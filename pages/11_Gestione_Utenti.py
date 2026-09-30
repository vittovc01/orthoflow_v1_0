import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from supabase import create_client

st.set_page_config(page_title="Utenti & Permessi · OrthoFlow",page_icon="👥",layout="wide")
if not st.session_state.get("user"): st.stop()
perms=set(st.session_state.get("permessi",[]) or [])
if str(st.session_state.get("ruolo",""))!="Admin" and "DIREZIONE" not in perms:
    st.error("Area riservata alla Direzione."); st.stop()

def sb():
    url=st.secrets.get("SUPABASE_URL")
    key=st.secrets.get("SUPABASE_SERVICE_KEY") or st.secrets.get("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_KEY")
    return create_client(str(url).rstrip("/"),str(key))

LABELS={
 "DIREZIONE":"Direzione · accesso completo",
 "OPERATIVITA":"Gestionale operativo",
 "AMMINISTRAZIONE":"Amministrazione",
 "LOGISTICA":"Logistica & Magazzino",
 "AGENTE":"Agente",
 "CORRIERE":"Corriere"
}
st.title("👥 Utenti & Permessi")
st.caption("Approva gli accessi e assegna una o più funzioni. Ogni utente visualizza soltanto le aree autorizzate.")

rows=sb().table("utenti_app").select("id,username,nome_completo,ruolo,permessi,stato_accesso,attivo,ultimo_accesso,created_at").order("created_at",desc=True).execute().data or []
df=pd.DataFrame(rows)
if df.empty: st.info("Nessun utente."); st.stop()
pending=df[df["stato_accesso"].fillna("APPROVATO")=="IN_ATTESA"]
a,b,c=st.columns(3); a.metric("Utenti",len(df)); b.metric("In attesa",len(pending)); c.metric("Attivi",int(df["attivo"].fillna(False).sum()))
if len(pending): st.warning(f"Ci sono {len(pending)} richieste da approvare.")

idx=st.selectbox("Seleziona utente",df.index,format_func=lambda i:f'{df.loc[i].get("nome_completo") or df.loc[i,"username"]} · {df.loc[i,"stato_accesso"]}')
r=df.loc[idx]
st.subheader(r.get("nome_completo") or r["username"])
st.caption(f'Username: {r["username"]} · Ultimo accesso: {r.get("ultimo_accesso") or "mai"}')
current=list(r.get("permessi") or [])
selected=st.multiselect("Funzioni autorizzate",list(LABELS),default=[x for x in current if x in LABELS],format_func=lambda x:LABELS[x])
col1,col2,col3=st.columns(3)
if col1.button("✅ Approva / Salva",type="primary",use_container_width=True):
    if not selected: st.error("Assegna almeno una funzione.")
    else:
        ruolo="Admin" if "DIREZIONE" in selected else ("Amministrazione" if "AMMINISTRAZIONE" in selected else ("Magazzino" if "LOGISTICA" in selected else ("Agente" if "AGENTE" in selected else ("Corriere" if "CORRIERE" in selected else "Operatore"))))
        try:
            sb().table("utenti_app").update({"permessi":selected,"ruolo":ruolo,"stato_accesso":"APPROVATO","attivo":True,"approvato_da":str(st.session_state.get("user","")),"approvato_at":datetime.now(timezone.utc).isoformat()}).eq("id",int(r["id"])).execute()
            st.success("Utente approvato e permessi aggiornati."); st.rerun()
        except Exception as exc:
            st.error("Impossibile salvare i permessi. Controlla configurazione e vincoli dell'utente.")
            st.caption(str(exc))
if col2.button("⛔ Sospendi",use_container_width=True):
    if str(r["username"])==str(st.session_state.get("user")): st.error("Non puoi sospendere il tuo stesso account.")
    else:
        sb().table("utenti_app").update({"attivo":False}).eq("id",int(r["id"])).execute(); st.success("Account sospeso."); st.rerun()
if col3.button("❌ Rifiuta richiesta",use_container_width=True):
    if str(r["username"])==str(st.session_state.get("user")): st.error("Operazione non consentita sul tuo account.")
    else:
        sb().table("utenti_app").update({"stato_accesso":"RIFIUTATO","attivo":False,"permessi":[]}).eq("id",int(r["id"])).execute(); st.rerun()

st.divider()
st.subheader("🚐 Gestione dati corrieri")
try:
    cor=pd.DataFrame(sb().table("corrieri").select("*").order("nome").execute().data or [])
except Exception:
    cor=pd.DataFrame()
if cor.empty:
    st.info("Nessun corriere registrato.")
else:
    ci=st.selectbox("Seleziona corriere da modificare",cor.index,format_func=lambda i:str(cor.loc[i].get("nome","")),key="manage_courier")
    cr=cor.loc[ci]
    with st.form("edit_courier"):
        cn=st.text_input("Nome corriere",value=str(cr.get("nome") or ""))
        ct=st.text_input("Telefono corriere",value=str(cr.get("telefono") or ""))
        cuid=st.selectbox("Collega a utente",[""]+df["id"].astype(str).tolist(),index=([""]+df["id"].astype(str).tolist()).index(str(cr.get("user_id"))) if str(cr.get("user_id")) in df["id"].astype(str).tolist() else 0,format_func=lambda x:"— Nessun utente —" if not x else str(df.loc[df["id"].astype(str)==x,"username"].iloc[0]))
        active=st.checkbox("Corriere attivo",value=bool(cr.get("attivo",True)))
        if st.form_submit_button("💾 Salva corriere",type="primary"):
            sb().table("corrieri").update({"nome":cn.strip(),"telefono":ct.strip(),"user_id":int(cuid) if cuid else None,"attivo":active}).eq("id",int(cr["id"])).execute(); st.success("Corriere aggiornato."); st.rerun()
    if st.button("🗑️ Elimina corriere",key="delete_courier"):
        used=sb().table("missioni_corrieri").select("id").eq("corriere_id",int(cr["id"])).limit(1).execute().data or []
        if used: st.error("Il corriere ha missioni registrate: per mantenere lo storico disattivalo invece di eliminarlo.")
        else: sb().table("corrieri").delete().eq("id",int(cr["id"])).execute(); st.rerun()

st.divider()
show=df.copy()
show["permessi"]=show["permessi"].apply(lambda x:", ".join(x or []))
st.dataframe(show[["nome_completo","username","stato_accesso","attivo","permessi","ultimo_accesso"]],use_container_width=True,hide_index=True)
