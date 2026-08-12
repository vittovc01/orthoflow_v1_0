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

st.markdown('''
<style>
.block-container{max-width:1400px;padding-top:1rem;padding-bottom:3rem}
[data-testid="stSidebar"]{background:#0B1F2A}
[data-testid="stSidebar"] *{color:#F2FAF7!important}
.ddt-hero{padding:22px 24px;border-radius:22px;background:linear-gradient(135deg,#0B1F2A,#123B41 55%,#17805F);color:white;margin-bottom:18px}
.ddt-hero h1{color:white!important;margin:.2rem 0;font-size:2rem}.ddt-hero p{margin:0;opacity:.82}
[data-testid="stMetric"]{background:white;border:1px solid rgba(16,38,46,.08);border-radius:16px;padding:14px}
.stButton>button,.stDownloadButton>button{border-radius:12px!important;min-height:44px;font-weight:700}
@media(max-width:760px){.block-container{padding:.7rem}.ddt-hero{padding:17px}.ddt-hero h1{font-size:1.55rem}}
</style>
''', unsafe_allow_html=True)


def sb():
    url=st.secrets.get('SUPABASE_URL')
    key=st.secrets.get('SUPABASE_SERVICE_KEY') or st.secrets.get('SUPABASE_ANON_KEY') or st.secrets.get('SUPABASE_KEY')
    if not url or not key:
        st.error('Supabase non configurato nei Secrets.'); st.stop()
    return create_client(str(url).rstrip('/'),str(key))


def role(): return str(st.session_state.get('ruolo','')).strip()
def user(): return str(st.session_state.get('user','')).strip()

if not user():
    st.warning('Accedi prima a OrthoFlow Control Tower.'); st.stop()
if role() not in {'Admin','Magazzino'}:
    st.error('Area riservata ad Admin e Magazzino.'); st.stop()


def clean(v):
    if v is None or (isinstance(v,float) and pd.isna(v)): return ''
    return str(v).strip()


def mags():
    try:
        rows=sb().table('magazzini').select('*').execute().data or []
    except Exception:
        rows=[]
    labels=[]
    for r in rows:
        c=clean(r.get('codice_magazzino') or r.get('codice') or r.get('magazzino'))
        n=clean(r.get('nome_magazzino') or r.get('descrizione') or r.get('nome'))
        if c: labels.append(f'{c} - {n or c}')
    return labels or ['MAG1 - Magazzino 1']


def movimento_row(tipo, mag, codice, lotto, qta, descr='', scad=None, origine='CONTO DEPOSITO', ref_id=''):
    return {
        'tipo_movimento':tipo,'codice_magazzino':mag,'codice':codice,'descrizione':descr,
        'lotto':lotto,'scadenza':scad or None,'quantita':float(qta),'origine':origine,
        'riferimento_tipo':'DDT','riferimento_id':str(ref_id or ''),'note':'','utente':user()
    }


def chunks(rows,size=500):
    for i in range(0,len(rows),size): yield rows[i:i+size]


def batch_insert(table,rows,size=500):
    done=0
    for ch in chunks([x for x in rows if x],size):
        sb().table(table).insert(ch).execute(); done+=len(ch)
    return done


def parse_gs1(raw):
    text=str(raw or '').strip().replace('\u001d','|').removeprefix(']d2').removeprefix(']C1')
    out={'raw':text,'gtin':'','lotto':'','scadenza':''}
    for ai,val in re.findall(r'\((01|10|17)\)([^()]+)',text):
        val=val.strip('|')
        if ai=='01': out['gtin']=val[:14]
        elif ai=='10': out['lotto']=val
        elif ai=='17' and len(val)>=6:
            try: out['scadenza']=pd.to_datetime(val[:6],format='%y%m%d').date().isoformat()
            except Exception: pass
    if not out['gtin']:
        m=re.search(r'01(\d{14})',text)
        if m: out['gtin']=m.group(1)
    if not out['scadenza']:
        m=re.search(r'17(\d{6})',text)
        if m:
            try: out['scadenza']=pd.to_datetime(m.group(1),format='%y%m%d').date().isoformat()
            except Exception: pass
    if not out['lotto']:
        m=re.search(r'(?:^|\|)10([^|]+)',text)
        if m: out['lotto']=m.group(1)
    return out


def mapping_for(parsed):
    try:
        q=sb().table('codici_prodotto_scan').select('*')
        rows=(q.eq('gtin',parsed['gtin']).limit(1).execute().data if parsed.get('gtin') else q.eq('codice_scansionato',parsed['raw']).limit(1).execute().data) or []
        return rows[0] if rows else None
    except Exception:
        return None


def add_scan(raw):
    if not raw: return
    p=parse_gs1(raw); m=mapping_for(p) or {}
    new={
        'codice':clean(m.get('codice_articolo')),
        'descrizione':clean(m.get('descrizione')),
        'lotto':clean(p.get('lotto')),
        'scadenza':clean(p.get('scadenza')),
        'quantita':1.0,
        'produttore':'Johnson & Johnson / DePuy Synthes',
        'gtin':clean(p.get('gtin')),
        'codice_scansionato':clean(p.get('raw')),
    }
    rows=st.session_state.get('ddt_mobile_rows',[])
    # Se stessa combinazione codice/lotto/scadenza è già presente aumenta la quantità.
    matched=False
    for r in rows:
        if new['codice'] and r.get('codice')==new['codice'] and r.get('lotto')==new['lotto'] and r.get('scadenza')==new['scadenza']:
            r['quantita']=float(r.get('quantita') or 0)+1; matched=True; break
    if not matched: rows.append(new)
    st.session_state['ddt_mobile_rows']=rows


st.markdown('<div class="ddt-hero"><div>ORTHOFLOW CONTROL TOWER</div><h1>🚚 DDT carico mobile</h1><p>Scanner Johnson, foto DDT con OCR AI o import Excel. Verifica sempre i dati prima del carico definitivo.</p></div>', unsafe_allow_html=True)

labels=mags()
head1,head2=st.columns(2)
with head1:
    ml=st.selectbox('Magazzino destinazione',labels)
    mag=ml.split(' - ')[0]
with head2:
    tipo=st.selectbox('Tipo carico',['CONTO DEPOSITO','LOAN / CONTO VISIONE'])

scanner_tab, photo_tab, excel_tab, history_tab=st.tabs(['📷 Scanner Johnson','🤖 Foto DDT AI','📄 Import Excel','🕘 Storico'])

with scanner_tab:
    st.subheader('Scansione rapida delle confezioni')
    st.caption('Scansiona in sequenza i DataMatrix/codici Johnson. Le confezioni uguali vengono sommate automaticamente.')
    raw=''
    if qrcode_scanner is not None:
        raw=qrcode_scanner(key='ddt_johnson_scanner') or ''
    manual=st.text_input('Oppure incolla il valore letto dallo scanner',key='ddt_manual_scan')
    raw=raw or manual
    c1,c2=st.columns([1,1])
    if c1.button('➕ Aggiungi scansione',use_container_width=True,disabled=not bool(raw)):
        add_scan(raw); st.rerun()
    if c2.button('🧹 Svuota lista scansioni',use_container_width=True):
        st.session_state['ddt_mobile_rows']=[]; st.rerun()

    scan_df=pd.DataFrame(st.session_state.get('ddt_mobile_rows',[]))
    edited_scan=st.data_editor(scan_df if not scan_df.empty else pd.DataFrame(columns=['codice','descrizione','lotto','scadenza','quantita','produttore','gtin']),num_rows='dynamic',use_container_width=True,key='ddt_scan_editor')
    st.session_state['ddt_mobile_rows']=edited_scan.to_dict('records')

with photo_tab:
    status=ai_status()
    if status.get('enabled'):
        st.success(f"OCR AI attivo · modello {status.get('model','')}")
    else:
        st.warning('OCR AI non ancora attivo: '+', '.join(status.get('missing',[])))
    photo=st.file_uploader('Fotografa o carica il DDT',type=['jpg','jpeg','png','webp'],key='ddt_photo')
    if photo:
        path_dir='uploads/ddt'; import os; os.makedirs(path_dir,exist_ok=True)
        path=f"{path_dir}/{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}_{photo.name.replace('/','_')}"
        open(path,'wb').write(photo.getbuffer())
        st.image(photo,use_container_width=True)
        if st.button('🤖 Estrai DDT con AI',use_container_width=True):
            if not ai_enabled():
                st.error('OCR AI non configurato. Controlla OPENAI_API_KEY e ENABLE_AI_OCR=true nei Secrets.')
            else:
                try:
                    meta=analyze_image(path,mode='ddt')
                    st.session_state['ddt_ai_header']={
                        'numero_ddt':clean(meta.get('ddt_number')),
                        'data_ddt':clean(meta.get('ddt_date')),
                        'cliente':clean(meta.get('customer') or meta.get('destination')),
                    }
                    st.session_state['ddt_ai_rows']=normalize_ai_items(meta)
                    st.success(f"Righe rilevate: {len(st.session_state['ddt_ai_rows'])}. Verifica prima di salvare.")
                except Exception as e:
                    st.error(f'Errore OCR AI DDT: {e}')

    ai_rows=pd.DataFrame(st.session_state.get('ddt_ai_rows',[]))
    ai_edit=st.data_editor(ai_rows if not ai_rows.empty else pd.DataFrame(columns=['codice','descrizione','lotto','scadenza','quantita','produttore']),num_rows='dynamic',use_container_width=True,key='ddt_ai_editor')
    st.session_state['ddt_ai_rows']=ai_edit.to_dict('records')

with excel_tab:
    f=st.file_uploader('Excel DDT',type=['xlsx','xls'],key='ddt_excel')
    if f:
        import io
        d=pd.read_excel(io.BytesIO(f.getvalue())); d.columns=[str(c).strip() for c in d.columns]
        st.dataframe(d.head(30),use_container_width=True)
        cols=list(d.columns)
        def find_col(keys,default=0):
            for i,c in enumerate(cols):
                if any(k.lower() in str(c).lower() for k in keys): return i
            return default
        cod=st.selectbox('Codice',cols,index=find_col(['codice','articolo','ref']),key='ex_cod')
        lot=st.selectbox('Lotto',cols,index=find_col(['lotto','lot']),key='ex_lot')
        qty=st.selectbox('Quantità',cols,index=find_col(['quantità','quantita','qta','qty']),key='ex_qty')
        des=st.selectbox('Descrizione',['']+cols,index=0,key='ex_des')
        sca=st.selectbox('Scadenza',['']+cols,index=0,key='ex_sca')
        if st.button('Prepara righe Excel',use_container_width=True):
            rows=[]
            for _,x in d.iterrows():
                c=clean(x[cod]); l=clean(x[lot]);
                try: q=float(x[qty])
                except Exception: q=1
                if c and l:
                    rows.append({'codice':c,'descrizione':'' if not des else clean(x[des]),'lotto':l,'scadenza':'' if not sca else clean(x[sca]),'quantita':q,'produttore':''})
            st.session_state['ddt_excel_rows']=rows; st.rerun()
    exdf=pd.DataFrame(st.session_state.get('ddt_excel_rows',[]))
    exedit=st.data_editor(exdf if not exdf.empty else pd.DataFrame(columns=['codice','descrizione','lotto','scadenza','quantita','produttore']),num_rows='dynamic',use_container_width=True,key='ddt_excel_editor')
    st.session_state['ddt_excel_rows']=exedit.to_dict('records')

# Testata e salvataggio comune.
st.divider(); st.subheader('✅ Conferma e carica DDT')
source=st.radio('Usa righe da',['Scanner Johnson','Foto DDT AI','Import Excel'],horizontal=True)
header=st.session_state.get('ddt_ai_header',{}) if source=='Foto DDT AI' else {}
num=st.text_input('Numero DDT',value=header.get('numero_ddt',''),key='final_ddt_number')
parsed_date=pd.to_datetime(header.get('data_ddt'),errors='coerce') if header.get('data_ddt') else pd.NaT
ddt_date=st.date_input('Data DDT',value=parsed_date.date() if pd.notna(parsed_date) else date.today(),key='final_ddt_date')
cliente=st.text_input('Cliente / destinazione',value=header.get('cliente',''),key='final_ddt_client')

if source=='Scanner Johnson': final_rows=st.session_state.get('ddt_mobile_rows',[])
elif source=='Foto DDT AI': final_rows=st.session_state.get('ddt_ai_rows',[])
else: final_rows=st.session_state.get('ddt_excel_rows',[])

preview=pd.DataFrame(final_rows)
st.write(f'Righe da caricare: **{len(preview)}**')
if not preview.empty:
    show=[c for c in ['codice','descrizione','lotto','scadenza','quantita','produttore'] if c in preview.columns]
    st.dataframe(preview[show],use_container_width=True,hide_index=True)

confirm=st.checkbox('Confermo che numero DDT, data, codici, lotti, scadenze e quantità sono stati verificati.')
if st.button('🚚 Crea DDT e carica magazzino',type='primary',use_container_width=True,disabled=not confirm or preview.empty):
    if not clean(num):
        st.error('Inserisci il numero DDT.')
    else:
        try:
            ddt_res=sb().table('ddt').insert({'numero_ddt':clean(num),'data_ddt':ddt_date.isoformat(),'tipo_ddt':tipo,'cliente':clean(cliente),'codice_magazzino_destinazione':mag}).execute().data or []
            ddt=ddt_res[0]
            righe=[]; movs=[]; skipped=0
            for r in final_rows:
                c=clean(r.get('codice')); l=clean(r.get('lotto'))
                try: q=float(r.get('quantita') or 1)
                except Exception: q=1
                if not c or not l or q<=0:
                    skipped+=1; continue
                descr=clean(r.get('descrizione')); scad=clean(r.get('scadenza')) or None
                righe.append({'ddt_id':ddt['id'],'codice':c,'descrizione':descr,'lotto':l,'scadenza':scad,'quantita':q,'origine':tipo})
                movs.append(movimento_row('CARICO_DDT',mag,c,l,q,descr,scad,tipo,ddt['id']))
            n1=batch_insert('ddt_righe',righe,500); n2=batch_insert('movimenti_magazzino',movs,500)
            try: sb().table('audit_log').insert({'utente':user(),'ruolo':role(),'azione':'CARICO_DDT_MOBILE','tabella':'ddt','record_id':str(ddt['id']),'dettaglio':f'{source}; DDT {num}; righe {n1}'}).execute()
            except Exception: pass
            st.success(f'DDT {num} creato. Righe: {n1}. Movimenti: {n2}. Scartate: {skipped}.')
            st.session_state['ddt_mobile_rows']=[]; st.session_state['ddt_ai_rows']=[]; st.session_state['ddt_excel_rows']=[]; st.session_state['ddt_ai_header']={}
        except Exception as e:
            st.error(f'Carico DDT non eseguito: {e}')

with history_tab:
    try: hist=pd.DataFrame(sb().table('ddt').select('*').order('id',desc=True).limit(200).execute().data or [])
    except Exception as e: st.error(f'Errore storico DDT: {e}'); hist=pd.DataFrame()
    st.dataframe(hist,use_container_width=True,hide_index=True)
