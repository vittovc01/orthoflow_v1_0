import streamlit as st
from orthoflow_branding import configure_page
import pandas as pd
from supabase import create_client
configure_page(page_title="Documenti Logistica · P.M. Medical",page_icon="📑",layout="wide")

if not st.session_state.get("user"): st.stop()
_ofp=set(st.session_state.get("permessi",[]) or [])
_ofd=str(st.session_state.get("ruolo",""))=="Admin" or "DIREZIONE" in _ofp
if not _ofd and not (_ofp & set(["LOGISTICA"])):
    st.error("Non sei autorizzato ad accedere a questa area."); st.stop()
if not st.session_state.get("user"): st.switch_page("pages/99_Login.py")
perms=set(st.session_state.get("permessi",[]) or [])
if str(st.session_state.get("ruolo",""))!="Admin" and "DIREZIONE" not in perms and "LOGISTICA" not in perms: st.error("Accesso non autorizzato."); st.stop()
@st.cache_resource
def sb():
    url=st.secrets.get("SUPABASE_URL")
    key=st.secrets.get("SUPABASE_SERVICE_KEY") or st.secrets.get("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_KEY")
    if not url or not key:
        st.error("Supabase non configurato nei Secrets."); st.stop()
    return create_client(str(url).rstrip("/"),str(key))
st.title("📑 Documenti Logistica")
st.caption("Archivio certificazioni di lavaggio/decontaminazione e documenti collegati alle missioni.")
d=pd.DataFrame(sb().table("documenti_missioni").select("*").order("created_at",desc=True).limit(500).execute().data or [])
if d.empty: st.info("Nessun documento archiviato.")
else:
    m=pd.DataFrame(sb().table("missioni_corrieri").select("id,codice,data_missione,kit_codice,struttura_id,corriere_id,tipo,esito_firma_ritiro,nota_firma_ritiro").execute().data or [])
    s=pd.DataFrame(sb().table("strutture_logistiche").select("id,nome").execute().data or [])
    c=pd.DataFrame(sb().table("corrieri").select("id,nome").execute().data or [])
    if not m.empty: d=d.merge(m,left_on="missione_id",right_on="id",how="left",suffixes=("","_missione"))
    if not s.empty and "struttura_id" in d: d["struttura"]=d["struttura_id"].map(dict(zip(s.id,s.nome)))
    if not c.empty and "corriere_id" in d: d["corriere"]=d["corriere_id"].map(dict(zip(c.id,c.nome)))
    q=st.text_input("🔎 Cerca per missione, kit, struttura, corriere, firmatario o tipo documento")
    if q: d=d[d.astype(str).apply(lambda x:x.str.contains(q,case=False,na=False)).any(axis=1)]
    st.dataframe(d[[x for x in ["created_at","codice","data_missione","tipo","kit_codice","struttura","corriere","tipo_documento","nome_firmatario","ruolo_firmatario","firmato_at"] if x in d]],use_container_width=True,hide_index=True)
    st.subheader("🔎 Anteprima documento")
    di=st.selectbox("Seleziona documento",d.index,format_func=lambda i:f'{d.loc[i].get("codice","")} · {d.loc[i].get("tipo_documento","")}')
    dr=d.loc[di]
    st.write(f'**Missione:** {dr.get("codice","-")} · **Struttura:** {dr.get("struttura","-")} · **Corriere:** {dr.get("corriere","-")}')
    st.write(f'**Firmatario:** {dr.get("nome_firmatario") or "-"} · **Ruolo:** {dr.get("ruolo_firmatario") or "-"} · **Firmato:** {dr.get("firmato_at") or "-"}')
    if dr.get("storage_path"):
        try:
            url=sb().storage.from_("orthoflow-impianti").create_signed_url(str(dr["storage_path"]),3600).get("signedURL")
            if url: st.link_button("📄 Apri documento",url)
        except Exception: pass
    if dr.get("firma_storage_path"):
        try:
            surl=sb().storage.from_("orthoflow-impianti").create_signed_url(str(dr["firma_storage_path"]),3600).get("signedURL")
            if surl: st.image(surl,caption="Firma del referente",width=500)
        except Exception: pass
    st.divider()
    st.subheader("⚠️ Ritiri senza firma")
    nf=m[(m["tipo"]=="RITIRO") & (m["esito_firma_ritiro"]=="SENZA_FIRMA")] if not m.empty else pd.DataFrame()
    if nf.empty: st.success("Nessun ritiro registrato senza firma.")
    else:
        if not s.empty: nf["struttura"]=nf["struttura_id"].map(dict(zip(s.id,s.nome)))
        if not c.empty: nf["corriere"]=nf["corriere_id"].map(dict(zip(c.id,c.nome)))
        st.dataframe(nf[[x for x in ["data_missione","codice","kit_codice","struttura","corriere","nota_firma_ritiro"] if x in nf]],use_container_width=True,hide_index=True)
