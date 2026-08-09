import io
import zipfile
import pandas as pd
import qrcode
import streamlit as st
from supabase import create_client

st.set_page_config(page_title='QR Scaffali · OrthoFlow', page_icon='🏷️', layout='wide')


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

def shelf_key(mag,corsia,scaffale): return f'{clean(mag)}|{clean(corsia)}|{clean(scaffale)}'

def shelf_payload(mag,corsia,scaffale): return f'OFWMS:SHELF:{shelf_key(mag,corsia,scaffale)}'

def qr_png(payload,box_size=10):
    qr=qrcode.QRCode(version=None,box_size=box_size,border=4)
    qr.add_data(payload); qr.make(fit=True)
    image=qr.make_image(fill_color='black',back_color='white')
    b=io.BytesIO(); image.save(b,format='PNG'); return b.getvalue()

def shelves():
    try: return pd.DataFrame(sb().table('v_wms_scaffali').select('*').execute().data or [])
    except Exception as e: st.error(f'Errore scaffali: {e}'); return pd.DataFrame()

def locations_for(mag,corsia,scaffale):
    try:
        rows=(sb().table('ubicazioni_magazzino').select('*').eq('codice_magazzino',mag).eq('corsia',corsia).eq('scaffale',scaffale).eq('attiva',True).execute().data or [])
        return pd.DataFrame(rows)
    except Exception as e: st.error(f'Errore ubicazioni: {e}'); return pd.DataFrame()

def stock_for(mag,corsia,scaffale):
    loc=locations_for(mag,corsia,scaffale)
    if loc.empty: return pd.DataFrame()
    ids=loc['id'].tolist()
    try:
        rows=sb().table('giacenze_ubicazioni').select('*').in_('ubicazione_id',ids).gt('quantita',0).execute().data or []
        stock=pd.DataFrame(rows)
        if stock.empty: return stock
        cols=['id','codice_ubicazione','ripiano','posizione']
        return stock.merge(loc[cols],left_on='ubicazione_id',right_on='id',how='left',suffixes=('','_loc'))
    except Exception as e: st.error(f'Errore contenuto scaffale: {e}'); return pd.DataFrame()

def label(row): return f"{row['codice_magazzino']} · Corsia {row['corsia']} · Scaffale {row['scaffale']}"

def zip_qr(data):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for _,r in data.iterrows():
            payload=shelf_payload(r['codice_magazzino'],r['corsia'],r['scaffale'])
            name=f"QR_SCAFFALE_{clean(r['codice_magazzino'])}_{clean(r['corsia'])}_{clean(r['scaffale'])}.png"
            z.writestr(name,qr_png(payload))
    return out.getvalue()

require_access()
st.title('🏷️ QR Scaffali')
st.caption('Un solo QR identifica l’intero scaffale. Ripiani e postazioni restano nel database per indicare dove recuperare ogni prodotto.')

data=shelves()
if data.empty:
    st.info('Nessuno scaffale disponibile. Prima crea almeno una ubicazione nel WMS indicando corsia e scaffale.')
    st.stop()

st.download_button('⬇️ Scarica QR di tutti gli scaffali',zip_qr(data),'orthoflow_qr_scaffali.zip','application/zip',use_container_width=True)

selected=st.selectbox('Scaffale',range(len(data)),format_func=lambda i: label(data.iloc[i]))
r=data.iloc[selected]
mag,corsia,scaffale=clean(r['codice_magazzino']),clean(r['corsia']),clean(r['scaffale'])
payload=shelf_payload(mag,corsia,scaffale)
png=qr_png(payload)

c1,c2=st.columns([1,2])
with c1:
    st.image(png,width=260)
    st.download_button('Scarica QR scaffale',png,f'QR_SCAFFALE_{mag}_{corsia}_{scaffale}.png','image/png',use_container_width=True)
with c2:
    st.subheader(f'{mag} · Corsia {corsia} · Scaffale {scaffale}')
    st.metric('Ubicazioni/postazioni',int(r.get('numero_ubicazioni',0)))
    st.metric('Ripiani',int(r.get('numero_ripiani',0)))
    st.metric('Quantità ubicata',float(r.get('quantita_totale',0) or 0))
    st.code(payload)

st.divider()
st.subheader('Contenuto dello scaffale')
stock=stock_for(mag,corsia,scaffale)
if stock.empty:
    st.warning('Scaffale creato correttamente, ma non contiene ancora prodotti ubicati. Il QR funziona: devi prima assegnare le giacenze alle postazioni/ripiani dal WMS → Posizionamento.')
else:
    show=[c for c in ['codice','lotto','scadenza','quantita','ripiano','posizione','codice_ubicazione','origine'] if c in stock.columns]
    st.dataframe(stock[show].sort_values([c for c in ['ripiano','posizione','codice'] if c in show]),use_container_width=True,hide_index=True)

st.info('Per il tuo utilizzo consiglio: 1 QR grande per ogni scaffale. QR aggiuntivi sui ripiani solo dove servono per inventario/picking molto preciso. Non è necessario un QR per ogni confezione Johnson: usiamo il DataMatrix già presente.')