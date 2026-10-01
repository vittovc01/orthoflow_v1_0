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
    payload["codice_cliente"]=payload.get("account_jj")
    payload["stato_riconciliazione"]="FATTURATO" if payload.get("numero_fattura") else "DA_FATTURARE"
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
 ordj["fase"]=ordj.apply(lambda x: "✅ CHIUSO" if pd.notna(x.get("chiuso_at")) else ("🧾 FATTURATO" if pd.notna(x.get("numero_fattura")) else "⏳ DA FATTURARE"),axis=1)
 st.subheader("📅 Ciclo mensile J&J")
 _o=ordj.copy(); _o["mese_competenza"]=pd.to_datetime(_o["mese_competenza"],errors="coerce")
 _open=_o[_o["chiuso_at"].isna()]
 m1,m2,m3=st.columns(3); m1.metric("Da fatturare",int((_open["fase"]=="⏳ DA FATTURARE").sum())); m2.metric("Fatturati da chiudere",int((_open["fase"]=="🧾 FATTURATO").sum())); m3.metric("Aperti / riporto",len(_open))
 _cols=[x for x in ["numero_ordine","data_ordine","numero_fattura","data_fattura","stato_johnson","importo","mese_competenza","riportato_da_mese","fase","note_anomalia"] if x in _open]
 st.dataframe(_open[_cols].sort_values("data_ordine",ascending=False),use_container_width=True,hide_index=True)
 st.caption("A fine mese si chiudono solo le posizioni completamente riconciliate. Residui, ordini non fatturati e anomalie di prezzo restano aperti per il mese successivo.")
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

st.divider()
st.subheader("📦 Controllo reintegri da DDT Carico Mobile")
st.caption("Il DDT ricevuto in OrthoFlow è la fonte primaria del reintegro fisico. I DDT Customer Connect restano solo una fonte opzionale di controllo.")
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
st.caption("Carica il file finale mensile Johnson separatamente per TRAUMA e PROTESICA. È il consuntivo ufficiale da confrontare con la previsione OrthoFlow.")
cm1,cm2=st.columns(2)
div=cm1.selectbox("Divisione",["TRAUMA","PROTESICA"],key="close_div")
mese_close=cm2.date_input("Mese di chiusura",value=pd.Timestamp.today().replace(day=1).date(),key="close_month")
closefile=st.file_uploader("File chiusura dettagliata J&J",type=["xlsx","xls","csv"],key="jj_close")
if closefile and st.button("📥 Importa e confronta chiusura",type="primary"):
 try:
  z=pd.read_csv(closefile,sep=None,engine="python",encoding="utf-8-sig") if closefile.name.lower().endswith(".csv") else pd.read_excel(closefile)
  lc={str(k).strip().lower():k for k in z.columns}
  def zcol(*names):
   for n in names:
    if n.lower() in lc:return lc[n.lower()]
   return None
  code=zcol("codice","codice prodotto","product code"); qty=zcol("quantita","quantità","quantity"); price=zcol("prezzo","prezzo unitario","unit price"); total=zcol("totale","totale riga","total"); order=zcol("numero ordine","numero_ordine","ordine","order"); lot=zcol("lotto","lot")
  econ_nis=zcol("sum of [nis]","nis"); econ_is=zcol("sum of [invoiced_sales__is_]","invoiced_sales","invoiced sales"); cac=zcol("c account[c. account code (cac)]","cac"); fam=zcol("product[p. bravo major]","famiglia prodotto"); bill=zcol("c bill to[c. bill to]","bill to"); acc=zcol("c account[c. account]","account"); reg=zcol("c account[c. account region]","region"); prov=zcol("c account[c. account county]","county")
  if code is None and econ_nis is None and econ_is is None: st.error("Formato non riconosciuto: servono colonne di dettaglio ordine oppure NIS/Invoiced Sales.")
  else:
   is_econ=(code is None and (econ_nis is not None or econ_is is not None))
   valid=z.copy()
   if is_econ and cac is not None: valid=valid[valid[cac].notna()]
   nis_tot=float(pd.to_numeric(valid[econ_nis],errors="coerce").fillna(0).sum()) if econ_nis else 0
   is_tot=float(pd.to_numeric(valid[econ_is],errors="coerce").fillna(0).sum()) if econ_is else 0
   tot=float(pd.to_numeric(valid[total],errors="coerce").fillna(0).sum()) if total else nis_tot
   h=sb().table("chiusure_mensili_johnson").insert({"mese":str(pd.Timestamp(mese_close).to_period("M").start_time.date()),"divisione":div,"nome_file":closefile.name,"importo_totale_jj":tot,"nis_totale":nis_tot,"invoiced_sales_totale":is_tot,"righe_totali":len(valid)}).execute().data[0]
   for _,r in valid.iterrows():
    p={"chiusura_id":h["id"],"codice":str(r[code]).strip() if code is not None and pd.notna(r[code]) else "ECONOMICO","raw_data":{str(k):None if pd.isna(v) else str(v) for k,v in r.items()}}
    if is_econ:
     emap=[(reg,"regione"),(prov,"provincia"),(bill,"bill_to"),(acc,"account_name"),(fam,"famiglia_prodotto"),(cac,"cac")]
     for ec,ed in emap:
      if ec is not None and pd.notna(r[ec]): p[ed]=str(r[ec]).strip()
     if econ_nis is not None and pd.notna(r[econ_nis]): p["nis"]=float(pd.to_numeric(r[econ_nis],errors="coerce"))
     if econ_is is not None and pd.notna(r[econ_is]): p["invoiced_sales"]=float(pd.to_numeric(r[econ_is],errors="coerce"))
    for col,dest,num in [(order,"numero_ordine",False),(lot,"lotto",False),(qty,"quantita",True),(price,"prezzo_unitario",True),(total,"totale_riga",True)]:
     if col is not None and pd.notna(r[col]): p[dest]=float(pd.to_numeric(r[col],errors="coerce")) if num and pd.notna(pd.to_numeric(r[col],errors="coerce")) else str(r[col]).strip()
    sb().table("righe_chiusura_johnson").insert(p).execute()
   st.success(f"Chiusura {div} importata: {len(valid)} righe · NIS € {nis_tot:,.2f} · Invoiced Sales € {is_tot:,.2f}."); st.rerun()
 except Exception as e: st.error(f"Chiusura non importata: {e}")

st.subheader("📈 Previsione OrthoFlow vs consuntivo J&J")
_m0=pd.Timestamp(mese_close).to_period("M").start_time.date(); _m1=(pd.Timestamp(_m0)+pd.offsets.MonthEnd(1)).date()
ints=get("interventi"); ris=get("righe_intervento"); clos=get("chiusure_mensili_johnson")
prev=0
if not ints.empty and not ris.empty:
 ids=ints[(pd.to_datetime(ints["data_intervento"],errors="coerce").dt.date>=_m0)&(pd.to_datetime(ints["data_intervento"],errors="coerce").dt.date<=_m1)]["id"].tolist()
 rr=ris[ris["intervento_id"].isin(ids)].copy()
 base="totale" if "totale" in rr else "valore"
 if base in rr: prev=float(pd.to_numeric(rr[base],errors="coerce").fillna(0).sum())
cons=0
if not clos.empty:
 cm=pd.to_datetime(clos["mese"],errors="coerce").dt.to_period("M")
 sel=clos[(cm==pd.Timestamp(_m0).to_period("M"))]
 cons=float(pd.to_numeric(sel["importo_totale_jj"],errors="coerce").fillna(0).sum())
a1,a2,a3=st.columns(3); a1.metric("Previsione OrthoFlow",f"€ {prev:,.2f}"); a2.metric("Chiusura J&J caricata",f"€ {cons:,.2f}"); a3.metric("Differenza",f"€ {cons-prev:,.2f}")
st.caption("La previsione deriva dall'operatività OrthoFlow; il file finale J&J è il consuntivo ufficiale. Le differenze dovranno essere analizzate per ordine/codice/lotto/quantità/prezzo, senza considerare automaticamente il dato J&J corretto.")

st.divider()
st.subheader("🔬 Controllo dettagliato file finale")
st.caption("Dopo il caricamento, OrthoFlow conserva ogni riga del file finale J&J per il confronto con consumi, ordini, prezzi e reintegri.")
if not clos.empty:
 _mc=pd.to_datetime(clos["mese"],errors="coerce").dt.to_period("M")
 _fc=clos[_mc==pd.Timestamp(_m0).to_period("M")]
 if not _fc.empty:
  _id=st.selectbox("Chiusura importata",_fc["id"].astype(int).tolist(),format_func=lambda x: str(_fc[_fc["id"]==x].iloc[0].get("divisione"))+" · "+str(_fc[_fc["id"]==x].iloc[0].get("nome_file")),key="detail_close")
  _det=pd.DataFrame(sb().table("righe_chiusura_johnson").select("*").eq("chiusura_id",int(_id)).execute().data or [])
  if not _det.empty:
   st.dataframe(_det[[x for x in ["numero_ordine","riferimento_cliente","codice","lotto","quantita","prezzo_unitario","totale_riga"] if x in _det]],use_container_width=True,hide_index=True)
   st.download_button("⬇️ Esporta dettaglio acquisito",_det.to_csv(index=False).encode("utf-8-sig"),"Dettaglio_chiusura_JJ.csv","text/csv")
