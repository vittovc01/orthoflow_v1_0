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
    from ai_ocr import ai_enabled, ai_status, analyze_image, normalize_ai_items
except Exception:
    ai_enabled=lambda: False
    ai_status=lambda: {'enabled':False,'missing':['OCR AI non disponibile'],'model':''}
    analyze_image=None
    normalize_ai_items=lambda x: []

st.set_page_config(page_title='DDT Mobile · OrthoFlow Control Tower', page_icon='🚚', layout='wide')


def sb():
    url=st.secrets.get('SUPABASE_URL')
    key=st.secrets.get('SUPABASE_SERVICE_KEY') or st.secrets.get('SUPABASE_ANON_KEY') or st.secrets.get('SUPABASE_KEY')
    if not url or not key:
        st.error('Supabase non configurato nei Secrets.'); st.stop()
    return create_client(str(url).rstrip('/'),str(key))

def role(): return str(st.session_state.get('ruolo','')).strip()
def user(): return str(st.session_state.get('user','')).strip()
def clean(v): return '' if v is None or (isinstance(v,float) and pd.isna(v)) else str(v).strip()

if not user(): st.warning('Accedi prima a OrthoFlow Control Tower.'); st.stop()
if role() not in {'Admin','Magazzino'}: st.error('Area riservata ad Admin e Magazzino.'); st.stop()


def gs1_date(yymmdd):
    try:
        return pd.to_datetime(yymmdd,format='%y%m%d',errors='raise').date().isoformat()
    except Exception:
        return ''


def normalize_scan(raw):
    text=str(raw or '')
    text=text.replace('\\u001d','\x1d').replace('<GS>','\x1d').replace('[GS]','\x1d')
    text=text.strip()
    for prefix in (']d2',']D2',']C1',']c1'):
        if text.startswith(prefix): text=text[len(prefix):]
    return text


def parse_gs1(raw):
    """Parser GS1 per DataMatrix J&J: AI 01 GTIN, 17 scadenza, 10 lotto, 21 seriale."""
    text=normalize_scan(raw)
    out={'raw':text,'gtin':'','lotto':'','scadenza':'','seriale':''}
    if not text:
        return out

    # Formato human readable: (01)...(17)...(10)...
    for ai,val in re.findall(r'\((01|10|17|21)\)(.*?)(?=\((?:01|10|17|21)\)|$)',text):
        val=val.strip().strip('\x1d')
        if ai=='01': out['gtin']=re.sub(r'\D','',val)[:14]
        elif ai=='17': out['scadenza']=gs1_date(re.sub(r'\D','',val)[:6])
        elif ai=='10': out['lotto']=val
        elif ai=='21': out['seriale']=val

    if out['gtin'] and (out['lotto'] or out['scadenza']):
        return out

    # Tokenizzazione tramite FNC1/Group Separator.
    parts=[p for p in text.split('\x1d') if p]
    for part in parts:
        cursor=0
        while cursor < len(part):
            if part.startswith('01',cursor) and len(part)>=cursor+16:
                candidate=part[cursor+2:cursor+16]
                if candidate.isdigit(): out['gtin']=candidate; cursor+=16; continue
            if part.startswith('17',cursor) and len(part)>=cursor+8:
                candidate=part[cursor+2:cursor+8]
                if candidate.isdigit(): out['scadenza']=gs1_date(candidate); cursor+=8; continue
            if part.startswith('10',cursor):
                value=part[cursor+2:]
                # Se il lotto non è ultimo e compare un AI fisso valido, troncalo lì.
                cut=len(value)
                m17=re.search(r'17\d{6}',value)
                if m17: cut=min(cut,m17.start())
                m21=re.search(r'21',value)
                if m21 and m21.start()>0: cut=min(cut,m21.start())
                out['lotto']=value[:cut].strip(); cursor=len(part); continue
            if part.startswith('21',cursor):
                out['seriale']=part[cursor+2:].strip(); cursor=len(part); continue
            cursor+=1

    # Fallback molto comune J&J: 01 + 14 GTIN + 17 + YYMMDD + 10 + LOTTO
    compact=text.replace('\x1d','')
    m=re.search(r'01(\d{14})',compact)
    if m and not out['gtin']: out['gtin']=m.group(1)
    m17=re.search(r'17(\d{6})',compact)
    if m17 and not out['scadenza']: out['scadenza']=gs1_date(m17.group(1))

    if not out['lotto']:
        # Lotto dopo AI 10: preferisci 10 successivo alla scadenza/GTIN per evitare falsi match nel GTIN.
        start=0
        if m17: start=m17.end()
        elif m: start=m.end()
        pos=compact.find('10',start)
        if pos>=0:
            lot=compact[pos+2:]
            # 21 può seguire il lotto; in GS1 dovrebbe esserci FNC1, ma alcuni browser lo perdono.
            serial_pos=lot.find('21')
            if serial_pos>0:
                maybe_serial=lot[serial_pos+2:]
                if maybe_serial: out['seriale']=maybe_serial; lot=lot[:serial_pos]
            out['lotto']=lot.strip()

    return out


def mapping_for(parsed):
    try:
        q=sb().table('codici_prodotto_scan').select('*')
        if parsed.get('gtin'):
            rows=q.eq('gtin',parsed['gtin']).limit(1).execute().data or []
        else:
            rows=q.eq('codice_scansionato',parsed['raw']).limit(1).execute().data or []
        return rows[0] if rows else None
    except Exception:
        return None


def mags():
    try: rows=sb().table('magazzini').select('*').execute().data or []
    except Exception: rows=[]
    labels=[]
    for r in rows:
        c=clean(r.get('codice_magazzino') or r.get('codice') or r.get('magazzino'))
        n=clean(r.get('nome_magazzino') or r.get('descrizione') or r.get('nome'))
        if c: labels.append(f'{c} - {n or c}')
    return labels or ['MAG1 - Magazzino 1']


def add_scan(raw):
    p=parse_gs1(raw); m=mapping_for(p) or {}
    new={'codice':clean(m.get('codice_articolo')),'descrizione':clean(m.get('descrizione')),'lotto':clean(p['lotto']),'scadenza':clean(p['scadenza']),'quantita':1.0,'produttore':'Johnson & Johnson / DePuy Synthes','gtin':clean(p['gtin']),'seriale':clean(p['seriale'])}
    st.session_state['last_gs1_debug']=p
    rows=st.session_state.get('ddt_mobile_rows',[])
    for r in rows:
        if r.get('gtin')==new['gtin'] and r.get('lotto')==new['lotto'] and r.get('scadenza')==new['scadenza'] and new['gtin']:
            r['quantita']=float(r.get('quantita') or 0)+1
            st.session_state['ddt_mobile_rows']=rows
            return
    rows.append(new); st.session_state['ddt_mobile_rows']=rows


def batch_insert(table,rows,size=500):
    done=0
    for i in range(0,len(rows),size):
        ch=rows[i:i+size]
        if ch: sb().table(table).insert(ch).execute(); done+=len(ch)
    return done

st.title('🚚 DDT carico mobile')
st.caption('Scanner GS1/DataMatrix Johnson + OCR AI del DDT. Il decoder legge AI 01 (GTIN), 17 (scadenza), 10 (lotto) e 21 (seriale).')

c1,c2=st.columns(2)
with c1:
    ml=st.selectbox('Magazzino destinazione',mags()); mag=ml.split(' - ')[0]
with c2:
    tipo=st.selectbox('Tipo carico',['CONTO DEPOSITO','LOAN / CONTO VISIONE'])

scan_tab,photo_tab,history_tab=st.tabs(['📷 Scanner Johnson','🤖 Foto DDT AI','🕘 Storico'])

with scan_tab:
    st.subheader('Scanner veloce Johnson')
    raw=''
    if qrcode_scanner is not None:
        raw=qrcode_scanner(key='ddt_johnson_scanner_v2') or ''
    manual=st.text_input('Valore scanner / test manuale',key='manual_gs1_v2')
    raw=raw or manual
    if raw:
        p=parse_gs1(raw)
        a,b,c,d=st.columns(4)
        a.metric('GTIN',p['gtin'] or '—'); b.metric('Lotto',p['lotto'] or '—'); c.metric('Scadenza',p['scadenza'] or '—'); d.metric('Seriale',p['seriale'] or '—')
        with st.expander('Diagnostica lettura GS1'):
            st.code(repr(p['raw']))
            st.json(p)
    x,y=st.columns(2)
    if x.button('➕ Aggiungi scansione',use_container_width=True,disabled=not bool(raw)):
        add_scan(raw); st.rerun()
    if y.button('🧹 Svuota lista',use_container_width=True):
        st.session_state['ddt_mobile_rows']=[]; st.rerun()
    sdf=pd.DataFrame(st.session_state.get('ddt_mobile_rows',[]))
    sed=st.data_editor(sdf if not sdf.empty else pd.DataFrame(columns=['codice','descrizione','lotto','scadenza','quantita','produttore','gtin','seriale']),num_rows='dynamic',use_container_width=True,key='ddt_scan_editor_v2')
    st.session_state['ddt_mobile_rows']=sed.to_dict('records')

with photo_tab:
    status=ai_status()
    if status.get('enabled'): st.success(f"OCR AI attivo · {status.get('model','')}")
    else: st.warning('OCR AI non attivo: '+', '.join(status.get('missing',[])))
    photo=st.file_uploader('Fotografa o carica il DDT',type=['jpg','jpeg','png','webp'],key='ddt_photo_v2')
    if photo:
        import os
        os.makedirs('uploads/ddt',exist_ok=True)
        path=f"uploads/ddt/{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}_{photo.name.replace('/','_')}"
        open(path,'wb').write(photo.getbuffer()); st.image(photo,use_container_width=True)
        if st.button('🤖 Estrai DDT con AI',use_container_width=True):
            try:
                meta=analyze_image(path,mode='ddt')
                st.session_state['ddt_ai_header']={'numero_ddt':clean(meta.get('ddt_number')),'data_ddt':clean(meta.get('ddt_date')),'cliente':clean(meta.get('customer') or meta.get('destination'))}
                st.session_state['ddt_ai_rows']=normalize_ai_items(meta)
                st.success(f"Righe rilevate: {len(st.session_state['ddt_ai_rows'])}")
            except Exception as e: st.error(f'Errore OCR AI DDT: {e}')
    adf=pd.DataFrame(st.session_state.get('ddt_ai_rows',[]))
    aed=st.data_editor(adf if not adf.empty else pd.DataFrame(columns=['codice','descrizione','lotto','scadenza','quantita','produttore']),num_rows='dynamic',use_container_width=True,key='ddt_ai_editor_v2')
    st.session_state['ddt_ai_rows']=aed.to_dict('records')

st.divider(); st.subheader('✅ Conferma DDT')
source=st.radio('Righe da',['Scanner Johnson','Foto DDT AI'],horizontal=True)
header=st.session_state.get('ddt_ai_header',{}) if source=='Foto DDT AI' else {}
num=st.text_input('Numero DDT',value=header.get('numero_ddt',''))
pd_date=pd.to_datetime(header.get('data_ddt'),errors='coerce') if header.get('data_ddt') else pd.NaT
ddt_date=st.date_input('Data DDT',value=pd_date.date() if pd.notna(pd_date) else date.today())
cliente=st.text_input('Cliente / destinazione',value=header.get('cliente',''))
rows=st.session_state.get('ddt_mobile_rows',[]) if source=='Scanner Johnson' else st.session_state.get('ddt_ai_rows',[])
preview=pd.DataFrame(rows)
if not preview.empty: st.dataframe(preview,use_container_width=True,hide_index=True)
confirm=st.checkbox('Ho verificato numero DDT, data, codice, lotto, scadenza e quantità.')
if st.button('🚚 Crea DDT e carica magazzino',type='primary',use_container_width=True,disabled=not confirm or preview.empty):
    if not clean(num): st.error('Inserisci il numero DDT.')
    else:
        try:
            ddt=(sb().table('ddt').insert({'numero_ddt':clean(num),'data_ddt':ddt_date.isoformat(),'tipo_ddt':tipo,'cliente':clean(cliente),'codice_magazzino_destinazione':mag}).execute().data or [])[0]
            righe=[]; movs=[]
            for r in rows:
                c=clean(r.get('codice')); l=clean(r.get('lotto')); q=float(r.get('quantita') or 1)
                if not c or not l or q<=0: continue
                desc=clean(r.get('descrizione')); scad=clean(r.get('scadenza')) or None
                righe.append({'ddt_id':ddt['id'],'codice':c,'descrizione':desc,'lotto':l,'scadenza':scad,'quantita':q,'origine':tipo})
                movs.append({'tipo_movimento':'CARICO_DDT','codice_magazzino':mag,'codice':c,'descrizione':desc,'lotto':l,'scadenza':scad,'quantita':q,'origine':tipo,'riferimento_tipo':'DDT','riferimento_id':str(ddt['id']),'note':'','utente':user()})
            n1=batch_insert('ddt_righe',righe); n2=batch_insert('movimenti_magazzino',movs)
            st.success(f'DDT {num} creato. Righe: {n1}. Movimenti: {n2}.')
            st.session_state['ddt_mobile_rows']=[]; st.session_state['ddt_ai_rows']=[]; st.session_state['ddt_ai_header']={}
        except Exception as e: st.error(f'Carico DDT non eseguito: {e}')

with history_tab:
    try: hist=pd.DataFrame(sb().table('ddt').select('*').order('id',desc=True).limit(200).execute().data or [])
    except Exception as e: st.error(f'Errore storico DDT: {e}'); hist=pd.DataFrame()
    st.dataframe(hist,use_container_width=True,hide_index=True)
