"""Authenticated, same-origin gateway to the existing office workflows.

The office process listens on loopback only. Every HTTP request and WebSocket
is checked against the app session; no second public login or shared password.
"""
import asyncio
from contextlib import suppress

import httpx
from fastapi import HTTPException, Request, WebSocket
from fastapi.responses import RedirectResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from websockets.asyncio.client import connect

from mobile.access import COOKIE, MODULES, authenticated, modules_for, office_allowed

UPSTREAM = 'http://127.0.0.1:8501'
HOP = {'host', 'connection', 'keep-alive', 'transfer-encoding', 'upgrade', 'proxy-authorization', 'proxy-authenticate', 'te', 'trailer'}


def install_office(app, backend, public_origin):
    def identity(cookies):
        sb = backend()
        row = authenticated(cookies.get(COOKIE, ''), app.state.sessions, sb)
        if not office_allowed(row):
            raise HTTPException(403, 'Funzione non autorizzata per il tuo utente.')
        return row

    @app.api_route('/office', methods=['GET', 'HEAD'])
    def root(request: Request):
        identity(request.cookies)
        return RedirectResponse('/office/', status_code=307)

    @app.api_route('/office/{path:path}', methods=['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
    async def office(request: Request, path: str):
        row = await run_in_threadpool(identity, request.cookies)
        route = path.strip('/')
        if route in {m[0] for m in MODULES} and route not in {m['path'] for m in modules_for(row)}:
            raise HTTPException(403, 'Funzione non autorizzata per il tuo utente.')
        # Join on a fixed loopback origin; path is never interpreted as a URL.
        url = httpx.URL(UPSTREAM).copy_with(raw_path=request.url.path.encode() +
            (b'?' + request.scope.get('query_string', b'') if request.scope.get('query_string') else b''))
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
        client = httpx.AsyncClient(timeout=httpx.Timeout(90, connect=5), follow_redirects=False, trust_env=False)
        try:
            response = await client.send(client.build_request(request.method, url, headers=headers, content=request.stream()), stream=True)
        except httpx.HTTPError:
            await client.aclose()
            raise HTTPException(503, 'Modulo in avvio. Riprova tra pochi secondi.')
        async def close():
            await response.aclose()
            await client.aclose()
        result = StreamingResponse(response.aiter_raw(), status_code=response.status_code,
            background=BackgroundTask(close))
        result.raw_headers = [(k, v) for k, v in response.headers.raw if k.decode().lower() not in HOP]
        result.headers['Cache-Control'] = 'no-store'
        return result

    @app.websocket('/office/{path:path}')
    async def office_socket(ws: WebSocket, path: str):
        expected = public_origin()
        if not expected:
            import os
            if os.getenv('MOBILE_LOCAL_DEV') == 'true':
                expected = 'http://' + ws.headers.get('host', '')
        try:
            if not expected or ws.headers.get('origin') != expected:
                raise HTTPException(403)
            await run_in_threadpool(identity, ws.cookies)
        except HTTPException:
            await ws.close(code=1008)
            return
        protocols = [x.strip() for x in ws.headers.get('sec-websocket-protocol', '').split(',') if x.strip()]
        headers = {k: v for k, v in ws.headers.items()
                   if k.lower() not in HOP and not k.lower().startswith('sec-websocket-')}
        target = 'ws://127.0.0.1:8501' + ws.url.path
        if ws.scope.get('query_string'):
            target += '?' + ws.scope['query_string'].decode()
        try:
            async with connect(target, additional_headers=headers, subprotocols=protocols,
                               max_size=45 * 1024 * 1024, compression=None, proxy=None) as upstream:
                await ws.accept(subprotocol=upstream.subprotocol)
                async def to_office():
                    while True:
                        message = await ws.receive()
                        if message['type'] == 'websocket.disconnect':
                            break
                        await run_in_threadpool(identity, ws.cookies)
                        await upstream.send(message.get('bytes') if message.get('bytes') is not None else message.get('text', ''))
                async def to_browser():
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await ws.send_bytes(message)
                        else:
                            await ws.send_text(message)
                async def revalidate():
                    while True:
                        await asyncio.sleep(15)
                        await run_in_threadpool(identity, ws.cookies)
                tasks = [asyncio.create_task(fn()) for fn in (to_office, to_browser, revalidate)]
                try:
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            # Neither upstream errors nor session values go to the browser/log.
            pass
        finally:
            with suppress(Exception):
                await ws.close(code=1008)
