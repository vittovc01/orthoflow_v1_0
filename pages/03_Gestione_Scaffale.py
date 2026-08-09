import re
from datetime import date
import pandas as pd
import streamlit as st
from supabase import create_client

try:
    from streamlit_qrcode_scanner import qrcode_scanner
except Exception:
    qrcode_scanner = None

st.set_page_config(page_title='Gestione Scaffale · OrthoFlow', page_icon='📚', layout='wide')


def sb():
    url=st.secrets.get('SUPABASE_URL')
    key=st.secrets.get('SUPABASE_SERVICE_KEY') or st.secrets.get('SUPABASE_ANON_KEY') or st.secrets.get('SUPABASE_KEY')
    if not url or not key:
        st.error('Supabase non configurato nei Secrets.'); st.stop()
    return create_client(str(url).rstrip('/'),str(key))


def require_access():
    if not st.session_state.get('user'):
        st.warning('Accedi prima dalla pagina principale di OrthoFlow.'); st.stop()
    if str(st.session_state.get('ruolo','')) not in {'Admin','Magazzino'}:
        st.error('Area riservata ad Admin e Magazzino.'); st.stop()


def clean(v): return str(v or '').strip().upper()

def shelves():
    try: return pd.DataFrame(sb().table('v_wms_scaffali').select('*').execute().data or [])
    except Exception as e: st.error(f'Errore scaffali: {e}'); return pd.DataFrame()

def shelf_label(r): return f"{r['codice_magazzino']} · Corsia {r['corsia']} · Scaffale {r['scaffale']}"

def locations_for(mag,corsia,scaffale):
    rows=(sb().table('ubicazioni_magazzino').select('*').eq('codice_magazzino',mag).eq('corsia',corsia).eq('scaffale',scaffale).eq('attiva',True).order('ripiano').order('posizione').execute().data or [])
    return pd.DataFrame(rows)

def stock_for(loc):
    if loc.empty: return pd.DataFrame()
    rows=sb().table('giacenze_ubicazioni').select('*').in_('ubicazione_id',loc['id'].tolist()).gt('quantita',0).execute().data or []
    s=pd.DataFrame(rows)
    if s.empty: return s
    return s.merge(loc[['id','ripiano','posizione','codice_ubicazione']],left_on='ubicazione_id',right_on='id',how='left',suffixes=('','_loc'))

def normalize(raw): return str(raw or '').strip().replace('\u001d','|')

def parse_gs1(raw):
    value=normalize(raw)
    result={'raw':value,'gtin':'','lotto':'','scadenza':None}
    compact=value.removeprefix(']d2').removeprefix(']C1')
    for ai,val in re.findall(r'\((01|10|17)\)([^()]+)',compact):
        val=val.strip('|')
        if ai=='01': result['gtin']=val[:14]
        elif ai=='10': result['lotto']=val
        elif ai=='17' and len(val)>=6:
            try: result['scadenza']=pd.to_datetime(val[:6],format='%y%m%d').date()
            except Exception: pass
    if not result['gtin']:
        m=re.search(r'01(\d{14})',compact)
        if m: result['gtin']=m.group(1)
    if result['scadenza'] is None:
        m=re.search(r'17(\d{6})',compact)
        if m:
            try: result['scadenza']=pd.to_datetime(m.group(1),format='%y%m%d').date()
            except Exception: pass
    m=re.search(r'(?:^|\|)10([^|]+)',compact)
    if m and not result['lotto']: result['lotto']=m.group(1)
    return result

def find_mapping(parsed):
    try:
        q=sb().table('codici_prodotto_scan').select('*')
        rows=(q.eq('gtin',parsed['gtin']).limit(1).execute().data if parsed['gtin'] else q.eq('codice_scansionato',parsed['raw']).limit(1).execute().data) or []
        return rows[0] if rows else None
    except Exception: return None

def audit(action,detail):
    try: sb().table('audit_log').insert({'utente':str(st.session_state.get('user','')),'ruolo':str(st.session_state.get('ruolo','')),'azione':action,'tabella':'WMS','dettaglio':detail}).execute()
    except Exception: pass

require_access()
st.title('📚 Gestione Scaffale')
st.caption('Seleziona lo scaffale, scansiona il prodotto Johnson e indica solo ripiano/postazione. Il QR dello scaffale resta unico.')

data=shelves()
if data.empty:
    st.info('Prima crea almeno uno scaffale/ubicazione nel WMS.'); st.stop()

idx=st.selectbox('Scaffale da gestire',range(len(data)),format_func=lambda i:shelf_label(data.iloc[i]))
r=data.iloc[idx]
mag,corsia,scaffale=clean(r['codice_magazzino']),clean(r['corsia']),clean(r['scaffale'])
loc=locations_for(mag,corsia,scaffale)

c1,c2,c3=st.columns(3)
c1.metric('Scaffale',scaffale); c2.metric('Ripiani',loc['ripiano'].nunique() if not loc.empty else 0); c3.metric('Postazioni',len(loc))

st.subheader('➕ Aggiungi prodotto tramite scanner Johnson')
raw=''
if qrcode_scanner is not None:
    raw=normalize(qrcode_scanner(key=f'shelf_product_{mag}_{corsia}_{scaffale}'))
manual=st.text_input('Oppure inserisci/incolla il codice letto',key='manual_product')
raw=raw or normalize(manual)

parsed=parse_gs1(raw) if raw else {'raw':'','gtin':'','lotto':'','scadenza':None}
mapped=find_mapping(parsed) if raw else None
if raw:
    a,b,c=st.columns(3)
    a.metric('GTIN',parsed['gtin'] or 'Non letto'); b.metric('Lotto',parsed['lotto'] or 'Da confermare'); c.metric('Scadenza',str(parsed['scadenza'] or 'Da confermare'))

with st.form('add_to_shelf'):
    codice=st.text_input('Codice articolo Johnson',value=(mapped or {}).get('codice_articolo',''))
    lotto=st.text_input('Lotto',value=parsed.get('lotto',''))
    scadenza=st.date_input('Scadenza',value=parsed.get('scadenza') or date.today())
    qty=st.number_input('Quantità',min_value=0.01,value=1.0,step=1.0)
    ripiani=sorted(loc['ripiano'].dropna().astype(str).unique().tolist()) if not loc.empty else []
    ripiano=st.selectbox('Ripiano',ripiani) if ripiani else st.text_input('Ripiano')
    subset=loc[loc['ripiano'].astype(str)==str(ripiano)] if not loc.empty and ripiani else pd.DataFrame()
    positions=sorted(subset['posizione'].dropna().astype(str).unique().tolist()) if not subset.empty else []
    posizione=st.selectbox('Postazione',positions) if positions else st.text_input('Postazione')
    sterile=st.checkbox('Sterile',True)
    save=st.form_submit_button('Salva nello scaffale',use_container_width=True)

if save:
    if not clean(codice) or not clean(lotto): st.error('Codice articolo e lotto sono obbligatori.')
    else:
        target=loc[(loc['ripiano'].astype(str)==str(ripiano)) & (loc['posizione'].astype(str)==str(posizione))]
        if target.empty: st.error('Ripiano/postazione non configurati per questo scaffale. Creali prima nel WMS → Ubicazioni.')
        else:
            t=target.iloc[0]
            try:
                sb().table('giacenze_ubicazioni').upsert({'ubicazione_id':int(t['id']),'codice_magazzino':mag,'codice':clean(codice),'lotto':clean(lotto),'scadenza':scadenza.isoformat(),'origine':'SCANNER_SCAFFALE','quantita':float(qty),'quantita_impegnata':0,'sterile':bool(sterile)},on_conflict='ubicazione_id,codice,lotto,origine,sterile').execute()
                if raw:
                    sb().table('codici_prodotto_scan').upsert({'codice_scansionato':parsed['raw'],'gtin':parsed['gtin'] or None,'codice_articolo':clean(codice),'descrizione':(mapped or {}).get('descrizione',''),'attivo':True},on_conflict='codice_scansionato').execute()
                audit('AGGIUNGI_PRODOTTO_SCAFFALE',f'{mag}/{corsia}/{scaffale}/{ripiano}/{posizione}; {clean(codice)}; lotto {clean(lotto)}; qta {qty}')
                st.success(f'Prodotto salvato: Scaffale {scaffale} → Ripiano {ripiano} → Postazione {posizione}.')
                st.rerun()
            except Exception as e: st.error(f'Salvataggio non eseguito: {e}')

st.divider(); st.subheader('📦 Contenuto attuale dello scaffale')
stock=stock_for(loc)
if stock.empty: st.info('Lo scaffale non contiene ancora prodotti registrati.')
else:
    cols=[c for c in ['codice','lotto','scadenza','quantita','ripiano','posizione','codice_ubicazione'] if c in stock.columns]
    st.dataframe(stock[cols].sort_values([c for c in ['ripiano','posizione','codice'] if c in cols]),use_container_width=True,hide_index=True)
