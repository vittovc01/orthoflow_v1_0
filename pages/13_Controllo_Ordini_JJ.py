import io
from jj_closures import division, select_division, prepare_closure, read_all
import pandas as pd
import streamlit as st
from orthoflow_branding import configure_page
from supabase import create_client
configure_page(page_title="Controllo Ordini J&J · P.M. Medical",page_icon="🔎",layout="wide")
if not st.session_state.get("user"): st.switch_page("pages/99_Login.py")
p=set(st.session_state.get("permessi",[]) or []); director=str(st.session_state.get("ruolo",""))=="Admin" or "DIREZIONE" in p
if not director and "AMMINISTRAZIONE" not in p: st.error("Accesso non autorizzato."); st.stop()
@st.cache_resource
def sb():
 return create_client(str(st.secrets.get("SUPABASE_URL")).rstrip("/"),str(st.secrets.get("SUPABASE_SERVICE_KEY") or st.secrets.get("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_KEY")))
def get(t): return read_all(sb(),t)
st.title("🔎 Controllo Ordini J&J")
st.caption("Riconcilia consumi/interventi P.M. Medical con ordini, fatture e chiusure J&J. Residui e anomalie restano aperti e passano al mese successivo.")
up=st.file_uploader("⬆️ Importa dataset J&J consolidato (CSV/Excel)",type=["xlsx","xls","csv"])
if up and st.button("Importa / aggiorna J&J",type="primary"):
 try:
  if up.name.lower().endswith(".csv"):
   x=pd.read_csv(up,sep=None,engine="python",encoding="utf-8-sig")
  else:
   x=pd.read_excel(up)
  aliases={
   "NumeroOrdine":["NumeroOrdine","numero_ordine","ordine","order"],
   "DataOrdine":["DataOrdine","data_ordine","data","order date"],
   "RiferimentoCliente":["RiferimentoCliente","riferimento_cliente","riferimento ordine di acquisto del cliente"],
   "CodiceCliente":["CodiceCliente","codice_cliente","cliente","customer"],
   "Struttura":["Struttura","struttura","destinazione","ship to"],
   "CodiceProdotto":["CodiceProdotto","codice prodotto","codice","product code"],
   "Lotto":["Lotto","lotto","lot"],
   "Quantita":["Quantita","quantità","quantita","quantity"],
   "PrezzoUnitario":["PrezzoUnitario","prezzo unitario","prezzo","unit price"],
   "TotaleRiga":["TotaleRiga","totale riga","totale","line total"],
   "StatoRiga":["StatoRiga","stato riga"],
   "StatoOrdine":["StatoOrdine","stato ordine","stato_johnson","status"],
   "NumeroFattura":["NumeroFattura","numero_fattura","fattura","invoice"],
   "DataFattura":["DataFattura","data_fattura","invoice date"],
   "NumeroDDT":["NumeroDDT","numero_ddt","ddt"]
  }
  norm={str(z).strip().lower():z for z in x.columns}
  def pick(k):
   for a in aliases[k]:
    if a.lower() in norm:return norm[a.lower()]
   return None
  no=pick("NumeroOrdine"); cp=pick("CodiceProdotto")
  if no is None: st.error("Manca NumeroOrdine.")
  else:
   imported_orders=set()
   for ix,r in x.iterrows():
    numero=str(r[no]).strip()
    if not numero or numero.lower()=="nan": continue
    payload={"numero_ordine":numero,"fonte":up.name,"fonte_aggiornata_at":pd.Timestamp.utcnow().isoformat()}
    mapping={"DataOrdine":"data_ordine","RiferimentoCliente":"riferimento_cliente","CodiceCliente":"account_jj","Struttura":"struttura","StatoOrdine":"stato_johnson","NumeroFattura":"numero_fattura","DataFattura":"data_fattura"}
    for k,dest in mapping.items():
     z=pick(k)
     if z is not None and pd.notna(r[z]) and str(r[z]).strip():
      payload[dest]=str(pd.to_datetime(r[z]).date()) if k in ("DataOrdine","DataFattura") else str(r[z]).strip()
    payload["codice_cliente"]=None # CAC J&J is not the internal customer code
    payload["stato_riconciliazione"]="DA_ABBINARE"
    base=pd.to_datetime(payload.get("data_fattura") or payload.get("data_ordine") or pd.Timestamp.today())
    payload["mese_competenza"]=str(base.to_period("M").start_time.date())
    old=sb().table("ordini_johnson").select("id").eq("numero_ordine",numero).limit(1).execute().data or []
    if old:
     oid=old[0]["id"]; sb().table("ordini_johnson").update(payload).eq("id",oid).execute()
    else:
     oid=sb().table("ordini_johnson").insert(payload).execute().data[0]["id"]
    imported_orders.add(oid)
    if cp is not None and pd.notna(r[cp]) and str(r[cp]).strip():
     def val(k):
      z=pick(k); return r[z] if z is not None and pd.notna(r[z]) else None
     lotto=val("Lotto"); codice=str(r[cp]).strip()
     line={"ordine_id":oid,"numero_riga_fonte":str(ix+1),"codice":codice,"lotto":None if lotto is None else str(lotto).strip(),
           "quantita":pd.to_numeric(val("Quantita"),errors="coerce"),"prezzo":pd.to_numeric(val("PrezzoUnitario"),errors="coerce"),
           "totale_riga":pd.to_numeric(val("TotaleRiga"),errors="coerce"),"stato_riga":val("StatoRiga"),
           "fonte_dato":up.name,"fonte_aggiornata_at":pd.Timestamp.utcnow().isoformat()}
     line={k:(None if pd.isna(v) else v) for k,v in line.items()}
     ex=sb().table("righe_ordini_johnson").select("id").eq("ordine_id",oid).eq("numero_riga_fonte",str(ix+1)).limit(1).execute().data or []
     if ex: sb().table("righe_ordini_johnson").update(line).eq("id",ex[0]["id"]).execute()
     else: sb().table("righe_ordini_johnson").insert(line).execute()
    nf=payload.get("numero_fattura")
    if nf:
     fp={"ordine_id":oid,"numero_fattura":nf,"data_fattura":payload.get("data_fattura"),"fonte":up.name}
     fe=sb().table("fatture_johnson").select("id").eq("ordine_id",oid).eq("numero_fattura",nf).limit(1).execute().data or []
     if fe: sb().table("fatture_johnson").update(fp).eq("id",fe[0]["id"]).execute()
     else: sb().table("fatture_johnson").insert(fp).execute()
    nd=val("NumeroDDT") if cp is not None else None
    if nd is not None and str(nd).strip():
     dp={"ordine_id":oid,"numero_ddt":str(nd).strip(),"fonte":up.name}
     de=sb().table("ddt_johnson").select("id").eq("numero_ddt",str(nd).strip()).limit(1).execute().data or []
     if de: sb().table("ddt_johnson").update(dp).eq("id",de[0]["id"]).execute()
     else: sb().table("ddt_johnson").insert(dp).execute()
   st.success(f"Import completato: {len(imported_orders)} ordini, {len(x)} righe sorgente."); st.rerun()
 except Exception as e: st.error(f"Import non riuscito: {e}")
inter=get("interventi"); rig=get("righe_intervento"); ordj=get("ordini_johnson")
if not ordj.empty:
 ordj["fase"]=ordj.apply(lambda x: "✅ CHIUSO" if pd.notna(x.get("chiuso_at")) else ("🧾 FATTURA PRESENTE" if pd.notna(x.get("numero_fattura")) else "🔎 FATTURA DA VERIFICARE"),axis=1)
 st.subheader("📅 Ciclo mensile J&J")
 _o=ordj.copy(); _o["mese_competenza"]=pd.to_datetime(_o["mese_competenza"],errors="coerce")
 _open=_o[_o["chiuso_at"].isna()]
 m1,m2,m3=st.columns(3); m1.metric("Fattura da verificare",int((_open["fase"]=="🔎 FATTURA DA VERIFICARE").sum())); m2.metric("Fattura acquisita, da abbinare",int((_open["fase"]=="🧾 FATTURA PRESENTE").sum())); m3.metric("Aperti / riporto",len(_open))
 _cols=[x for x in ["numero_ordine","data_ordine","numero_fattura","data_fattura","stato_johnson","importo","mese_competenza","riportato_da_mese","fase","note_anomalia"] if x in _open]
 st.dataframe(_open[_cols].sort_values("data_ordine",ascending=False),use_container_width=True,hide_index=True)
 st.caption("A fine mese si chiudono solo le posizioni completamente riconciliate. Residui, ordini senza fattura acquisita e anomalie di prezzo restano aperti per il mese successivo.")
if inter.empty: st.info("Nessun intervento disponibile."); st.stop()
if not rig.empty:
 totals=rig.groupby("intervento_id").agg(valore_teorico=("totale","sum"),righe=("id","count")).reset_index()
 inter=inter.merge(totals,left_on="id",right_on="intervento_id",how="left")
else: inter["valore_teorico"]=0
inter["valore_teorico"]=pd.to_numeric(inter["valore_teorico"],errors="coerce").fillna(0)
def match_order(r):
 # Order totals and nearby dates are not evidence of an intervention allocation.
 return pd.Series(["DA ABBINARE",None,None,None])
inter[["esito","ordine_jj","stato_jj","importo_jj"]]=inter.apply(match_order,axis=1)
a,b,c=st.columns(3); a.metric("Interventi",len(inter)); b.metric("Chiusi",int((inter.esito=="CHIUSO").sum())); c.metric("Da controllare",int((inter.esito!="CHIUSO").sum()))
show=[x for x in ["data_intervento","cartella_clinica","struttura","codice_cliente","valore_teorico","ordine_jj","importo_jj","stato_jj","esito"] if x in inter]
st.dataframe(inter[show].sort_values("data_intervento",ascending=False),use_container_width=True,hide_index=True)
out=io.BytesIO()
with pd.ExcelWriter(out,engine="xlsxwriter") as w: inter[show].to_excel(w,index=False,sheet_name="Riconciliazione")
st.download_button("⬇️ Esporta controllo Excel",out.getvalue(),"PM_Medical_Controllo_Ordini_JJ.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
st.info("Ordini e fatture importati restano da abbinare alle righe degli interventi. Struttura, data e importo non determinano la chiusura.")

st.divider()
st.subheader("🔗 Riconciliazione analitica")
st.caption("Incrocio Codice + Lotto + Quantità + Prezzo tra righe intervento P.M. Medical e righe ordine J&J.")
c1,c2=st.columns(2)
st.info("La riconciliazione automatica precedente è sospesa: i collegamenti devono rispettare riferimento, prodotto, lotto e quantità residua. Nessuna chiusura per sola coincidenza di struttura o importo.")
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
 dash=tmp.groupby("mese").agg(ordini=("id","count"),valore_jj=("importo","sum"),chiusi=("chiuso_at",lambda x:x.notna().sum()),fattura_da_verificare=("numero_fattura",lambda x:x.isna().sum())).reset_index()
 if not ric.empty:
  rr=ric.copy(); rr["mese"]=pd.to_datetime(rr["mese_competenza"],errors="coerce").dt.to_period("M").astype(str)
  aa=rr.groupby("mese").agg(anomalie=("esito",lambda x:(x!="OK").sum()),differenze_prezzo=("differenza_prezzo",lambda x:pd.to_numeric(x,errors="coerce").abs().sum())).reset_index()
  dash=dash.merge(aa,on="mese",how="left")
 st.dataframe(dash.sort_values("mese",ascending=False),use_container_width=True,hide_index=True)

st.divider()
st.subheader("📦 Controllo reintegri da DDT Carico Mobile")
st.caption("Il DDT ricevuto in P.M. Medical è la fonte primaria del reintegro fisico. I DDT Customer Connect restano solo una fonte opzionale di controllo.")
if st.button("🔄 Incrocia consumi → ordini J&J → DDT ricevuti"):
 try:
  n=sb().rpc("riconcilia_reintegri_jj",{}).execute().data
  st.success(f"Controllo reintegri aggiornato: {n} righe."); st.rerun()
 except Exception as e: st.error(str(e))
rein=get("riconciliazioni_reintegro_jj")
if not rein.empty:
 ri2=get("righe_intervento"); ro2=get("righe_ordini_johnson"); dr2=get("ddt_righe"); dh2=get("ddt")
 v=rein.merge(ri2[["id","intervento_id","codice","lotto"]].rename(columns={"id":"riga_intervento_id"}),on="riga_intervento_id",how="left")
 if not ro2.empty: v=v.merge(ro2[["id","ordine_id"]].rename(columns={"id":"riga_ordine_id"}),on="riga_ordine_id",how="left")
 if not dr2.empty:
  v=v.merge(dr2[["id","ddt_id"]].rename(columns={"id":"ddt_riga_id"}),on="ddt_riga_id",how="left")
  if not dh2.empty: v=v.merge(dh2[["id","numero_ddt","data_ddt"]].rename(columns={"id":"ddt_id"}),on="ddt_id",how="left")
 oo2=get("ordini_johnson")
 if not oo2.empty and "ordine_id" in v: v=v.merge(oo2[["id","numero_ordine","numero_fattura"]].rename(columns={"id":"ordine_id"}),on="ordine_id",how="left")
 cc=[x for x in ["codice","lotto","quantita_consumata","quantita_ordinata","quantita_ricevuta","numero_ordine","numero_fattura","numero_ddt","data_ddt","esito"] if x in v]
 st.dataframe(v[cc],use_container_width=True,hide_index=True)
 m1,m2,m3,m4=st.columns(4)
 m1.metric("Da ordinare",int((v.esito=="DA_ORDINARE").sum()))
 m2.metric("Ordinati da ricevere",int((v.esito=="ORDINATO_DA_RICEVERE").sum()))
 m3.metric("Parziali",int((v.esito=="REINTEGRO_PARZIALE").sum()))
 m4.metric("Ricevuti",int((v.esito=="REINTEGRO_RICEVUTO").sum()))

st.divider()
st.subheader("🏁 Chiusura mensile ufficiale J&J")
st.caption("Carica il file finale mensile Johnson separatamente per TRAUMA e PROTESICA. È il consuntivo ufficiale da confrontare con la previsione P.M. Medical.")
cm1,cm2=st.columns(2)
div=cm1.selectbox("Divisione",["TRAUMA","PROTESICA"],key="close_div")
mese_close=cm2.date_input("Mese di chiusura",value=pd.Timestamp.today().replace(day=1).date(),key="close_month")
closefile=st.file_uploader("File chiusura dettagliata J&J",type=["xlsx","xls","csv"],key="jj_close")
if closefile and st.button("📥 Importa e confronta chiusura",type="primary"):
 try:
  prepared=prepare_closure(closefile.getvalue(),closefile.name,div)
  result=sb().rpc("importa_chiusura_jj",{"p_divisione":div,"p_mese":str(pd.Timestamp(mese_close).to_period("M").start_time.date()),"p_nome_file":closefile.name,"p_fingerprint":prepared["fingerprint"],"p_righe":prepared["rows"]}).execute().data
  st.success(f"Chiusura {div}: {result['righe']} righe · " + ("già presente, nessun duplicato" if result.get("gia_presente") else "importata") + f" · Fatturato € {float(prepared['invoiced_sales']):,.2f}.")

 except Exception as e: st.error(f"Chiusura non importata: {e}")

st.subheader(f"📈 {div} · Previsione e consuntivo J&J")
_m0=pd.Timestamp(mese_close).to_period("M").start_time.date(); _m1=(pd.Timestamp(_m0)+pd.offsets.MonthEnd(1)).date()
ints=get("interventi"); ris=get("righe_intervento"); clos=get("chiusure_mensili_johnson")
prev=0
if not ints.empty and "linea" in ints:
 _unknown=ints[ints["linea"].map(division)=="DA CLASSIFICARE"]
 if not _unknown.empty: st.warning(f"{len(_unknown)} interventi da classificare: esclusi dai totali Trauma e Protesica finché la linea non viene corretta.")
if not ints.empty and not ris.empty:
 ints=select_division(ints,div,"linea")
 ids=ints[(pd.to_datetime(ints["data_intervento"],errors="coerce").dt.date>=_m0)&(pd.to_datetime(ints["data_intervento"],errors="coerce").dt.date<=_m1)]["id"].tolist()
 rr=ris[ris["intervento_id"].isin(ids)].copy()
 base="totale" if "totale" in rr else "valore"
 if base in rr: prev=float(pd.to_numeric(rr[base],errors="coerce").fillna(0).sum())
cons=0
if not clos.empty:
 cm=pd.to_datetime(clos["mese"],errors="coerce").dt.to_period("M")
 sel=select_division(clos[(cm==pd.Timestamp(_m0).to_period("M"))],div)
 cons=float(pd.to_numeric(sel["importo_totale_jj"],errors="coerce").fillna(0).sum())
a1,a2,a3=st.columns(3); a1.metric("Previsione P.M. Medical",f"€ {prev:,.2f}"); a2.metric("Chiusura J&J caricata",f"€ {cons:,.2f}"); a3.metric("Differenza",f"€ {cons-prev:,.2f}")
st.caption("La previsione deriva dall'operatività P.M. Medical; il file finale J&J è il consuntivo ufficiale. Le differenze dovranno essere analizzate per ordine/codice/lotto/quantità/prezzo, senza considerare automaticamente il dato J&J corretto.")

st.divider()
st.subheader("🔬 Controllo dettagliato file finale")
st.caption("Dopo il caricamento, P.M. Medical conserva ogni riga del file finale J&J per il confronto con consumi, ordini, prezzi e reintegri.")
if not clos.empty:
 _mc=pd.to_datetime(clos["mese"],errors="coerce").dt.to_period("M")
 _fc=select_division(clos[_mc==pd.Timestamp(_m0).to_period("M")],div)
 if not _fc.empty:
  _id=st.selectbox("Chiusura importata",_fc["id"].astype(int).tolist(),format_func=lambda x: str(_fc[_fc["id"]==x].iloc[0].get("divisione"))+" · "+str(_fc[_fc["id"]==x].iloc[0].get("nome_file")),key="detail_close")
  _det=read_all(sb(),"righe_chiusura_johnson",{"chiusura_id":int(_id)})
  if not _det.empty:
   for _label,_key in [("fattura","Order Transactions[O. Invoice Number]"),("data_fattura","Calendar[Date]"),("tipo_movimento","Order Type[O. Sub Type]"),("descrizione","Product[Product]")]:
    _det[_label]=_det["raw_data"].map(lambda r:r.get(_key) if isinstance(r,dict) else None)
   st.dataframe(_det[[x for x in ["fattura","data_fattura","tipo_movimento","riferimento_cliente","numero_ordine","codice","descrizione","lotto","quantita","prezzo_unitario","totale_riga"] if x in _det]],use_container_width=True,hide_index=True)
   st.download_button("⬇️ Esporta dettaglio acquisito",_det.to_csv(index=False).encode("utf-8-sig"),f"Dettaglio_chiusura_JJ_{div}.csv","text/csv")

st.divider()
st.subheader("🎯 Previsione chiusura P.M. Medical")
st.caption("Previsione indipendente dai consuntivi J&J: nasce dagli interventi e consumi registrati in P.M. Medical.")
pf_i=get("interventi"); pf_r=get("righe_intervento")
if not pf_i.empty and not pf_r.empty:
 pf_i["_data"]=pd.to_datetime(pf_i["data_intervento"],errors="coerce")
 mesi=sorted(pf_i["_data"].dropna().dt.to_period("M").unique(),reverse=True)
 if mesi:
  pm=st.selectbox("Mese previsione",mesi,format_func=lambda x:str(x),key="forecast_month")
  pi=select_division(pf_i[pf_i["_data"].dt.to_period("M")==pm],div,"linea")
  pr=pf_r[pf_r["intervento_id"].isin(pi["id"])].copy()
  pr["_valore"]=pd.to_numeric(pr["totale"],errors="coerce").fillna(0) if "totale" in pr else 0
  if "totale" not in pr or pd.Series(pr["_valore"]).fillna(0).eq(0).all():
   pr["_valore"]=pd.to_numeric(pr["quantita"],errors="coerce").fillna(0)*pd.to_numeric(pr["prezzo"],errors="coerce").fillna(0)
  pr=pr.merge(pi[["id","struttura","linea","codice_cliente","cartella_clinica"]].rename(columns={"id":"intervento_id"}),on="intervento_id",how="left")
  pr["_divisione"]=pr["linea"].map(division)
  tot=float(pd.to_numeric(pr["_valore"],errors="coerce").fillna(0).sum())
  ordp=get("ordini_johnson"); ordtot=0.0
  if not ordp.empty and "data_ordine" in ordp and "importo" in ordp:
   om=pd.to_datetime(ordp["data_ordine"],errors="coerce").dt.to_period("M")
   ordtot=float(pd.to_numeric(select_division(ordp.loc[om==pm],div).get("importo",pd.Series(dtype=float)),errors="coerce").fillna(0).sum())
  clp=get("chiusure_mensili_johnson"); nis=0.0; inv=0.0
  if not clp.empty:
   cm=pd.to_datetime(clp["mese"],errors="coerce").dt.to_period("M"); mc=select_division(clp[cm==pm],div)
   if "nis_totale" in mc: nis=float(pd.to_numeric(mc["nis_totale"],errors="coerce").fillna(0).sum())
   if "invoiced_sales_totale" in mc: inv=float(pd.to_numeric(mc["invoiced_sales_totale"],errors="coerce").fillna(0).sum())
  a,b,d,e=st.columns(4)
  a.metric("Previsione P.M. Medical",f"€ {tot:,.2f}")
  b.metric("Ordini J&J da classificare",len(ordp) if "divisione" not in ordp else int((ordp["divisione"].map(division)=="DA CLASSIFICARE").sum()))
  st.caption("Gli importi degli ordini non classificati non vengono attribuiti a Trauma o Protesica. Il confronto per mese di intervento non prova la fatturazione nello stesso mese.")
  d.metric("NIS chiusura J&J",f"€ {nis:,.2f}",f"€ {nis-tot:,.2f}")
  e.metric("Invoiced Sales J&J",f"€ {inv:,.2f}")
  by=pr.groupby(["_divisione","struttura"],dropna=False).agg(Interventi=("intervento_id","nunique"),Righe=("intervento_id","size"),Previsione_EUR=("_valore","sum")).reset_index().rename(columns={"_divisione":"Divisione","struttura":"Struttura"})
  st.dataframe(by.sort_values("Previsione_EUR",ascending=False),use_container_width=True,hide_index=True)
  miss=pr[pr["linea"].isna() | pr["codice_cliente"].isna()]
  if not miss.empty: st.warning(f"{len(miss)} righe senza Linea o Codice Cliente: incluse nel totale, ma da classificare per il confronto J&J preciso.")
  st.download_button("⬇️ Esporta previsione dettagliata",pr.to_csv(index=False).encode("utf-8-sig"),f"Previsione_PM_Medical_{div}_{pm}.csv","text/csv")