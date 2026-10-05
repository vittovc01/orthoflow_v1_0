import pytest
import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from mobile.app import create_app
from mobile.access import authenticated, modules_for
from tests.fixtures.mobile_backend import Backend, user


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('MOBILE_PUBLIC_ORIGIN', 'https://testserver')
    backend = Backend()
    backend.tables['utenti_app'] += [user(4,'direzione',['DIREZIONE']), user(5,'magazzino',['LOGISTICA'])]
    app = create_app(lambda:backend, tmp_path/'sessions.sqlite')
    client = TestClient(app, base_url='https://testserver')
    client.headers['Origin'] = 'https://testserver'
    return client, backend, app


def login(client, name):
    assert client.post('/api/login',json={'username':name,'password':'test-password'}).status_code == 200


def test_director_sees_all_office_modules_and_courier_sees_none(setup):
    client, backend, app = setup
    login(client, 'direzione')
    paths = {x['path'] for x in client.get('/api/config').json()['modules']}
    assert {'gestionale','utenti-permessi','wms','ddt-carico-mobile','gestione-interventi'} <= paths
    login(client, 'mario')
    assert client.get('/api/config').json()['modules'] == []
    assert client.get('/office/utenti-permessi').status_code == 403
    assert client.get('/office/_stcore/health').status_code == 403


def test_agent_and_warehouse_cannot_open_director_pages(setup):
    client, backend, app = setup
    for name in ('agente','magazzino'):
        login(client,name)
        assert client.get('/office/utenti-permessi').status_code == 403
        assert client.get('/office/?module=utenti-permessi').status_code == 403
        if name=='agente':
            assert client.get('/office/gestionale').status_code == 403
    assert {x['path'] for x in client.get('/api/config').json()['modules']} == {
        'ddt-carico-mobile','wms','gestione-scaffale','qr-scaffali','documenti-logistica','corrieri','gestionale'}


def test_shared_identity_revalidates_role_and_session(setup):
    client, backend, app = setup
    row = backend.tables['utenti_app'][0]
    token = app.state.sessions.issue(row)
    assert authenticated(token, app.state.sessions, backend)['username'] == 'mario'
    row['permessi'] = ['DIREZIONE']
    assert any(x['path']=='utenti-permessi' for x in modules_for(authenticated(token,app.state.sessions,backend)))
    row['attivo'] = False
    with pytest.raises(HTTPException) as error:
        authenticated(token,app.state.sessions,backend)
    assert error.value.status_code == 401
    assert app.state.sessions.get(token) is None


def test_office_http_and_websocket_require_valid_session(setup):
    client, backend, app = setup
    assert client.get('/office/').status_code == 401
    with pytest.raises(Exception):
        with client.websocket_connect('/office/_stcore/stream',headers={'origin':'https://testserver'}):
            pass
    login(client,'direzione')
    with pytest.raises(Exception):
        with client.websocket_connect('/office/_stcore/stream',headers={'origin':'https://attacker.invalid'}):
            pass


def test_office_headers_allow_only_same_origin_frame(setup):
    client, _, _ = setup
    response = client.get('/office/')
    assert response.headers['x-frame-options'] == 'SAMEORIGIN'
    assert "frame-ancestors 'self'" in response.headers['content-security-policy']
    assert response.headers['cache-control'] == 'no-store'
    shell = client.get('/')
    assert shell.headers['x-frame-options'] == 'DENY'


def test_office_pages_and_assets_do_not_wait_for_an_inbound_body(setup, monkeypatch):
    from starlette.requests import Request
    import mobile.office_proxy as gateway
    client, _, _ = setup
    login(client, 'direzione')
    original = httpx.AsyncClient
    seen = []

    async def upstream(request):
        seen.append((request.method, request.url.path, request.headers))
        assert await request.aread() == b''
        return httpx.Response(200, content=b'office asset')

    monkeypatch.setattr(gateway.httpx, 'AsyncClient', lambda **kw:
                        original(transport=httpx.MockTransport(upstream), **kw))

    def pending_body(_):
        raise AssertionError('Body-less page requests must not read the receive channel')

    monkeypatch.setattr(Request, 'stream', pending_body)
    assert client.get('/office/?module=gestionale').status_code == 200
    assert client.get('/office/static/js/index.js').content == b'office asset'
    assert client.head('/office/static/js/index.js').status_code == 200
    assert len(seen) == 3
    assert all('transfer-encoding' not in headers for _, _, headers in seen)
