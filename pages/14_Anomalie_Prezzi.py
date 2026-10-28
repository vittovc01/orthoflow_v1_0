import os
from datetime import datetime, timezone
import pandas as pd
import streamlit as st
from orthoflow_branding import configure_page
from supabase import create_client

configure_page(page_title="Anomalie Prezzi e Giacenze · P.M. Medical", page_icon="⚠️", layout="wide")
perms=set(st.session_state.get("permessi",[]) or [])
role=str(st.session_state.get("ruolo","")).strip().lower()
allowed=role in ["admin","amministrazione"] or "DIREZIONE" in perms or "AMMINISTRAZIONE" in perms
if not st.session_state.get("user") or not allowed:
    st.error("Accesso non autorizzato."); st.stop()

@st.cache_resource
def sb():
    url=st.secrets.get("SUPABASE_URL",os.getenv("SUPABASE_URL",""))
    key=st.secrets.get("SUPABASE_SERVICE_KEY") or st.secrets.get("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        st.error("Configurazione Supabase non disponibile.")
        st.stop()
    return create_client(str(url).rstrip("/"),str(key))

from anomaly_reads import read_rows


def load_rows(query):
    try:
        return read_rows(sb, query, sb.clear)
    except Exception:
        st.error("Connessione ai dati non disponibile. Premi Riprova per ricaricare le anomalie.")
        if st.button('Riprova caricamento anomalie', key='retry_anomaly_reads'):
            sb.clear()
            st.rerun()
        st.stop()


from stock_anomalies import split_stock_anomalies

st.title("⚠️ Anomalie Prezzi e Giacenze")
st.caption("Prezzi mancanti e disponibilità di magazzino da verificare. Le due sezioni sono indipendenti.")

rows=load_rows(lambda client: client.table("righe_intervento").select("id,intervento_id,codice,descrizione,lotto,quantita,prezzo,prezzo_source").eq("prezzo_source","DA_VERIFICARE_DIREZIONE").order("id",desc=True))
if not rows:
    notice=st.session_state.pop('price_anomalies_saved',None)
    if notice: st.success(notice)
    st.success("Nessuna anomalia prezzo da verificare.")

else:
    df=pd.DataFrame(rows)
    ids=df["intervento_id"].dropna().astype(int).unique().tolist()
    ints=load_rows(lambda client: client.table("interventi").select("id,data_intervento,cliente,struttura,cartella_clinica,linea,agente").in_("id",ids))
    if ints:
        di=pd.DataFrame(ints).rename(columns={"id":"intervento_id"})
        df=df.merge(di,on="intervento_id",how="left")
    show=[c for c in ["id","data_intervento","cliente","struttura","cartella_clinica","linea","agente","codice","descrizione","lotto","quantita","prezzo_source"] if c in df]
    st.metric("Da verificare",len(df))
    st.dataframe(df[show],use_container_width=True,hide_index=True)

    rid=st.selectbox("Riga da regolarizzare",df["id"].astype(int).tolist(),format_func=lambda x:(lambda r:f"#{x} · {r.get('codice','')} · lotto {r.get('lotto','')} · CC {r.get('cartella_clinica','')}")(df[df["id"]==x].iloc[0]))
    r=df[df["id"]==rid].iloc[0]
    st.write(f"**{r.get('codice','')}** — {r.get('descrizione','')}")
    st.caption(f"Clinica: {r.get('cliente','')} · Linea: {r.get('linea','')}")
    mode=st.radio("Tipo regolarizzazione",["Prezzo corretto","Sconto merce €0"],horizontal=True,key=f"anomaly_mode_{rid}")
    price=0.0
    if mode=="Prezzo corretto":
        price=st.number_input("Prezzo unitario €",min_value=0.01,step=0.01,format="%.2f",key=f"anomaly_price_{rid}")
    st.info("Il prezzo sarà applicato a tutte le anomalie prezzo aperte con lo stesso codice, clinica e linea, anche con lotti diversi. Ogni totale viene ricalcolato con la quantità della propria riga.")
    notice=st.session_state.pop('price_anomalies_saved',None)
    if notice: st.success(notice)
    if st.button("✅ Salva e regolarizza tutte le anomalie corrispondenti",type="primary",use_container_width=True):
        try:
            result=sb().rpc('regolarizza_anomalie_prezzo', {
                'p_riga_id':int(rid),'p_prezzo':float(price),'p_sconto':mode=="Sconto merce €0",
                'p_utente':str(st.session_state.get('user','')),
            }).execute().data
            count=int((result or {}).get('righe_regolarizzate',0))
        except Exception:
            st.error("Regolarizzazione non completata. Aggiorna la pagina e verifica che clinica, linea e codice siano presenti. Nessuna modifica parziale è stata salvata.")
        else:
            st.session_state['price_anomalies_saved']=f"Regolarizzate {count} anomalie prezzo per lo stesso codice, clinica e linea."
            st.rerun()

st.divider()
st.subheader("📦 Anomalie Giacenza")
stock=load_rows(lambda client: client.table("anomalie_giacenza").select("*").eq("stato","DA_VERIFICARE").order("id",desc=True))
stock_ids = sorted({int(a["intervento_id"]) for a in stock if a.get("intervento_id") is not None})
headers = (load_rows(lambda client: client.table("interventi").select("id,codice_cliente,cliente,cartella_clinica").in_("id",stock_ids))) if stock_ids else []
materials = (load_rows(lambda client: client.table("righe_intervento").select("intervento_id,codice,lotto,origine").in_("intervento_id",stock_ids))) if stock_ids else []
stock, unlinked_stock, structure_stock = split_stock_anomalies(stock, headers, materials)
if unlinked_stock:
    with st.expander(f"Segnalazioni senza intervento collegato: {len(unlinked_stock)}"):
        st.caption("Segnalazioni storiche rimaste scollegate. Non sono anomalie operative degli interventi attuali; non vengono chiuse o associate automaticamente.")
        st.dataframe(pd.DataFrame(unlinked_stock), use_container_width=True, hide_index=True)
if structure_stock:
    with st.expander(f"Segnalazioni superate: conto deposito struttura ({len(structure_stock)})"):
        st.caption("Le righe collegate sono confermate conto deposito struttura: non richiedono giacenza nostra.")
        st.dataframe(pd.DataFrame(structure_stock), use_container_width=True, hide_index=True)
if not stock:
    st.success("Nessuna anomalia giacenza operativa da verificare.")
else:
    sdf=pd.DataFrame(stock)
    st.dataframe(sdf[[x for x in ["id","created_at","cliente","cartella_clinica","codice","lotto","quantita_richiesta","quantita_disponibile","magazzino","intervento_id","motivo"] if x in sdf]],use_container_width=True,hide_index=True)
    sid=st.selectbox("Anomalia giacenza da chiudere",sdf["id"].astype(int).tolist(),key="stock_anomaly")
    reason=st.selectbox("Esito",["Già scaricato in Business prima dell'importazione","Rettifica giacenza","Lotto da correggere","Altro"])
    note=st.text_input("Nota Direzione",key="stock_note")
    if st.button("✅ Chiudi anomalia giacenza",type="primary"):
        sb().table("anomalie_giacenza").update({"stato":"RISOLTA","motivo":reason + ((" · "+note) if note else ""),"risolto_da":str(st.session_state.get("user","")),"risolto_at":datetime.now(timezone.utc).isoformat()}).eq("id",int(sid)).execute()
        st.success("Anomalia giacenza chiusa."); st.rerun()

