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
st.caption("Riconcilia consumi/interventi OrthoFlow con ordini, fatture e chiusure J&J. Residui e anomalie restano aperti e passano al mese successivo.")
up=st.file_uploader("⬆️ Importa file Johnson (Excel/CSV)",type=["xlsx","xls","csv"])
if up and st.button("Importa dati Johnson",type="primary"):
 try:
  x=pd.read_csv(up) if up.name.lower().endswith(".csv") else pd.read_excel(up)
  cols={str(z).strip().lower():z for z in x.columns}
  def col(*names):
   for n in names:
    if n in cols:return cols[n]
   return None
  no=col("numero_ordine","ordine","order"); dt=col("data_ordine","data","order date"); cc=col("codice_cliente","cliente","customer"); ss=col("struttura","destinazione","ship to"); stt=col("stato_johnson","stato","status"); imp=col("importo","totale","amount"); nf=col("numero_fattura","fattura","invoice"); df=col("data_fattura","invoice date")
  if no is None: st.error("Non trovo la colonna numero ordine/ordine.")
  else:
   for _,r in x.iterrows():
    payload={"numero_ordine":str(r[no]).strip(),"fonte":up.name}
    if dt is not None and pd.notna(r[dt]): payload["data_ordine"]=str(pd.to_datetime(r[dt]).date())
    if cc is not None and pd.notna(r[cc]): payload["codice_cliente"]=str(r[cc]).strip()
    if ss is not None and pd.notna(r[ss]): payload["struttura"]=str(r[ss]).strip()
    if stt is not None and pd.notna(r[stt]): payload["stato_johnson"]=str(r[stt]).strip()
    if imp is not None and pd.notna(r[imp]): payload["importo"]=float(r[imp])\n    if nf is not None and pd.notna(r[nf]): payload["numero_fattura"]=str(r[nf]).strip()\n    if df is not None and pd.notna(r[df]): payload["data_fattura"]=str(pd.to_datetime(r[df]).date())\n    payload["stato_riconciliazione"]="FATTURATO" if payload.get("numero_fattura") else "DA_FATTURARE"\n    _base=pd.to_datetime(payload.get("data_fattura") or payload.get("data_ordine") or pd.Timestamp.today())\n    payload["mese_competenza"]=str(_base.to_period("M").start_time.date())
    old=sb().table("ordini_johnson").select("id").eq("numero_ordine",payload["numero_ordine"]).limit(1).execute().data or []
    if old: sb().table("ordini_johnson").update(payload).eq("id",old[0]["id"]).execute()
    else: sb().table("ordini_johnson").insert(payload).execute()
   st.success(f"Importati/aggiornati {len(x)} record."); st.rerun()
 except Exception as e: st.error(f"Import non riuscito: {e}")
inter=get("interventi"); rig=get("righe_intervento"); ordj=get("ordini_johnson")\nif not ordj.empty:\n ordj["fase"]=ordj.apply(lambda x: "✅ CHIUSO" if pd.notna(x.get("chiuso_at")) else ("🧾 FATTURATO" if pd.notna(x.get("numero_fattura")) else "⏳ DA FATTURARE"),axis=1)\n st.subheader("📅 Ciclo mensile J&J")\n _o=ordj.copy(); _o["mese_competenza"]=pd.to_datetime(_o["mese_competenza"],errors="coerce")\n _open=_o[_o["chiuso_at"].isna()]\n m1,m2,m3=st.columns(3); m1.metric("Da fatturare",int((_open["fase"]=="⏳ DA FATTURARE").sum())); m2.metric("Fatturati da chiudere",int((_open["fase"]=="🧾 FATTURATO").sum())); m3.metric("Aperti / riporto",len(_open))\n _cols=[x for x in ["numero_ordine","data_ordine","numero_fattura","data_fattura","stato_johnson","importo","mese_competenza","riportato_da_mese","fase","note_anomalia"] if x in _open]\n st.dataframe(_open[_cols].sort_values("data_ordine",ascending=False),use_container_width=True,hide_index=True)\n st.caption("A fine mese si chiudono solo le posizioni completamente riconciliate. Residui, ordini non fatturati e anomalie di prezzo restano aperti per il mese successivo.")
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

st.divider()
st.subheader("🔗 Riconciliazione analitica")
st.caption("Incrocio Codice + Lotto + Quantità + Prezzo tra righe intervento OrthoFlow e righe ordine J&J.")
c1,c2=st.columns(2)
if c1.button("🔄 Esegui riconciliazione automatica",type="primary"):
 try:
  n=sb().rpc("riconcilia_johnson_auto",{}).execute().data
  st.success(f"Riconciliazione aggiornata: {n} abbinamenti elaborati."); st.rerun()
 except Exception as e: st.error(str(e))
ric=get("riconciliazioni_johnson")
if not ric.empty:
 rj=get("righe_ordini_johnson")
 oo=get("ordini_johnson")
 ii=get("interventi")
 ri=get("righe_intervento")
 v=ric.merge(ri[["id","codice","lotto","quantita","intervento_id"]].rename(columns={"id":"riga_intervento_id","quantita":"qta_orthoflow"}),on="riga_intervento_id",how="left",suffixes=("","_ri"))
 v=v.merge(oo[["id","numero_ordine","numero_fattura","data_fattura"]].rename(columns={"id":"ordine_id"}),on="ordine_id",how="left")
 v=v.merge(ii[["id","data_intervento","struttura","cartella_clinica"]].rename(columns={"id":"intervento_id"}),on="intervento_id",how="left")
 cols=[x for x in ["data_intervento","struttura","cartella_clinica","codice","lotto","qta_orthoflow","quantita_abbinata","prezzo_orthoflow","prezzo_johnson","differenza_prezzo","numero_ordine","numero_fattura","esito","mese_competenza"] if x in v]
 st.dataframe(v[cols].sort_values("data_intervento",ascending=False),use_container_width=True,hide_index=True)
 an=v[v["esito"]!="OK"]
 st.metric("Anomalie / residui aperti",len(an))
 if not an.empty: st.dataframe(an[cols],use_container_width=True,hide_index=True)

st.divider()
st.subheader("🔒 Chiusura e riporto mensile")
if not ordj.empty:
 openo=ordj[ordj["chiuso_at"].isna()] if "chiuso_at" in ordj else ordj
 if not openo.empty:
  labels={int(x["id"]):f'{x.get("numero_ordine","")} · {x.get("numero_fattura") or "DA FATTURARE"}' for _,x in openo.iterrows()}
  oid=st.selectbox("Ordine da chiudere",list(labels),format_func=lambda x:labels[x])
  if st.button("✅ Chiudi ordine riconciliato"):
   try: sb().rpc("chiudi_ordine_johnson",{"p_ordine_id":int(oid)}).execute(); st.success("Ordine chiuso."); st.rerun()
   except Exception as e: st.error(str(e))
mese=st.date_input("Mese da chiudere / riportare",value=pd.Timestamp.today().replace(day=1).date())
st.warning("Il riporto sposta al mese successivo solo le posizioni non chiuse. Le posizioni chiuse restano storicizzate nel mese di competenza.")
if st.button("➡️ Riporta aperti al mese successivo"):
 try:
  n=sb().rpc("riporta_aperti_johnson",{"p_mese":str(mese)}).execute().data
  st.success(f"{n} ordini aperti riportati al mese successivo."); st.rerun()
 except Exception as e: st.error(str(e))

st.divider()
st.subheader("📊 Cruscotto chiusura mensile")
if not ordj.empty:
 tmp=ordj.copy(); tmp["mese"]=pd.to_datetime(tmp["mese_competenza"],errors="coerce").dt.to_period("M").astype(str)
 tmp["importo"]=pd.to_numeric(tmp["importo"],errors="coerce").fillna(0)
 dash=tmp.groupby("mese").agg(ordini=("id","count"),valore_jj=("importo","sum"),chiusi=("chiuso_at",lambda x:x.notna().sum()),da_fatturare=("numero_fattura",lambda x:x.isna().sum())).reset_index()
 if not ric.empty:
  rr=ric.copy(); rr["mese"]=pd.to_datetime(rr["mese_competenza"],errors="coerce").dt.to_period("M").astype(str)
  aa=rr.groupby("mese").agg(anomalie=("esito",lambda x:(x!="OK").sum()),differenze_prezzo=("differenza_prezzo",lambda x:pd.to_numeric(x,errors="coerce").abs().sum())).reset_index()
  dash=dash.merge(aa,on="mese",how="left")
 st.dataframe(dash.sort_values("mese",ascending=False),use_container_width=True,hide_index=True)
