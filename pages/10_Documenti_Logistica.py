import streamlit as st
import pandas as pd
from supabase import create_client
st.set_page_config(page_title="Documenti Logistica · OrthoFlow",page_icon="📑",layout="wide")
if not st.session_state.get("user"): st.switch_page("pages/99_Login.py")
def sb(): return create_client(st.secrets["SUPABASE_URL"],st.secrets["SUPABASE_KEY"])
st.title("📑 Documenti Logistica")
st.caption("Archivio certificazioni di lavaggio/decontaminazione e documenti collegati alle missioni.")
d=pd.DataFrame(sb().table("documenti_missioni").select("*").order("created_at",desc=True).limit(500).execute().data or [])
if d.empty: st.info("Nessun documento archiviato.")
else:
    m=pd.DataFrame(sb().table("missioni_corrieri").select("id,codice,data_missione,kit_codice,struttura_id").execute().data or [])
    if not m.empty: d=d.merge(m,left_on="missione_id",right_on="id",how="left",suffixes=("","_missione"))
    q=st.text_input("🔎 Cerca per missione, kit, firmatario o tipo documento")
    if q: d=d[d.astype(str).apply(lambda x:x.str.contains(q,case=False,na=False)).any(axis=1)]
    st.dataframe(d,use_container_width=True,hide_index=True)
