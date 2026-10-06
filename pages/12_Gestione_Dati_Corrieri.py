import pandas as pd
import streamlit as st
from orthoflow_branding import configure_page
from supabase import create_client
configure_page(page_title="Gestione Dati Corrieri · P.M. Medical",page_icon="🗂️",layout="wide")
if not st.session_state.get("user"): st.switch_page("pages/99_Login.py")
p=set(st.session_state.get("permessi",[]) or [])
if str(st.session_state.get("ruolo",""))!="Admin" and "DIREZIONE" not in p: st.error("Area riservata alla Direzione."); st.stop()
@st.cache_resource
def sb():
    return create_client(str(st.secrets.get("SUPABASE_URL")).rstrip("/"),str(st.secrets.get("SUPABASE_SERVICE_KEY") or st.secrets.get("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_KEY")))
st.title("🗂️ Gestione Dati Corrieri")
st.caption("Qui puoi modificare o eliminare anche le singole timbrature GPS.")
tables={"Timbrature GPS":"timbrature_corrieri","Missioni":"missioni_corrieri","Foto missioni":"foto_missioni","Documenti e firme":"documenti_missioni","Kit logistici":"kit_logistici","Movimenti kit":"movimenti_kit_corrieri","Corrieri":"corrieri","Strutture":"strutture_logistiche"}
label=st.selectbox("Sezione",list(tables)); table=tables[label]
d=pd.DataFrame(sb().table(table).select("*").order("id",desc=True).limit(3000).execute().data or [])
if d.empty: st.info("Nessun record."); st.stop()
q=st.text_input("🔎 Cerca")
if q: d=d[d.astype(str).apply(lambda x:x.str.contains(q,case=False,na=False)).any(axis=1)]
st.dataframe(d,use_container_width=True,hide_index=True)
if d.empty: st.stop()
rid=st.selectbox("ID da gestire",d["id"].tolist()); rec=d[d["id"]==rid].iloc[0]
editable=[x for x in d.columns if x not in ("id","created_at","updated_at")]; changes={}
with st.expander("✏️ Modifica ID selezionato"):
    cols=st.columns(2)
    for n,col in enumerate(editable):
        v=rec.get(col)
        if col in ("attivo","attiva"): changes[col]=cols[n%2].checkbox(col,value=bool(v),key=f"{table}_{rid}_{col}")
        elif col in ("colli","corriere_id","struttura_id","missione_id","kit_id","user_id"):
            z=cols[n%2].text_input(col,value="" if pd.isna(v) else str(int(v)),key=f"{table}_{rid}_{col}"); changes[col]=int(z) if z.strip() else None
        else: changes[col]=cols[n%2].text_input(col,value="" if pd.isna(v) else str(v),key=f"{table}_{rid}_{col}")
    if st.button("💾 Salva modifiche",type="primary"):
        try: sb().table(table).update(changes).eq("id",int(rid)).execute(); st.rerun()
        except Exception as e: st.error(str(e))
st.divider(); confirm=st.checkbox(f"Confermo eliminazione definitiva ID {rid}")
if st.button("🗑️ Elimina ID",disabled=not confirm):
    try:
        if table=="missioni_corrieri": sb().rpc("elimina_missione_corriere_completa",{"p_missione_id":int(rid)}).execute()
        elif table in ("foto_missioni","documenti_missioni"):
            assets=[rec.get("storage_path"),rec.get("firma_storage_path")]; assets=[x for x in assets if x and not pd.isna(x)]
            if assets: sb().storage.from_("orthoflow-impianti").remove(assets)
            sb().table(table).delete().eq("id",int(rid)).execute()
        elif table=="kit_logistici":
            sb().table("movimenti_kit_corrieri").delete().eq("kit_id",int(rid)).execute(); sb().table(table).delete().eq("id",int(rid)).execute()
        else: sb().table(table).delete().eq("id",int(rid)).execute()
        st.success("Record eliminato."); st.rerun()
    except Exception as e: st.error(str(e))
