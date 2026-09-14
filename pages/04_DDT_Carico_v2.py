import re
from datetime import date

import pandas as pd
import streamlit as st
from supabase import create_client

try:
    from streamlit_qrcode_scanner import qrcode_scanner
except Exception:
    qrcode_scanner = None
try:
    from ai_ocr import ai_status, analyze_document, normalize_ai_items
except Exception:
    ai_status = lambda: {'enabled': False, 'missing': ['OCR AI non disponibile'], 'model': ''}
    analyze_document = None
    normalize_ai_items = lambda x: []

st.set_page_config(page_title='DDT Mobile · OrthoFlow Control Tower', page_icon='🚚', layout='wide')


def sb():
    url = st.secrets.get('SUPABASE_URL')
    key = st.secrets.get('SUPABASE_SERVICE_KEY') or st.secrets.get('SUPABASE_ANON_KEY') or st.secrets.get('SUPABASE_KEY')
    if not url or not key:
        st.error('Supabase non configurato nei Secrets.')
        st.stop()
    return create_client(str(url).rstrip('/'), str(key))


def role(): return str(st.session_state.get('ruolo', '')).strip()
def user(): return str(st.session_state.get('user', '')).strip()
def clean(v): return '' if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


if not user():
    st.warning('Accedi prima a OrthoFlow Control Tower.')
    st.stop()
if role() not in {'Admin', 'Magazzino'}:
    st.error('Area riservata ad Admin e Magazzino.')
    st.stop()


def gs1_date(v):
    try:
        return pd.to_datetime(v, format='%y%m%d', errors='raise').date().isoformat()
    except Exception:
        return ''


def normalize_scan(raw):
    text = str(raw or '').replace('\\u001d', '\x1d').replace('<GS>', '\x1d').replace('[GS]', '\x1d').strip()
    for p in (']d2', ']D2', ']C1', ']c1'):
        if text.startswith(p):
            text = text[len(p):]
    return text


def parse_gs1(raw):
    text = normalize_scan(raw)
    out = {'raw': text, 'gtin': '', 'lotto': '', 'scadenza': '', 'seriale': ''}
    if not text:
        return out
    for ai, val in re.findall(r'\((01|10|17|21)\)(.*?)(?=\((?:01|10|17|21)\)|$)', text):
        val = val.strip().strip('\x1d')
        if ai == '01': out['gtin'] = re.sub(r'\D', '', val)[:14]
        elif ai == '17': out['scadenza'] = gs1_date(re.sub(r'\D', '', val)[:6])
        elif ai == '10': out['lotto'] = val
        elif ai == '21': out['seriale'] = val
    compact = text.replace('\x1d', '')
    m = re.search(r'01(\d{14})', compact)
    m17 = re.search(r'17(\d{6})', compact)
    if m and not out['gtin']: out['gtin'] = m.group(1)
    if m17 and not out['scadenza']: out['scadenza'] = gs1_date(m17.group(1))
    if not out['lotto']:
        start = m17.end() if m17 else (m.end() if m else 0)
        pos = compact.find('10', start)
        if pos >= 0:
            lot = compact[pos + 2:]
            sp = lot.find('21')
            if sp > 0:
                out['seriale'] = lot[sp + 2:]
                lot = lot[:sp]
            out['lotto'] = lot.strip()
    return out


def mapping_for(p):
    try:
        q = sb().table('codici_prodotto_scan').select('*')
        rows = (q.eq('gtin', p['gtin']).limit(1).execute().data if p.get('gtin') else q.eq('codice_scansionato', p['raw']).limit(1).execute().data) or []
        return rows[0] if rows else None
    except Exception:
        return None


def save_mapping(p, code, desc=''):
    code = clean(code).upper()
    if not code or not p.get('gtin'):
        return False
    try:
        sb().table('codici_prodotto_scan').upsert({
            'codice_scansionato': clean(p['raw']), 'gtin': clean(p['gtin']),
            'codice_articolo': code, 'descrizione': clean(desc), 'attivo': True
        }, on_conflict='codice_scansionato').execute()
        return True
    except Exception as e:
        st.error(f'Impossibile salvare associazione GTIN → codice Johnson: {e}')
        return False


def mags():
    try:
        rows = sb().table('magazzini').select('*').execute().data or []
    except Exception:
        rows = []
    labels = []
    for r in rows:
        c = clean(r.get('codice_magazzino') or r.get('codice') or r.get('magazzino'))
        n = clean(r.get('nome_magazzino') or r.get('descrizione') or r.get('nome'))
        if c:
            labels.append(f'{c} - {n or c}')
    return labels or ['MAG1 - Magazzino 1']


def add_scan(raw):
    p = parse_gs1(raw)
    m = mapping_for(p) or {}
    code = clean(m.get('codice_articolo')).upper()
    new = {
        'codice': code, 'descrizione': clean(m.get('descrizione')), 'lotto': clean(p['lotto']),
        'scadenza': clean(p['scadenza']), 'quantita': 1.0,
        'produttore': 'Johnson & Johnson / DePuy Synthes', 'gtin': clean(p['gtin']),
        'seriale': clean(p['seriale'])
    }
    rows = st.session_state.get('ddt_mobile_rows', [])
    for r in rows:
        if r.get('codice') == code and r.get('lotto') == new['lotto'] and r.get('scadenza') == new['scadenza'] and code:
            r['quantita'] = float(r.get('quantita') or 0) + 1
            st.session_state['ddt_mobile_rows'] = rows
            return
    rows.append(new)
    st.session_state['ddt_mobile_rows'] = rows


def atomic_ddt(header, rows):
    payload_rows = []
    errors = []
    for idx, r in enumerate(rows, start=1):
        code = clean(r.get('codice')).upper()
        lot = clean(r.get('lotto'))
        try:
            qty = float(r.get('quantita') or 0)
        except Exception:
            qty = 0
        if not code or not lot or qty <= 0:
            errors.append(f'Riga {idx}: servono codice, lotto e quantità > 0')
            continue
        payload_rows.append({
            'codice': code,
            'descrizione': clean(r.get('descrizione')),
            'lotto': lot,
            'scadenza': clean(r.get('scadenza')) or None,
            'quantita': qty,
        })
    if errors:
        raise ValueError(' | '.join(errors))
    result = sb().rpc('crea_ddt_carico', {
        'p_header': header,
        'p_rows': payload_rows,
        'p_utente': user(),
    }).execute().data
    return result or {}


st.title('🚚 DDT carico mobile')
st.caption('Carica PDF/foto DDT con AI oppure usa lo scanner Johnson. Il salvataggio di DDT, righe e magazzino è atomico: o riesce tutto oppure non viene scritto nulla.')
c1, c2 = st.columns(2)
with c1:
    ml = st.selectbox('Magazzino destinazione', mags())
    mag = ml.split(' - ')[0]
with c2:
    tipo = st.selectbox('Tipo carico', ['CONTO DEPOSITO', 'LOAN / CONTO VISIONE'])

scan_tab, photo_tab, history_tab = st.tabs(['📷 Scanner Johnson', '🤖 PDF / Foto DDT AI', '🕘 Storico'])
with scan_tab:
    st.subheader('Scanner veloce Johnson')
    raw = ''
    if qrcode_scanner is not None:
        raw = qrcode_scanner(key='ddt_johnson_scanner_v4') or ''
    raw = raw or st.text_input('Valore scanner / test manuale', key='manual_gs1_v4')
    parsed = parse_gs1(raw) if raw else {'raw': '', 'gtin': '', 'lotto': '', 'scadenza': '', 'seriale': ''}
    mapped = mapping_for(parsed) if raw else None
    ref = clean((mapped or {}).get('codice_articolo')).upper()
    if raw:
        a, b, c, d = st.columns(4)
        a.metric('Codice Johnson / REF', ref or 'DA ASSOCIARE')
        b.metric('Lotto', parsed['lotto'] or '—')
        c.metric('Scadenza', parsed['scadenza'] or '—')
        d.metric('GTIN', parsed['gtin'] or '—')
        if not ref and parsed.get('gtin'):
            with st.form('associate_ref_v4'):
                nr = st.text_input('Codice Johnson / REF', placeholder='es. 413.030S').upper()
                nd = st.text_input('Descrizione (opzionale)')
                ok = st.form_submit_button('💾 Associa GTIN al codice Johnson')
            if ok and nr and save_mapping(parsed, nr, nd):
                st.success('Associazione salvata.')
                st.rerun()
    x, y = st.columns(2)
    if x.button('➕ Aggiungi scansione', disabled=not bool(raw and ref), use_container_width=True):
        add_scan(raw)
        st.rerun()
    if y.button('🧹 Svuota lista', use_container_width=True):
        st.session_state['ddt_mobile_rows'] = []
        st.rerun()
    sdf = pd.DataFrame(st.session_state.get('ddt_mobile_rows', []))
    sed = st.data_editor(
        sdf if not sdf.empty else pd.DataFrame(columns=['codice', 'descrizione', 'lotto', 'scadenza', 'quantita', 'produttore', 'gtin', 'seriale']),
        num_rows='dynamic', use_container_width=True, key='ddt_scan_editor_v4'
    )
    st.session_state['ddt_mobile_rows'] = sed.to_dict('records')

with photo_tab:
    status = ai_status()
    if status.get('enabled'):
        st.success(f"OCR AI attivo · {status.get('model', '')}")
    else:
        st.warning('OCR AI non attivo: ' + ', '.join(status.get('missing', [])))
    doc = st.file_uploader('Carica DDT PDF oppure foto', type=['pdf', 'jpg', 'jpeg', 'png', 'webp'], key='ddt_document_v4', help='Puoi caricare direttamente il PDF originale Johnson anche se contiene più pagine.')
    if doc:
        import os
        os.makedirs('uploads/ddt', exist_ok=True)
        path = f"uploads/ddt/{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}_{doc.name.replace('/', '_')}"
        open(path, 'wb').write(doc.getbuffer())
        if doc.type == 'application/pdf' or doc.name.lower().endswith('.pdf'):
            st.info(f'📄 PDF pronto: {doc.name} · {len(doc.getvalue())/1024:.0f} KB')
        else:
            st.image(doc, use_container_width=True)
        if st.button('🤖 Analizza DDT completo con AI', type='primary', use_container_width=True):
            try:
                with st.spinner('Analisi di tutte le pagine del DDT in corso...'):
                    meta = analyze_document(path, mode='ddt')
                st.session_state['ddt_ai_header'] = {
                    'numero_ddt': clean(meta.get('ddt_number')),
                    'data_ddt': clean(meta.get('ddt_date')),
                    'cliente': clean(meta.get('customer') or meta.get('destination')),
                }
                st.session_state['ddt_ai_rows'] = normalize_ai_items(meta)
                st.session_state['ddt_source'] = 'Foto DDT AI'
                st.success(f"Analisi completata: {len(st.session_state['ddt_ai_rows'])} righe spedite rilevate.")
            except Exception as e:
                st.error(f'Errore OCR AI DDT: {e}')
    adf = pd.DataFrame(st.session_state.get('ddt_ai_rows', []))
    aed = st.data_editor(
        adf if not adf.empty else pd.DataFrame(columns=['codice', 'descrizione', 'lotto', 'scadenza', 'quantita', 'produttore']),
        num_rows='dynamic', use_container_width=True, key='ddt_ai_editor_v4'
    )
    st.session_state['ddt_ai_rows'] = aed.to_dict('records')

st.divider()
st.subheader('✅ Conferma DDT')

def source_changed():
    st.session_state['ddt_source'] = st.session_state.get('ddt_source_radio', 'Scanner Johnson')

source = st.radio(
    'Righe da', ['Scanner Johnson', 'Foto DDT AI'], horizontal=True, key='ddt_source_radio',
    index=1 if st.session_state.get('ddt_source') == 'Foto DDT AI' else 0, on_change=source_changed
)
header = st.session_state.get('ddt_ai_header', {}) if source == 'Foto DDT AI' else {}
num = st.text_input('Numero DDT', value=header.get('numero_ddt', ''))
pdate = pd.to_datetime(header.get('data_ddt'), errors='coerce') if header.get('data_ddt') else pd.NaT
ddt_date = st.date_input('Data DDT', value=pdate.date() if pd.notna(pdate) else date.today())
cliente = st.text_input('Cliente / destinazione', value=header.get('cliente', ''))
rows = st.session_state.get('ddt_mobile_rows', []) if source == 'Scanner Johnson' else st.session_state.get('ddt_ai_rows', [])
preview = pd.DataFrame(rows)
if not preview.empty:
    st.dataframe(preview, use_container_width=True, hide_index=True)
confirm = st.checkbox('Ho verificato numero DDT, data, codice Johnson, lotto, scadenza e quantità.')

if st.button('🚚 Crea DDT e carica magazzino', type='primary', use_container_width=True, disabled=not confirm or preview.empty):
    if not clean(num):
        st.error('Inserisci il numero DDT.')
    else:
        try:
            result = atomic_ddt({
                'numero_ddt': clean(num),
                'data_ddt': ddt_date.isoformat(),
                'tipo_ddt': tipo,
                'cliente': clean(cliente),
                'codice_magazzino_destinazione': mag,
            }, rows)
            st.success(f"DDT {num} creato in modo atomico. Righe: {int(result.get('righe', 0))}. ID: {result.get('ddt_id', '')}.")
            st.session_state['ddt_mobile_rows'] = []
            st.session_state['ddt_ai_rows'] = []
            st.session_state['ddt_ai_header'] = {}
            st.cache_data.clear()
        except Exception as e:
            msg = str(e)
            if 'DDT_DUPLICATO' in msg or 'duplicate' in msg.lower():
                st.error('Questo DDT risulta già caricato per la stessa data, tipologia e magazzino. Nessun nuovo movimento è stato creato.')
            else:
                st.error(f'Carico DDT non eseguito: {e}')

with history_tab:
    try:
        hist = pd.DataFrame(sb().table('ddt').select('*').order('id', desc=True).limit(200).execute().data or [])
    except Exception as e:
        st.error(f'Errore storico DDT: {e}')
        hist = pd.DataFrame()
    st.dataframe(hist, use_container_width=True, hide_index=True)
