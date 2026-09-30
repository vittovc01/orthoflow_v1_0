import io
import pandas as pd
import streamlit as st
from supabase import create_client
st.set_page_config(page_title="Controllo Ordini J&J · OrthoFlow",page_icon="🔎",layout="wide")
if not st.session_state.get("user"): st.switch_page("pages/99_Login.py")
p=set(st.session_state.get("permessi",[]) or []); director=str(st.session_state.get("ruolo",""))=="Admin" or "DIREZIONE" in p
if not director and "AMMINISTRAZIONE" not in p: st.error("Accesso non autorizzato."); st.stop()
@st.cache_resource
def sb():
 return create_client(str(st.secrets.get("SUPABASE_URL")).rstrip("/"),str(st.secrets.get("SUPABASE_SERVICE_KEY") or st.secrets.get("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_KEY")))
def get(t): return pd.DataFrame(sb().table(t).select("*").execute().data or [])
st.title("🔎 Controllo Ordini J&J")
st.caption("Riconcilia consumi/interventi OrthoFlow con ordini e chiusure trasmesse da Johnson & Johnson.")
up=st.file_uploader("⬆️ Importa file Johnson (Excel/CSV)",type=["xlsx","xls","csv"])
if up and st.button("Importa dati Johnson",type="primary"):
 try:
  x=pd.read_csv(up) if up.name.lower().endswith(".csv") else pd.read_excel(up)
  cols={str(z).strip().lower():z for z in x.columns}
  def col(*names):
   for n in names:
    if n in cols:return cols[n]
   return None
  no=col("numero_ordine","ordine","order"); dt=col("data_ordine","data","order date"); cc=col("codice_cliente","cliente","customer"); ss=col("struttura","destinazione","ship to"); stt=col("stato_johnson","stato","status"); imp=col("importo","totale","amount")
  if no is None: st.error("Non trovo la colonna numero ordine/ordine.")
  else:
   for _,r in x.iterrows():
    payload={"numero_ordine":str(r[no]).strip(),"fonte":up.name}
    if dt is not None and pd.notna(r[dt]): payload["data_ordine"]=str(pd.to_datetime(r[dt]).date())
    if cc is not None and pd.notna(r[cc]): payload["codice_cliente"]=str(r[cc]).strip()
    if ss is not None and pd.notna(r[ss]): payload["struttura"]=str(r[ss]).strip()
    if stt is not None and pd.notna(r[stt]): payload["stato_johnson"]=str(r[stt]).strip()
    if imp is not None and pd.notna(r[imp]): payload["importo"]=float(r[imp])
    old=sb().table("ordini_johnson").select("id").eq("numero_ordine",payload["numero_ordine"]).limit(1).execute().data or []
    if old: sb().table("ordini_johnson").update(payload).eq("id",old[0]["id"]).execute()
    else: sb().table("ordini_johnson").insert(payload).execute()
   st.success(f"Importati/aggiornati {len(x)} record."); st.rerun()
 except Exception as e: st.error(f"Import non riuscito: {e}")
inter=get("interventi"); rig=get("righe_intervento"); ordj=get("ordini_johnson")
if inter.empty: st.info("Nessun intervento disponibile."); st.stop()
if not rig.empty:
 totals=rig.groupby("intervento_id").agg(valore_teorico=("totale","sum"),righe=("id","count")).reset_index()
 inter=inter.merge(totals,left_on="id",right_on="intervento_id",how="left")
else: inter["valore_teorico"]=0
inter["valore_teorico"]=pd.to_numeric(inter["valore_teorico"],errors="coerce").fillna(0)
def match_order(r):
 if ordj.empty:return pd.Series(["NESSUN ORDINE",None,None,None])
 cand=ordj.copy()
 if r.get("codice_cliente") and "codice_cliente" in cand: cand=cand[cand["codice_cliente"].astype(str).str.strip()==str(r["codice_cliente"]).strip()]
 if cand.empty and r.get("struttura") and "struttura" in ordj:
  cand=ordj[ordj["struttura"].astype(str).str.lower().str.strip()==str(r["struttura"]).lower().strip()]
 if cand.empty:return pd.Series(["NESSUN ORDINE",None,None,None])
 if pd.notna(r.get("data_intervento")) and "data_ordine" in cand:
  dd=pd.to_datetime(cand["data_ordine"],errors="coerce"); target=pd.to_datetime(r["data_intervento"]); cand=cand.assign(_dist=(dd-target).abs().dt.days).sort_values("_dist")
 o=cand.iloc[0]; imp=float(o.get("importo") or 0); teor=float(r.get("valore_teorico") or 0)
 status="CHIUSO" if teor>0 and imp>=teor*.99 else ("PARZIALE" if imp>0 else "DA VERIFICARE")
 return pd.Series([status,o.get("numero_ordine"),o.get("stato_johnson"),imp])
inter[["esito","ordine_jj","stato_jj","importo_jj"]]=inter.apply(match_order,axis=1)
a,b,c=st.columns(3); a.metric("Interventi",len(inter)); b.metric("Chiusi",int((inter.esito=="CHIUSO").sum())); c.metric("Da controllare",int((inter.esito!="CHIUSO").sum()))
show=[x for x in ["data_intervento","cartella_clinica","struttura","codice_cliente","valore_teorico","ordine_jj","importo_jj","stato_jj","esito"] if x in inter]
st.dataframe(inter[show].sort_values("data_intervento",ascending=False),use_container_width=True,hide_index=True)
out=io.BytesIO()
with pd.ExcelWriter(out,engine="xlsxwriter") as w: inter[show].to_excel(w,index=False,sheet_name="Riconciliazione")
st.download_button("⬇️ Esporta controllo Excel",out.getvalue(),"OrthoFlow_Controllo_Ordini_JJ.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
st.warning("Gli abbinamenti sono automatici e servono come pre-controllo: i casi PARZIALE / DA VERIFICARE / NESSUN ORDINE richiedono verifica amministrativa.")
