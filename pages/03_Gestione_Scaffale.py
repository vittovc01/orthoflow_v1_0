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

# OrthoFlow RBAC: blocca anche l'accesso diretto via URL.
if not st.session_state.get("user"):
    st.error("Sessione non autenticata."); st.stop()
_of_perms=set(st.session_state.get("permessi",[]) or [])
_of_director=str(st.session_state.get("ruolo",""))=="Admin" or "DIREZIONE" in _of_perms
_of_required=set(["LOGISTICA"])
if not _of_director and not (_of_perms & _of_required):
    st.error("Non sei autorizzato ad accedere a questa area."); st.stop()


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

def shelf_label(r):
    nome=str(r.get('nome_scaffale') or '').strip()
    extra=f" · {nome}" if nome else ''
    return f"{r['codice_magazzino']} · Corsia {r['corsia']} · Scaffale {r['scaffale']}{extra}"

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

with st.expander('⚙️ Gestisci scaffali', expanded=data.empty):
    st.caption('Crea nuovi scaffali, assegna un nome leggibile, aggiungi ripiani/postazioni o modifica quelli esistenti.')
    mags=pd.DataFrame(sb().table('magazzini').select('*').eq('stato_record','Attivo').execute().data or [])
    mag_opts=mags['codice_magazzino'].astype(str).tolist() if not mags.empty else ['MAG1']
    tab_new,tab_edit=st.tabs(['➕ Nuovo scaffale / ubicazione','✏️ Modifica scaffale'])
    with tab_new:
        with st.form('new_shelf_location'):
            nm=st.selectbox('Magazzino',mag_opts)
            nc=st.text_input('Corsia',value='A')
            ns=st.text_input('Codice scaffale',placeholder='Es. 02')
            nn=st.text_input('Nome scaffale',placeholder='Es. Trauma Tibia')
            nr=st.text_input('Ripiano',value='A')
            np=st.text_input('Postazione',value='01')
            create=st.form_submit_button('Crea / aggiungi ubicazione',use_container_width=True)
        if create:
            vals=[clean(x) for x in [nm,nc,ns,nr,np]]
            if not all(vals): st.error('Magazzino, corsia, scaffale, ripiano e postazione sono obbligatori.')
            else:
                cm,cc,cs,cr,cp=vals; cu=f'{cm}-{cc}-{cs}-{cr}-{cp}'
                exists=sb().table('ubicazioni_magazzino').select('id').eq('codice_ubicazione',cu).limit(1).execute().data or []
                if exists: st.error('Questa ubicazione esiste già.')
                else:
                    magrow=mags[mags['codice_magazzino'].astype(str)==str(nm)]
                    mid=int(magrow.iloc[0]['id']) if not magrow.empty else None
                    sb().table('ubicazioni_magazzino').insert({'magazzino_id':mid,'codice_magazzino':cm,'codice_ubicazione':cu,'corsia':cc,'scaffale':cs,'nome_scaffale':str(nn).strip() or f'Scaffale {cs}','ripiano':cr,'posizione':cp,'descrizione':'','attiva':True}).execute()
                    audit('CREA_UBICAZIONE_SCAFFALE',cu)
                    st.success(f'Creata ubicazione {cu}.'); st.rerun()
    with tab_edit:
        if data.empty: st.info('Non ci sono ancora scaffali da modificare.')
        else:
            ei=st.selectbox('Scaffale',range(len(data)),format_func=lambda i:shelf_label(data.iloc[i]),key='edit_shelf')
            er=data.iloc[ei]; em,ec,es=clean(er['codice_magazzino']),clean(er['corsia']),clean(er['scaffale'])
            eloc=locations_for(em,ec,es)
            with st.form('edit_shelf_form'):
                new_name=st.text_input('Nome scaffale',value=str(er.get('nome_scaffale') or f'Scaffale {es}'))
                add_r=st.text_input('Nuovo ripiano (opzionale)',placeholder='Es. B')
                add_p=st.text_input('Nuova postazione (opzionale)',placeholder='Es. 01')
                save_master=st.form_submit_button('Salva modifiche / aggiungi postazione',use_container_width=True)
            if save_master:
                sb().table('ubicazioni_magazzino').update({'nome_scaffale':new_name.strip() or f'Scaffale {es}'}).eq('codice_magazzino',em).eq('corsia',ec).eq('scaffale',es).execute()
                if clean(add_r) and clean(add_p):
                    cr,cp=clean(add_r),clean(add_p); cu=f'{em}-{ec}-{es}-{cr}-{cp}'
                    exists=sb().table('ubicazioni_magazzino').select('id').eq('codice_ubicazione',cu).limit(1).execute().data or []
                    if not exists:
                        mid=int(eloc.iloc[0]['magazzino_id']) if not eloc.empty and pd.notna(eloc.iloc[0].get('magazzino_id')) else None
                        sb().table('ubicazioni_magazzino').insert({'magazzino_id':mid,'codice_magazzino':em,'codice_ubicazione':cu,'corsia':ec,'scaffale':es,'nome_scaffale':new_name.strip() or f'Scaffale {es}','ripiano':cr,'posizione':cp,'descrizione':'','attiva':True}).execute()
                audit('MODIFICA_SCAFFALE',f'{em}/{ec}/{es}; nome={new_name}')
                st.success('Scaffale aggiornato.'); st.rerun()

data=shelves()
if data.empty:
    st.info('Crea il primo scaffale dalla sezione Gestisci scaffali qui sopra.'); st.stop()

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
