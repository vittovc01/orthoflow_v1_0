"""Run: uvicorn mobile.app:app --host 0.0.0.0 --port 8000.
Privileged Supabase credentials are read only here, on the server.
"""
import io
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from supabase import create_client
from starlette.concurrency import run_in_threadpool

from mobile.models import Complete, ExportItems, Login, Scarico, Stamp
from mobile.security import Sessions, TTL, fingerprint, password_ok
from mobile import service as s

STATIC = Path(__file__).parent / 'static'
COOKIE = 'orthoflow_mobile'
USER_COLUMNS = 'id,username,nome_completo,ruolo,permessi,agente_nome,attivo,stato_accesso,password_hash'
log = logging.getLogger('orthoflow.mobile')


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] in ('GET', 'HEAD', 'OPTIONS'):
            return await self.app(scope, receive, send)
        # Stop oversized streaming bodies even if Content-Length is absent or forged.
        messages, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            size += len(message.get('body', b''))
            if size > 45 * 1024 * 1024:
                response = JSONResponse({'detail': 'Massimo 40 MB per caricamento.'}, status_code=413)
                return await response(scope, receive, send)
            messages.append(message)
            if not message.get('more_body'):
                break
        async def replay():
            if messages:
                return messages.pop(0)
            return await receive()
        await self.app(scope, replay, send)


def create_app(backend_factory=None, session_path=None):
    app = FastAPI(title='OrthoFlow mobile', docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BodyLimit)
    app.state.sessions = Sessions(session_path or Path(os.getenv('MOBILE_DATA_DIR', '/tmp/orthoflow-mobile')) / 'sessions.sqlite')

    def backend():
        if backend_factory:
            return backend_factory()
        url, key = os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_KEY')
        if not url or not key:
            raise HTTPException(503, 'Servizio mobile non ancora configurato.')
        return create_client(url.rstrip('/'), key)

    def secure_cookie():
        return os.getenv('MOBILE_LOCAL_DEV', 'false').lower() != 'true'

    def context(request: Request):
        token = request.cookies.get(COOKIE, '')
        session = app.state.sessions.get(token)
        if not session:
            raise HTTPException(401, 'Accedi per continuare.')
        sb = backend()
        found = s.rows(sb.table('utenti_app').select(USER_COLUMNS).eq('id', session[0]).limit(1))
        if not found or not found[0].get('attivo') or found[0].get('stato_accesso') != 'APPROVATO' or fingerprint(found[0]) != session[1]:
            app.state.sessions.revoke(token)
            raise HTTPException(401, 'Sessione non più valida. Accedi nuovamente.')
        return sb, found[0]

    @app.middleware('http')
    async def headers_and_origin(request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            expected = os.getenv('MOBILE_PUBLIC_ORIGIN', '').rstrip('/')
            if not expected and os.getenv('MOBILE_LOCAL_DEV') == 'true':
                expected = str(request.base_url).rstrip('/')
            if not expected:
                return JSONResponse({'detail': 'Indirizzo pubblico mobile non configurato.'}, status_code=503)
            if request.headers.get('origin') != expected:
                return JSONResponse({'detail': 'Richiesta da origine non autorizzata.'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data: https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
        response.headers['Permissions-Policy'] = 'geolocation=(self), camera=(self), microphone=()'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        if secure_cookie():
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.exception_handler(Exception)
    async def error(request, exc):
        messages = {
            'MOBILE_STAMP_REQUIRED': 'Registra prima l’arrivo in struttura.',
            'MOBILE_CERTIFICATE_REQUIRED': 'Archivia certificazione e firma, oppure seleziona ritiro senza firma.',
            'MOBILE_SIGNATURE_STATUS_REQUIRED': 'Scegli ritiro con firma o senza firma.',
            'MOBILE_MISSION_CLOSED': 'La missione è già completata.',
            'MOBILE_MISSION_UNAVAILABLE': 'Missione non disponibile per il tuo utente.',
            'MOBILE_INVALID_STATE': 'Lo stato della missione non permette questa operazione.',
        }
        message = getattr(exc, 'message', None)
        if message in messages:
            return JSONResponse({'detail': messages[message]}, status_code=422)
        # Never return database messages, file paths, credentials or clinical values.
        log.error('Mobile operation failed: %s', type(exc).__name__)
        return JSONResponse({'detail': 'Operazione non completata. Riprova; se persiste contatta la Direzione.'}, status_code=503)

    @app.get('/health')
    def health():
        configured = bool(backend_factory) or bool(os.getenv('SUPABASE_URL') and os.getenv('SUPABASE_SERVICE_KEY') and os.getenv('MOBILE_PUBLIC_ORIGIN'))
        status = 'ok' if configured else 'not_configured'
        if configured:
            try:
                backend().table('clienti').select('codice_cliente').limit(1).execute()
            except Exception:
                status = 'backend_unavailable'
        data = {'status': status, 'version': os.getenv('RENDER_GIT_COMMIT') or os.getenv('GIT_SHA') or 'unconfigured'}
        return JSONResponse(data, status_code=200 if status == 'ok' else 503)

    @app.post('/api/login')
    def login(body: Login, request: Request, response: Response):
        if not app.state.sessions.throttle('user:' + body.username.strip().lower()):
            raise HTTPException(429, 'Troppi tentativi. Riprova tra 15 minuti.')
        sb = backend()
        found = s.rows(sb.table('utenti_app').select('*').eq('username', body.username.strip()).limit(1))
        row = found[0] if found else {}
        # Also perform the hash for a missing username.
        valid = password_ok(body.password, row.get('password_salt', 'dummy'), row.get('password_hash', ''))
        if not valid or not row.get('attivo') or row.get('stato_accesso') != 'APPROVATO':
            raise HTTPException(401, 'Credenziali errate o accesso non approvato.')
        old = request.cookies.get(COOKIE)
        if old:
            app.state.sessions.revoke(old)
        token = app.state.sessions.issue(row)
        response.set_cookie(COOKIE, token, httponly=True, secure=secure_cookie(), samesite='strict', max_age=TTL, path='/')
        return public_user(row)

    def public_user(row):
        return {k: row.get(k) for k in ('username', 'nome_completo', 'ruolo', 'permessi', 'agente_nome')}

    @app.get('/api/me')
    def me(ctx=Depends(context)):
        return public_user(ctx[1])

    @app.post('/api/logout')
    def logout(request: Request, response: Response):
        app.state.sessions.revoke(request.cookies.get(COOKIE, ''))
        response.delete_cookie(COOKIE, path='/', httponly=True, secure=secure_cookie(), samesite='strict')
        return {'ok': True}

    @app.get('/api/config')
    def config(ctx=Depends(context)):
        link = os.getenv('ORTHOFLOW_DESKTOP_URL', '')
        if urlsplit(link).scheme != 'https':
            link = ''
        return {'desktop_url': link}

    @app.get('/api/missions')
    def missions(ctx=Depends(context)):
        sb, row = ctx
        s.require(row, 'CORRIERE')
        q = sb.table('missioni_corrieri').select('*')
        if row.get('ruolo') != 'Admin' and 'DIREZIONE' not in (row.get('permessi') or []):
            linked = s.rows(sb.table('corrieri').select('id').eq('user_id', row['id']).eq('attivo', True))
            if not linked:
                return {'missions': [], 'notice': 'La Direzione deve collegare il tuo profilo corriere.'}
            q = q.in_('corriere_id', [c['id'] for c in linked])
        data = s.rows(q.order('data_missione', desc=True).limit(200))
        ids = list({m['struttura_id'] for m in data if m.get('struttura_id')})
        structures = s.rows(sb.table('strutture_logistiche').select('id,nome,indirizzo,note_consegna,telefono').in_('id', ids)) if ids else []
        mapping = {x['id']: x for x in structures}
        for m in data:
            m['structure'] = mapping.get(m['struttura_id'], {})
        return {'missions': data, 'notice': ''}

    @app.get('/api/missions/{mid}')
    def detail(mid: int, ctx=Depends(context)):
        sb, row = ctx
        m = s.mission(sb, row, mid)
        structures = s.rows(sb.table('strutture_logistiche').select('id,nome,indirizzo,note_consegna,telefono').eq('id', m['struttura_id']).limit(1))
        m['structure'] = structures[0] if structures else {}
        assets = []
        for table in ('foto_missioni', 'documenti_missioni'):
            for rec in s.rows(sb.table(table).select('*').eq('missione_id', mid).order('id')):
                signed = sb.storage.from_(s.BUCKET).create_signed_url(rec['storage_path'], 300)
                assets.append({'id': rec['id'], 'kind': 'photo' if table == 'foto_missioni' else 'document',
                               'url': signed.get('signedURL') or signed.get('signedUrl'),
                               'label': rec.get('tipo_documento') or rec.get('tipo'), 'signer': rec.get('nome_firmatario')})
        return {'mission': m, 'assets': assets}

    def mission_rpc(sb, row, mid, action, payload):
        s.mission(sb, row, mid)
        return sb.rpc('orthoflow_mobile_mission', {'p_user_id': row['id'], 'p_mission_id': mid,
                      'p_action': action, 'p_payload': payload}).execute().data

    @app.post('/api/missions/{mid}/stamp')
    def stamp(mid: int, body: Stamp, ctx=Depends(context)):
        sb, row = ctx
        return mission_rpc(sb, row, mid, 'STAMP', body.model_dump())

    @app.post('/api/missions/{mid}/complete')
    def complete(mid: int, body: Complete, ctx=Depends(context)):
        sb, row = ctx
        return mission_rpc(sb, row, mid, 'COMPLETE', body.model_dump())

    @app.post('/api/missions/{mid}/photos')
    async def photos(mid: int, request: Request, ctx=Depends(context)):
        sb, row = ctx
        s.mission(sb, row, mid)
        form = await request.form(max_files=20, max_fields=20)
        files = form.getlist('files')
        if not 1 <= len(files) <= 20:
            raise HTTPException(422, 'Seleziona da 1 a 20 foto.')
        saved = 0
        # Sequential per file: report partial success without asking to resend everything.
        for file in files:
            data, mime, ext = s.validated_file(await file.read(s.MAX_FILE + 1), file.filename)
            path = await run_in_threadpool(s.upload, sb, f'missioni/{mid}/foto', data, mime, ext)
            try:
                await run_in_threadpool(mission_rpc, sb, row, mid, 'PHOTO', {'path': path})
                saved += 1
            except Exception:
                await run_in_threadpool(sb.storage.from_(s.BUCKET).remove, [path])
                return JSONResponse({'detail': f'{saved} foto salvate. Le altre non sono state archiviate; ricarica solo quelle.'}, status_code=503)
        return {'saved': saved}

    @app.post('/api/missions/{mid}/certificate')
    async def certificate(mid: int, request: Request, ctx=Depends(context)):
        sb, row = ctx
        m = s.mission(sb, row, mid)
        if m['tipo'] != 'RITIRO':
            raise HTTPException(422, 'Certificazione prevista per i ritiri.')
        form = await request.form(max_files=2, max_fields=5)
        signer, role = str(form.get('signer') or '').strip(), str(form.get('role') or '').strip()
        if not signer or not role or len(signer) > 200 or len(role) > 200:
            raise HTTPException(422, 'Inserisci nome e ruolo del firmatario.')
        if not form.get('file') or not form.get('signature'):
            raise HTTPException(422, 'Allega il certificato e la firma.')
        uploaded = []
        try:
            for key in ('file', 'signature'):
                file = form[key]
                data, mime, ext = s.validated_file(await file.read(s.MAX_FILE + 1), file.filename, allow_pdf=key == 'file')
                if key == 'signature':
                    from PIL import Image, ImageStat
                    image = Image.open(io.BytesIO(data)).convert('L')
                    if ImageStat.Stat(image).stddev[0] < 1:
                        raise HTTPException(422, 'La firma risulta vuota.')
                path = await run_in_threadpool(s.upload, sb, f'missioni/{mid}/documenti', data, mime, ext)
                uploaded.append(path)
            return await run_in_threadpool(mission_rpc, sb, row, mid, 'CERTIFICATE',
                {'path': uploaded[0], 'signature_path': uploaded[1], 'signer': signer, 'role': role})
        except Exception:
            if uploaded:
                await run_in_threadpool(sb.storage.from_(s.BUCKET).remove, uploaded)
            raise

    @app.get('/api/scarico/options')
    def options(ctx=Depends(context)):
        sb, row = ctx
        return {'customers': s.customers(sb, row),
                'warehouses': s.rows(sb.table('magazzini').select('codice_magazzino,nome_magazzino').order('id').limit(1000)),
                'can_price': s.allowed(row, 'AMMINISTRAZIONE')}

    @app.post('/api/scarico/analyze')
    async def analyze(request: Request, ctx=Depends(context)):
        sb, row = ctx
        s.agent_access(row)
        # Limits also apply to OCR calls, without sharing another user's drafts.
        if not app.state.sessions.throttle('ocr:' + str(row['id'])):
            raise HTTPException(429, 'Limite temporaneo di analisi raggiunto. Riprova tra 15 minuti.')
        form = await request.form(max_files=20, max_fields=5)
        files = form.getlist('files')
        if not 1 <= len(files) <= 20:
            raise HTTPException(422, 'Seleziona da 1 a 20 foto o PDF.')
        from ai_ocr import analyze_document, normalize_ai_items
        result = {'items': [], 'documents': len(files), 'header': {}}
        with TemporaryDirectory(prefix='orthoflow-ocr-') as tmp:
            for i, file in enumerate(files):
                data, mime, ext = s.validated_file(await file.read(s.MAX_FILE + 1), file.filename, allow_pdf=True)
                path = Path(tmp) / f'{i}{ext}'
                path.write_bytes(data)
                raw = await run_in_threadpool(analyze_document, str(path), 'scarico_sala')
                result['items'].extend(normalize_ai_items(raw))
                if not result['header']:
                    result['header'] = {k: raw.get(k) for k in ('procedure_date', 'clinical_record', 'surgeon', 'clinic_name')}
        return result

    @app.post('/api/scarico/preview')
    def preview(body: Scarico, ctx=Depends(context)):
        header, items = s.build_scarico(*ctx, body)
        return {'header': header, 'items': items, 'total': sum(x['quantita'] * x['prezzo'] for x in items)}

    @app.post('/api/scarico/save')
    def save(body: Scarico, ctx=Depends(context)):
        sb, row = ctx
        header, items = s.build_scarico(sb, row, body)
        return sb.rpc('orthoflow_mobile_scarico', {'p_user_id': row['id'], 'p_request_id': body.request_id,
                      'p_header': header, 'p_rows': items}).execute().data

    @app.post('/api/scarico/export')
    def export(body: ExportItems, ctx=Depends(context)):
        s.agent_access(ctx[1])
        from openpyxl import Workbook
        book = Workbook()
        sheet = book.active
        sheet.title = 'Codici'
        sheet.append(['Codice', 'Lotto', 'Quantità', 'Descrizione', 'Scadenza', 'Conto deposito struttura'])
        for r in body.items:
            # Plain text cells prevent spreadsheet formula injection from OCR.
            vals = [r.code, r.lot, r.quantity, r.description, str(r.expiry or ''), 'Sì' if r.structure_stock else 'No']
            sheet.append(vals)
            for col in (1, 2, 4, 5, 6):
                sheet.cell(sheet.max_row, col).data_type = 's'
        output = io.BytesIO()
        book.save(output)
        return Response(output.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename="OrthoFlow_Codici.xlsx"'})

    @app.post('/api/scarico/{intervention_id}/originals')
    async def originals(intervention_id: int, request: Request, ctx=Depends(context)):
        sb, row = ctx
        s.agent_access(row)
        found = s.rows(sb.table('interventi').select('id,agente,data_intervento,codice_cliente,cliente,cartella_clinica')
                       .eq('id', intervention_id).limit(1))
        if not found:
            raise HTTPException(404, 'Intervento non disponibile.')
        h = found[0]
        # Authorizes through the idempotency record, not a caller supplied agent name.
        own = s.rows(sb.table('orthoflow_mobile_operations').select('request_id').eq('user_id', row['id'])
                     .eq('intervento_id', intervention_id).limit(1))
        if not own:
            raise HTTPException(404, 'Intervento non disponibile.')
        form = await request.form(max_files=20, max_fields=5)
        files = form.getlist('files')
        if not 1 <= len(files) <= 20:
            raise HTTPException(422, 'Seleziona da 1 a 20 documenti.')
        saved = 0
        for file in files:
            data, mime, ext = s.validated_file(await file.read(s.MAX_FILE + 1), file.filename, allow_pdf=True)
            path = await run_in_threadpool(s.upload, sb, f'impianti/mobile/{intervention_id}', data, mime, ext)
            try:
                rec = {'intervento_id': str(intervention_id), 'data_intervento': h['data_intervento'],
                       'codice_cliente': h['codice_cliente'], 'cliente': h['cliente'], 'agente': h['agente'],
                       'cartella_clinica': h['cartella_clinica'], 'nome_file': Path(file.filename or 'documento').name[:200],
                       'tipo_file': mime, 'storage_bucket': s.BUCKET, 'storage_path': path,
                       'note': 'Documento originale acquisito da OrthoFlow mobile'}
                await run_in_threadpool(lambda: sb.table('documenti_impianto').insert(rec).execute())
                saved += 1
            except Exception:
                await run_in_threadpool(sb.storage.from_(s.BUCKET).remove, [path])
                return JSONResponse({'detail': f'Intervento salvato; {saved} documenti archiviati. Ricarica gli altri dall’archivio.'}, status_code=503)
        return {'saved': saved}

    @app.get('/')
    def index():
        return FileResponse(STATIC / 'index.html', headers={'Cache-Control': 'no-cache'})

    @app.get('/sw.js')
    def worker():
        return FileResponse(STATIC / 'sw.js', media_type='application/javascript', headers={'Cache-Control': 'no-cache'})

    app.mount('/static', StaticFiles(directory=STATIC), name='static')
    return app


app = create_app()
