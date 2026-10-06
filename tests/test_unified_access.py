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
    with TestClient(app, base_url='https://testserver') as client:
        client.headers['Origin'] = 'https://testserver'
        yield client, backend, app


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


def test_office_pages_and_assets_do_not_wait_for_an_inbound_body(tmp_path, monkeypatch):
    from starlette.requests import Request
    import mobile.office_proxy as gateway
    monkeypatch.setattr(gateway, 'streamlit_static_root', lambda: None)
    original = httpx.AsyncClient
    seen = []
    pools = []

    class AssetStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'office asset'

    async def upstream(request):
        seen.append((request.method, request.url.path, request.headers))
        assert await request.aread() == b''
        assert 'upstream_private' not in request.headers.get('cookie', '')
        return httpx.Response(200, stream=AssetStream(),
                              headers={'set-cookie': 'upstream_private=test; Path=/'})

    def pooled_client(**kwargs):
        pool = original(transport=httpx.MockTransport(upstream), **kwargs)
        pools.append(pool)
        return pool

    monkeypatch.setattr(gateway.httpx, 'AsyncClient', pooled_client)
    monkeypatch.setenv('MOBILE_PUBLIC_ORIGIN', 'https://testserver')
    backend = Backend()
    backend.tables['utenti_app'].append(user(4, 'direzione', ['DIREZIONE']))
    app = create_app(lambda: backend, tmp_path/'sessions.sqlite')

    original_stream = Request.stream

    def pending_body(request):
        # Starlette's middleware may consume its own cached request to watch
        # disconnects. Only the proxy's request must never be streamed.
        if type(request) is Request and request.method in {'GET', 'HEAD'}:
            raise AssertionError('Body-less page requests must not read the receive channel')
        return original_stream(request)

    monkeypatch.setattr(Request, 'stream', pending_body)
    with TestClient(app, base_url='https://testserver') as client:
        client.headers['Origin'] = 'https://testserver'
        login(client, 'direzione')
        assert client.get('/office/?module=gestionale').status_code == 200
        # Simulate a different browser which did not receive the Set-Cookie.
        client.cookies.delete('upstream_private')
        assert client.get('/office/static/js/index.js').content == b'office asset'
        client.cookies.delete('upstream_private')
        assert client.head('/office/static/js/index.js').status_code == 200
        assert len(pools) == 1
        assert not pools[0].is_closed
    assert pools[0].is_closed
    assert len(seen) == 3
    assert all('transfer-encoding' not in headers for _, _, headers in seen)
    assert all('content-length' not in headers for _, _, headers in seen)


def test_supabase_pool_reused_without_caching_permissions(tmp_path, monkeypatch):
    import mobile.app as mobile_app
    backend = Backend()
    backend.tables['utenti_app'].append(user(4, 'direzione', ['DIREZIONE']))
    created = []
    for name in ('ALL_PROXY', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'http_proxy', 'https_proxy'):
        monkeypatch.delenv(name, raising=False)
    def factory(url, key, options):
        assert options.httpx_client._transport._pool._http2 is False
        created.append(options.httpx_client)
        return backend
    monkeypatch.setenv('SUPABASE_URL', 'https://test.invalid')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'synthetic-test-key')
    monkeypatch.setenv('MOBILE_PUBLIC_ORIGIN', 'https://testserver')
    monkeypatch.setattr(mobile_app, 'create_client', factory)
    app = create_app(session_path=tmp_path/'sessions.sqlite')
    with TestClient(app, base_url='https://testserver') as client:
        client.headers['Origin'] = 'https://testserver'
        login(client, 'direzione')
        assert client.get('/api/config').status_code == 200
        backend.tables['utenti_app'][-1]['attivo'] = False
        assert client.get('/api/config').status_code == 401
    assert len(created) == 1
    assert created[0].is_closed


def test_packaged_assets_bypass_loopback_but_require_live_permissions(setup, tmp_path, monkeypatch):
    import mobile.office_proxy as gateway
    root = tmp_path/'bundle'
    (root/'static'/'js').mkdir(parents=True)
    (root/'static'/'js'/'index.js').write_text('console.log("synthetic");')
    (root/'private.txt').write_text('must stay private')
    monkeypatch.setattr(gateway, 'streamlit_static_root', lambda: root)
    client, backend, app = setup
    asset = '/office/static/js/index.js'
    assert client.get(asset).status_code == 401
    login(client, 'mario')
    assert client.get(asset).status_code == 403
    login(client, 'direzione')
    response = client.get(asset)
    assert response.status_code == 200
    assert response.content == b'console.log("synthetic");'
    assert 'javascript' in response.headers['content-type']
    assert client.head(asset).status_code == 200
    assert client.get('/office/static/js/missing.js').status_code == 404
    assert client.get('/office/static/%2e%2e/private.txt').status_code == 404
    backend.tables['utenti_app'][-2]['attivo'] = False
    assert client.get(asset).status_code == 401
