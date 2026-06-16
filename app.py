import os, re
from datetime import date
from pathlib import Path
import pandas as pd
import streamlit as st
from supabase import create_client

try:
    from ai_ocr import ai_enabled, analyze_image, normalize_ai_items
except Exception:
    ai_enabled=lambda: False
    analyze_image=None
    normalize_ai_items=lambda x: []

st.set_page_config(page_title='OrthoFlow 6.0 Cloud', layout='wide')

def secret(name, default=None):
    try:
        if name in st.secrets: return st.secrets[name]
    except Exception: pass
    return os.getenv(name, default)

@st.cache_resource
def client():
    url=secret('SUPABASE_URL')
    key=secret('SUPABASE_SERVICE_KEY') or secret('SUPABASE_ANON_KEY') or secret('SUPABASE_KEY')
    if not url or not key: raise RuntimeError('Supabase non configurato nei Secrets')
    return create_client(str(url).rstrip('/'), str(key))

def sb(): return client()
@st.cache_data(ttl=120)
def df(table, order='id', desc=False):
    try: return pd.DataFrame(sb().table(table).select('*').order(order, desc=desc).execute().data or [])
    except Exception as e: st.error(f'Errore {table}: {e}'); return pd.DataFrame()
def ins(table, data): return sb().table(table).insert(data).execute().data[0]
def upsert(table, data, conflict): return sb().table(table).upsert(data, on_conflict=conflict).execute()

def chunks(items, size=500):
    for i in range(0, len(items), size):
        yield items[i:i+size]

def batch_insert(table, rows, size=500):
    rows = [r for r in rows if r]
    done = 0
    for ch in chunks(rows, size):
        sb().table(table).insert(ch).execute()
        done += len(ch)
    return done

def batch_upsert(table, rows, conflict, size=500):
    rows = [r for r in rows if r]
    done = 0
    for ch in chunks(rows, size):
        sb().table(table).upsert(ch, on_conflict=conflict).execute()
        done += len(ch)
    return done

def norm(d): d=d.copy(); d.columns=[str(c).strip() for c in d.columns]; return d
def money(v):
    if pd.isna(v): return None
    if isinstance(v,(int,float)): return float(v)
    s=str(v).replace('€','').replace(' ','').strip()
    if ',' in s and '.' in s: s=s.replace('.','').replace(',','.')
    elif ',' in s: s=s.replace(',','.')
    try: return float(s)
    except: return None
def clean(v):
    if pd.isna(v): return ''
    if isinstance(v,float) and v.is_integer(): return str(int(v))
    return str(v).strip()
def idx(cols, keys, default=0):
    for k in keys:
        if k in cols: return cols.index(k)
    for i,c in enumerate(cols):
        if any(str(k).lower() in str(c).lower() for k in keys): return i
    return default
def idxo(cols, keys):
    opts=['']+cols
    for k in keys:
        if k in cols: return opts.index(k)
    for c in cols:
        if any(str(k).lower() in str(c).lower() for k in keys): return opts.index(c)
    return 0
def ncode(c): return re.sub(r'[^A-Z0-9]','',str(c or '').upper().strip())
def save_file(upload):
    Path('uploads').mkdir(exist_ok=True); p=Path('uploads')/f"{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}_{upload.name.replace('/','_')}"; p.write_bytes(upload.getbuffer()); return str(p)
def validate_prod(t):
    u=str(t or '').upper()
    return 'Validato J&J' if any(x in u for x in ['J&J','JOHNSON','DEPUY','SYNTHES','DE PUY']) else ('Marchio non letto' if not u else 'Prodotto non J&J')
def excel_bytes(sheets):
    import io
    bio=io.BytesIO()
    with pd.ExcelWriter(bio, engine='xlsxwriter') as w:
        for n,d in sheets.items(): d.to_excel(w,index=False,sheet_name=n[:31])
    return bio.getvalue()

def mags():
    d=df('magazzini','nome_magazzino')
    if d.empty:
        try: upsert('magazzini', {'codice_magazzino':'MAG1','nome_magazzino':'Magazzino 1','tipo':'INTERNO'}, 'codice_magazzino'); d=df('magazzini','nome_magazzino')
        except Exception: pass
    return d
def clienti_opts():
    d=df('clienti','descrizione')
    return [{'label':str(r.descrizione),'codice_cliente':str(r.codice_cliente),'descrizione':str(r.descrizione)} for r in d.itertuples()] if not d.empty else []
@st.cache_data(ttl=60)
def price_map(codice_cliente, linea):
    links = sb().table('offerte_clienti').select('offerta_id').eq('codice_cliente', codice_cliente).execute().data or []
    ids = [int(x['offerta_id']) for x in links if x.get('offerta_id') is not None]
    if not ids:
        return {}

    heads = []
    for oid in ids:
        h = sb().table('offerte_header').select('id,linea').eq('id', oid).execute().data or []
        if h and str(h[0].get('linea','')).upper() == str(linea).upper():
            heads.append(oid)

    out = {}
    for oid in heads:
        start = 0
        step = 1000
        while True:
            rows = sb().table('offerte_prezzi').select('codice,prezzo').eq('offerta_id', oid).range(start, start + step - 1).execute().data or []
            for p in rows:
                out[ncode(p.get('codice'))] = float(p.get('prezzo') or 0)
            if len(rows) < step:
                break
            start += step
    return out

def prezzo_per(codice_cliente,codice,linea):
    return price_map(codice_cliente, linea).get(ncode(codice))
def movimento(tipo, mag, codice, lotto, qta, descr='', scad=None, origine='CONTO DEPOSITO', ref_tipo='', ref_id='', note=''):
    return ins('movimenti_magazzino', {'tipo_movimento':tipo,'codice_magazzino':mag,'codice':codice,'descrizione':descr,'lotto':lotto,'scadenza':scad or None,'quantita':float(qta),'origine':origine,'riferimento_tipo':ref_tipo,'riferimento_id':str(ref_id or ''),'note':note,'utente':st.session_state.get('user','')})
def disp(mag,codice,lotto):
    rows=sb().table('giacenze').select('*').eq('codice_magazzino',mag).eq('lotto',lotto).execute().data or []
    return sum(float(r.get('quantita') or 0) for r in rows if ncode(r.get('codice'))==ncode(codice))

# Login
if 'user' not in st.session_state:
    st.sidebar.title('OrthoFlow 6.0')
    with st.sidebar.form('login'):
        u=st.text_input('Utente','admin'); p=st.text_input('Password','admin',type='password'); ok=st.form_submit_button('Accedi')
    if ok:
        if (u,p)==('admin','Mastrota09@'): st.session_state.user=u; st.session_state.ruolo='Admin'; st.rerun()
        elif (u,p)==('collaboratore','1234'): st.session_state.user=u; st.session_state.ruolo='Collaboratore'; st.rerun()
        else: st.sidebar.error('Credenziali errate')
    st.title('OrthoFlow 6.0 Cloud'); st.stop()
st.sidebar.markdown('## 🏥 OrthoFlow 6.0')
st.sidebar.caption('Gestionale ortopedico cloud')
st.sidebar.success(f"{st.session_state.user} - {st.session_state.ruolo}")
if st.sidebar.button('Esci'): st.session_state.clear(); st.rerun()
admin=st.session_state.get('ruolo')=='Admin'
menu_admin=['Dashboard','Gestione dati','Clienti','Magazzini','Inventario','Offerte','DDT carico / Loan','Scarico sala','Work Implant','Customer Connect','KPI e Fatturato','Anomalie']
menu_collab=['Dashboard','Scarico sala']
menu=st.sidebar.radio('Menu', menu_admin if admin else menu_collab)
if 'quick_menu' in st.session_state:
    menu=st.session_state.pop('quick_menu')

if menu=='Dashboard':
    st.title('🏥 OrthoFlow 6.0 Cloud')
    st.caption('Dashboard operativa: accessi rapidi, KPI principali e controllo magazzino')

    if st.button('🔄 Aggiorna dati', use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    r=df('righe_intervento')
    clienti_df=df('clienti')
    giacenze_df=df('giacenze')
    interventi_df=df('interventi')
    movimenti_df=df('movimenti_magazzino')
    anomalie_df=df('anomalie')
    fatt=float(r['totale'].fillna(0).sum()) if not r.empty and 'totale' in r else 0

    c1,c2,c3,c4,c5=st.columns(5)
    c1.metric('Clienti',len(clienti_df))
    c2.metric('Giacenze',len(giacenze_df))
    c3.metric('Interventi',len(interventi_df))
    c4.metric('Movimenti',len(movimenti_df))
    c5.metric('Fatturato',f'€ {fatt:,.2f}')

    st.divider()
    st.subheader('⚡ Azioni rapide')
    q1,q2,q3,q4=st.columns(4)
    if q1.button('📸 Scarico sala',use_container_width=True):
        st.session_state.quick_menu='Scarico sala'
        st.rerun()
    if q2.button('📦 Inventario',use_container_width=True):
        st.session_state.quick_menu='Inventario'
        st.rerun()
    if q3.button('💰 Offerte',use_container_width=True):
        st.session_state.quick_menu='Offerte'
        st.rerun()
    if q4.button('🗄️ Gestione dati',use_container_width=True):
        st.session_state.quick_menu='Gestione dati'
        st.rerun()

    st.divider()
    a1,a2=st.columns(2)
    with a1:
        st.subheader('⚠️ Anomalie aperte')
        if not anomalie_df.empty:
            st.dataframe(anomalie_df.head(10),use_container_width=True,height=280)
        else:
            st.success('Nessuna anomalia presente')
    with a2:
        st.subheader('📦 Ultime giacenze')
        if not giacenze_df.empty:
            st.dataframe(giacenze_df.head(10),use_container_width=True,height=280)
        else:
            st.info('Nessuna giacenza presente')

elif menu=='Gestione dati':
    st.title('🗄️ Gestione dati')
    st.caption('Consultazione veloce delle principali tabelle operative')
    if st.button('🔄 Aggiorna tabelle', use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    tab=st.selectbox('Tabella da visualizzare',['clienti','magazzini','giacenze','movimenti_magazzino','interventi','righe_intervento','offerte_header','offerte_clienti','offerte_prezzi','ddt','ddt_righe','anomalie'])
    order_col=st.text_input('Ordina per colonna','id')
    desc=st.checkbox('Ordine decrescente',True)
    data=df(tab,order_col,desc)
    st.write(f'Righe visualizzate: {len(data)}')
    st.dataframe(data,use_container_width=True,height=520)
    if not data.empty:
        st.download_button('⬇️ Scarica Excel', excel_bytes({tab:data}), file_name=f'{tab}.xlsx', use_container_width=True)

elif menu=='Clienti':
    st.title('👥 Clienti')
    t1,t2=st.tabs(['Import ANAGRA','Clienti presenti'])
    with t1:
        f=st.file_uploader('ANAGRA Excel',type=['xlsx','xls'])
        if f:
            d=norm(pd.read_excel(f)); st.dataframe(d.head(30),use_container_width=True); cols=list(d.columns)
            cc=st.selectbox('Codice cliente',cols,index=idx(cols,['Codice','codice_cliente'])); de=st.selectbox('Descrizione',cols,index=idx(cols,['Descrizione','Cliente'],1 if len(cols)>1 else 0)); ci=st.selectbox('Città',['']+cols,index=idxo(cols,['Città','Citta'])); pr=st.selectbox('Provincia',['']+cols,index=idxo(cols,['Prov','Provincia'])); pv=st.selectbox('P.IVA',['']+cols,index=idxo(cols,['Partita Iva','PIVA','P.IVA']))
            if st.button('Importa clienti',use_container_width=True):
                rows=[]
                for _,x in d.iterrows():
                    cod=clean(x[cc])
                    if cod:
                        descr = '' if pd.isna(x[de]) else str(x[de])
                        rows.append({
                            'codice_cliente': cod,
                            'descrizione': descr,
                            'descrizione_cliente': descr,
                            'citta': '' if not ci else str(x[ci]),
                            'provincia': '' if not pr else str(x[pr]),
                            'piva': '' if not pv else str(x[pv])
                        })
                n = batch_upsert('clienti', rows, 'codice_cliente', size=500)
                st.success(f'Clienti importati/aggiornati: {n}')
    with t2: st.dataframe(df('clienti','descrizione'),use_container_width=True)
elif menu=='Magazzini':
    st.title('🏬 Magazzini')
    with st.form('mag'):
        cm=st.text_input('Codice magazzino','MAG1'); nm=st.text_input('Nome','Magazzino 1'); tipo=st.selectbox('Tipo',['INTERNO','STRUTTURA','LOAN']); cc=st.text_input('Codice cliente collegato',''); ok=st.form_submit_button('Salva')
    if ok: upsert('magazzini',{'codice_magazzino':cm,'nome_magazzino':nm,'tipo':tipo,'codice_cliente':cc},'codice_magazzino'); st.success('Salvato')
    st.dataframe(mags(),use_container_width=True)
elif menu=='Inventario':
    st.title('📦 Inventario')
    t1,t2,t3=st.tabs(['Import TTKEYS','Giacenze','Movimenti'])
    with t1:
        m=mags(); labels=[f'{r.codice_magazzino} - {r.nome_magazzino}' for r in m.itertuples()] if not m.empty else ['MAG1 - Magazzino 1']; ml=st.selectbox('Magazzino',labels); mag=ml.split(' - ')[0]; origine=st.selectbox('Origine',['CONTO DEPOSITO','LOAN / CONTO VISIONE'])
        f=st.file_uploader('TTKEYS / giacenze',type=['xlsx','xls'])
        if f:
            d=norm(pd.read_excel(f)); st.dataframe(d.head(30),use_container_width=True); cols=list(d.columns)
            cod=st.selectbox('Codice',cols,index=idx(cols,['Articolo','Codice'])); des=st.selectbox('Descrizione',['']+cols,index=idxo(cols,['Descr. articolo','Descrizione','Descr.'])); lot=st.selectbox('Lotto',cols,index=idx(cols,['Lotto','LOT'])); qty=st.selectbox('Quantità',cols,index=idx(cols,['Quantità','Quantita','Qta'])); sca=st.selectbox('Scadenza',['']+cols,index=idxo(cols,['Scadenza','EXP'])); only=st.checkbox('Solo quantità positive',True)
            if st.button('Importa giacenze',use_container_width=True):
                n=0
                prog = st.progress(0)
                total = len(d)
                for i,(_,x) in enumerate(d.iterrows(), start=1):
                    c=clean(x[cod]); l=clean(x[lot]); q=money(x[qty]) or 0
                    if c and l and not (only and q<=0):
                        movimento('CARICO_INIZIALE',mag,c,l,q,'' if not des else str(x[des]),None if not sca else str(x[sca]),origine,'IMPORT','TTKEYS')
                        n+=1
                    if i % 100 == 0 or i == total:
                        prog.progress(min(i/total, 1.0))
                st.success(f'Movimenti caricati: {n}')
    with t2: st.dataframe(df('giacenze','updated_at',True),use_container_width=True)
    with t3: st.dataframe(df('movimenti_magazzino','id',True),use_container_width=True)
elif menu=='Offerte':
    st.title('💰 Offerte')
    st.info('Import ottimizzato: i prezzi vengono caricati in blocchi da 500 righe. Il matching resta J&J Safe Match: 413.050S ≠ 413.050.')
    t1,t2,t3=st.tabs(['Crea','Import prezzi','Visualizza/Test'])
    with t1:
        with st.form('off'):
            nome=st.text_input('Nome offerta','Federico II Trauma'); linea=st.selectbox('Linea',['TRAUMA','PROTESICA','CMF','SPINE','SPORTS','ALTRO']); clienti=st.text_area('Codici clienti','9010062'); ok=st.form_submit_button('Crea offerta')
        if ok:
            h=ins('offerte_header',{'nome_offerta':nome,'linea':linea})
            for x in clienti.replace(',', '\n').splitlines():
                x=x.strip()
                if x: ins('offerte_clienti',{'offerta_id':h['id'],'codice_cliente':x})
            st.success(f"Offerta ID {h['id']}")
    with t2:
        o=df('offerte_header','id',True)
        if not o.empty:
            sel=st.selectbox('Offerta',[f'{r.id} - {r.nome_offerta} ({r.linea})' for r in o.itertuples()]); oid=int(sel.split(' - ')[0]); f=st.file_uploader('Excel prezzi',type=['xlsx','xls'])
            if f:
                d=norm(pd.read_excel(f)); st.dataframe(d.head(30),use_container_width=True); cols=list(d.columns); cod=st.selectbox('Codice',cols,index=idx(cols,['Codice Prodotto','Codice','Articolo'])); des=st.selectbox('Descrizione',['']+cols,index=idxo(cols,['Descrizione prodotto','Descrizione'])); pre=st.selectbox('Prezzo',cols,index=idx(cols,['Prezzo unitario offerto cifre e lettere','Prezzo','prezzo']))
                if st.button('Importa prezzi',use_container_width=True):
                    rows=[]
                    for _,x in d.iterrows():
                        c=clean(x[cod]); p=money(x[pre])
                        if c and p is not None:
                            rows.append({
                                'offerta_id': oid,
                                'codice': c,
                                'descrizione': '' if not des else str(x[des]),
                                'prezzo': p
                            })
                    n = batch_insert('offerte_prezzi', rows, size=500)
                    price_map.clear()
                    st.success(f'Prezzi importati: {n}')
    with t3:
        st.dataframe(df('offerte_header','id',True),use_container_width=True); st.dataframe(df('offerte_clienti','id',True),use_container_width=True); st.dataframe(df('offerte_prezzi','id',True),use_container_width=True)
elif menu=='DDT carico / Loan':
    st.title('🚚 DDT carico / Loan')
    t1,t2=st.tabs(['Import Excel','Storico'])
    with t1:
        labels=[f'{r.codice_magazzino} - {r.nome_magazzino}' for r in mags().itertuples()]; ml=st.selectbox('Magazzino destinazione',labels); mag=ml.split(' - ')[0]; tipo=st.selectbox('Tipo',['CONTO DEPOSITO','LOAN / CONTO VISIONE'])
        f=st.file_uploader('Excel DDT',type=['xlsx','xls'])
        if f:
            d=norm(pd.read_excel(f)); st.dataframe(d.head(30),use_container_width=True); cols=list(d.columns); cod=st.selectbox('Codice',cols,index=idx(cols,['Codice','Articolo','REF'])); lot=st.selectbox('Lotto',cols,index=idx(cols,['Lotto','LOT'])); qty=st.selectbox('Quantità',cols,index=idx(cols,['Quantità','Qta','Qty'])); des=st.selectbox('Descrizione',['']+cols,index=idxo(cols,['Descrizione','Descr.'])); sca=st.selectbox('Scadenza',['']+cols,index=idxo(cols,['Scadenza','EXP']))
            num=st.text_input('Numero DDT',''); cli=st.text_input('Cliente/destinazione','')
            if st.button('Crea DDT e carica magazzino',use_container_width=True):
                ddt=ins('ddt',{'numero_ddt':num,'data_ddt':str(date.today()),'tipo_ddt':tipo,'cliente':cli,'codice_magazzino_destinazione':mag}); n=0
                for _,x in d.iterrows():
                    c=clean(x[cod]); l=clean(x[lot]); q=money(x[qty]) or 1
                    if c and l: ins('ddt_righe',{'ddt_id':ddt['id'],'codice':c,'descrizione':'' if not des else str(x[des]),'lotto':l,'scadenza':None if not sca else str(x[sca]),'quantita':q,'origine':tipo}); movimento('CARICO_DDT',mag,c,l,q,'' if not des else str(x[des]),None if not sca else str(x[sca]),tipo,'DDT',ddt['id']); n+=1
                st.success(f'DDT {ddt["id"]} creato. Righe: {n}')
    with t2: st.dataframe(df('ddt','id',True),use_container_width=True); st.dataframe(df('ddt_righe','id',True),use_container_width=True)
elif menu=='Scarico sala':
    st.title('📸 Scarico sala')
    clienti=clienti_opts(); labels=[f'{r.codice_magazzino} - {r.nome_magazzino}' for r in mags().itertuples()]
    rows=[]
    up=st.file_uploader('Foto scarico sala',type=['jpg','jpeg','png'])
    if up:
        path=save_file(up); st.image(up,use_container_width=True)
        if st.button('Estrai OCR AI',use_container_width=True):
            if not ai_enabled(): st.error('OCR AI non configurato o quota API non disponibile')
            else:
                meta=analyze_image(path,mode='scarico_sala'); rows=normalize_ai_items(meta); st.session_state['scarico_rows']=rows; st.success(f'Righe estratte: {len(rows)}')
    edited=st.data_editor(pd.DataFrame(st.session_state.get('scarico_rows',[])) if st.session_state.get('scarico_rows') else pd.DataFrame(columns=['codice','descrizione','lotto','scadenza','quantita','produttore']),num_rows='dynamic',use_container_width=True)
    with st.form('intervento'):
        data_int=st.date_input('Data intervento',date.today()); cs=st.selectbox('Struttura',clienti,format_func=lambda x:x['label']) if clienti else {'codice_cliente':'','descrizione':''}; ml=st.selectbox('Scarica da giacenza',labels); mag=ml.split(' - ')[0]; agente=st.text_input('Agente',''); linea=st.selectbox('Linea',['TRAUMA','PROTESICA','CMF','SPINE','SPORTS','ALTRO']); ok=st.form_submit_button('Crea intervento e scarica')
    if ok:
        inter=ins('interventi',{'data_intervento':str(data_int),'codice_cliente':cs['codice_cliente'],'cliente':cs['descrizione'],'agente':agente,'linea':linea,'magazzino_scarico':mag}); fatt=0; n=0
        for _,x in edited.iterrows():
            c=clean(x.get('codice','')); l=clean(x.get('lotto','')); q=money(x.get('quantita')) or 1; descr=str(x.get('descrizione','') or ''); prod=str(x.get('produttore','') or '')
            if not c or not l: continue
            valid=validate_prod(prod)
            pr=prezzo_per(cs['codice_cliente'],c,linea)
            tot=pr*q if pr is not None else None
            if pr is None:
                ins('anomalie',{'tipo':'PREZZO_NON_TROVATO','gravita':'Media','descrizione':f'Intervento {inter["id"]}: prezzo non trovato per cliente {cs["codice_cliente"]}, linea {linea}, codice {c}. Verifica offerta e S sterile/non sterile.','stato':'Aperta'})
            ins('righe_intervento',{'intervento_id':inter['id'],'codice':c,'descrizione':descr,'lotto':l,'scadenza':str(x.get('scadenza','') or '') or None,'quantita':q,'produttore':prod,'validazione':valid,'origine':'CONTO DEPOSITO','prezzo':pr,'totale':tot,'reintegro':True})
            if disp(mag,c,l)<q: ins('anomalie',{'tipo':'GIACENZA_INSUFFICIENTE','gravita':'Alta','descrizione':f'Intervento {inter["id"]}: {c} lotto {l} disponibile {disp(mag,c,l)} richiesta {q}','stato':'Aperta'})
            movimento('SCARICO_INTERVENTO',mag,c,l,-abs(q),descr,str(x.get('scadenza','') or '') or None,'CONTO DEPOSITO','INTERVENTO',inter['id']); fatt+=tot or 0; n+=1
        st.success(f'Intervento {inter["id"]} creato. Righe: {n}. Fatturato: € {fatt:,.2f}')
elif menu=='Work Implant': st.title('📄 Work Implant'); st.dataframe(df('righe_intervento','id',True),use_container_width=True)
elif menu=='Customer Connect':
    st.title('🔁 Customer Connect'); r=df('righe_intervento')
    if not r.empty: st.dataframe(r.groupby('codice',as_index=False)['quantita'].sum(),use_container_width=True)
elif menu=='KPI e Fatturato':
    st.title('📊 KPI e Fatturato'); r=df('righe_intervento'); st.metric('Fatturato teorico', f"€ {float(r['totale'].fillna(0).sum()) if not r.empty and 'totale' in r else 0:,.2f}"); st.dataframe(r,use_container_width=True)
elif menu=='Anomalie': st.title('⚠️ Anomalie'); st.dataframe(df('anomalie','id',True),use_container_width=True)
