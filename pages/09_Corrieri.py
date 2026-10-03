import io
from PIL import Image
from datetime import date, datetime, timezone
import pandas as pd
import streamlit as st
from orthoflow_branding import configure_page
from streamlit_js_eval import get_geolocation
from streamlit_drawable_canvas import st_canvas
from supabase import create_client

configure_page(page_title="Controllo Corrieri · OrthoFlow",page_icon="🚐",layout="wide")
if not st.session_state.get("user"): st.switch_page("pages/99_Login.py")
p=set(st.session_state.get("permessi",[]) or [])
director=str(st.session_state.get("ruolo",""))=="Admin" or "DIREZIONE" in p
manager=director or "LOGISTICA" in p
courier_only="CORRIERE" in p and not manager
if not manager and not courier_only: st.error("Accesso non autorizzato."); st.stop()

@st.cache_resource
def sb():
    url=st.secrets.get("SUPABASE_URL"); key=st.secrets.get("SUPABASE_SERVICE_KEY") or st.secrets.get("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_KEY")
    return create_client(str(url).rstrip("/"),str(key))

def df(table,cols="*"):
    try:return pd.DataFrame(sb().table(table).select(cols).execute().data or [])
    except:return pd.DataFrame()

cour=df("corrieri"); stru=df("strutture_logistiche")
cmap=dict(zip(cour.id,cour.nome)) if not cour.empty else {}; smap=dict(zip(stru.id,stru.nome)) if not stru.empty else {}

st.title("🚐 Controllo Corrieri" if manager else "🚐 Le mie missioni")
if manager:
    mis=pd.DataFrame(sb().table("missioni_corrieri").select("*").order("data_missione",desc=True).limit(1000).execute().data or [])
    tim=pd.DataFrame(sb().table("timbrature_corrieri").select("*").order("created_at",desc=True).limit(2000).execute().data or [])
    if not mis.empty:
        mis["corriere"]=mis["corriere_id"].map(cmap); mis["struttura"]=mis["struttura_id"].map(smap)
        x1,x2,x3,x4=st.columns(4); x1.metric("Missioni",len(mis)); x2.metric("In corso",int(mis["stato"].isin(["PROGRAMMATA","ARRIVATO"]).sum())); x3.metric("Completate",int((mis["stato"]=="COMPLETATA").sum())); x4.metric("Timbrature",len(tim))
    tabs=st.tabs(["🛰️ Controllo live","📋 Missioni","➕ Nuova missione","⚙️ Anagrafiche","📦 Registro Kit","📊 Report Excel"])
    with tabs[0]:
        if tim.empty: st.info("Nessuna timbratura.")
        else:
            t=tim.copy(); t["corriere"]=t["corriere_id"].map(cmap); t["struttura"]=t["struttura_id"].map(smap)
            t["GPS"]="—"
            _valid=t["latitudine"].notna() & t["longitudine"].notna()
            t.loc[_valid,"GPS"]="📍 Posizione GPS ✓"
            t["precisione"]=pd.to_numeric(t.get("precisione_m"),errors="coerce").apply(lambda x:f"{x:.0f} m" if pd.notna(x) else "—")
            cols=[x for x in ["created_at","tipo","corriere","struttura","GPS","precisione"] if x in t]
            st.dataframe(t[cols].head(100),use_container_width=True,hide_index=True)
            last=t.iloc[0]; st.success(f'Ultima timbratura: {last.get("corriere","")} · {last.get("struttura","")} · {last.get("created_at","")}')
            if pd.notna(last.get("latitudine")) and pd.notna(last.get("longitudine")):
                _maps=f'https://www.google.com/maps/search/?api=1&query={last.get("latitudine")},{last.get("longitudine")}'
                st.link_button("📍 Apri posizione ultima timbratura",_maps)
            _map=t.dropna(subset=["latitudine","longitudine"]).copy()
            if not _map.empty:
                _map["lat"]=pd.to_numeric(_map["latitudine"],errors="coerce"); _map["lon"]=pd.to_numeric(_map["longitudine"],errors="coerce")
                _map=_map.dropna(subset=["lat","lon"])
                if not _map.empty:
                    st.caption("📍 Posizioni rilevate automaticamente alle timbrature")
                    st.map(_map[["lat","lon"]].head(100),use_container_width=True)
    with tabs[1]:
        if mis.empty: st.info("Nessuna missione.")
        else: st.dataframe(mis[[x for x in ["codice","data_missione","tipo","corriere","struttura","kit_codice","colli","stato"] if x in mis]],use_container_width=True,hide_index=True)
    with tabs[2]:
        ac=cour[cour.get("attivo",True)==True] if not cour.empty else cour; ast=stru[stru.get("attiva",True)==True] if not stru.empty else stru
        if ac.empty or ast.empty: st.info("Inserisci prima corriere e struttura.")
        else:
            with st.form("new_mission"):
                codice=st.text_input("Codice missione",value=f"M-{date.today().strftime('%Y%m%d')}-"); dm=st.date_input("Data",date.today())
                ci=st.selectbox("Corriere",ac.index,format_func=lambda i:ac.loc[i,"nome"]); si=st.selectbox("Struttura",ast.index,format_func=lambda i:ast.loc[i,"nome"])
                tipo=st.selectbox("Tipo",["CONSEGNA","RITIRO"]); kit=st.text_input("Kit / materiale"); colli=st.number_input("Colli",0,step=1); note=st.text_area("Note")
                if st.form_submit_button("Crea missione",type="primary"):
                    _new=sb().table("missioni_corrieri").insert({"codice":codice,"data_missione":str(dm),"corriere_id":int(ac.loc[ci,"id"]),"struttura_id":int(ast.loc[si,"id"]),"tipo":tipo,"kit_codice":kit.strip(),"colli":int(colli),"note":note}).execute()
                    if kit.strip():
                        _existing=sb().table("kit_logistici").select("*").eq("codice",kit.strip()).limit(1).execute().data or []
                        if _existing: _kid=int(_existing[0]["id"]); _old=str(_existing[0].get("stato") or "IN_MAGAZZINO")
                        else:
                            _k=sb().table("kit_logistici").insert({"codice":kit.strip(),"stato":"IN_MAGAZZINO"}).execute().data[0]; _kid=int(_k["id"]); _old="IN_MAGAZZINO"
                        _mid=int(_new.data[0]["id"]); _newst="ASSEGNATO"
                        sb().table("kit_logistici").update({"stato":_newst,"missione_id":_mid,"corriere_id":int(ac.loc[ci,"id"]),"struttura_id":int(ast.loc[si,"id"])}).eq("id",_kid).execute()
                        sb().table("movimenti_kit_corrieri").insert({"kit_id":_kid,"missione_id":_mid,"corriere_id":int(ac.loc[ci,"id"]),"struttura_id":int(ast.loc[si,"id"]),"movimento":"ASSEGNAZIONE","stato_precedente":_old,"stato_nuovo":_newst,"utente":str(st.session_state.get("user",""))}).execute()
                    st.rerun()
    with tabs[3]:
        st.subheader("Corrieri")
        with st.form("new_courier"):
            n=st.text_input("Nome"); tel=st.text_input("Telefono")
            if st.form_submit_button("Aggiungi") and n: sb().table("corrieri").insert({"nome":n,"telefono":tel}).execute(); st.rerun()
        st.dataframe(cour,use_container_width=True,hide_index=True)
        st.divider()
        st.subheader("🏥 Anagrafica strutture")
        st.caption("Crea e consulta le strutture utilizzate per consegne e ritiri.")
        with st.form("new_structure"):
            _sc1,_sc2=st.columns(2)
            _sn=_sc1.text_input("Nome struttura *")
            _sa=_sc2.text_input("Indirizzo *")
            _sr=_sc1.text_input("Referente")
            _st=_sc2.text_input("Telefono")
            _snote=st.text_area("Note consegna / accesso")
            _sactive=st.checkbox("Struttura attiva",value=True)
            if st.form_submit_button("➕ Crea struttura",type="primary"):
                if not _sn.strip() or not _sa.strip():
                    st.error("Nome struttura e indirizzo sono obbligatori.")
                else:
                    sb().table("strutture_logistiche").insert({"nome":_sn.strip(),"indirizzo":_sa.strip(),"referente":_sr.strip(),"telefono":_st.strip(),"note_consegna":_snote.strip(),"attiva":_sactive}).execute()
                    st.success("Struttura creata."); st.rerun()
        if stru.empty:
            st.info("Nessuna struttura registrata.")
        else:
            st.dataframe(stru[[x for x in ["id","nome","indirizzo","referente","telefono","note_consegna","attiva"] if x in stru]],use_container_width=True,hide_index=True)
            _si=st.selectbox("Modifica struttura",stru.index,format_func=lambda i:f'{stru.loc[i,"nome"]} · {stru.loc[i].get("indirizzo","")}',key="edit_structure_select")
            _srw=stru.loc[_si]
            with st.form("edit_structure"):
                _en=st.text_input("Nome",value=str(_srw.get("nome") or ""))
                _ea=st.text_input("Indirizzo",value=str(_srw.get("indirizzo") or ""))
                _er=st.text_input("Referente",value=str(_srw.get("referente") or ""))
                _et=st.text_input("Telefono",value=str(_srw.get("telefono") or ""))
                _eno=st.text_area("Note consegna / accesso",value=str(_srw.get("note_consegna") or ""))
                _eact=st.checkbox("Attiva",value=bool(_srw.get("attiva",True)))
                if st.form_submit_button("💾 Salva struttura"):
                    sb().table("strutture_logistiche").update({"nome":_en.strip(),"indirizzo":_ea.strip(),"referente":_er.strip(),"telefono":_et.strip(),"note_consegna":_eno.strip(),"attiva":_eact}).eq("id",int(_srw["id"])).execute()
                    st.success("Struttura aggiornata."); st.rerun()
    with tabs[4]:
        st.subheader("📦 Registro movimentazione kit")
        kits=df("kit_logistici"); kmov=df("movimenti_kit_corrieri")
        if kits.empty: st.info("Il registro si popolerà automaticamente dalle nuove missioni con un codice kit.")
        else:
            if "struttura_id" in kits: kits["struttura"]=kits["struttura_id"].map(smap)
            if "corriere_id" in kits: kits["corriere"]=kits["corriere_id"].map(cmap)
            st.dataframe(kits[[x for x in ["codice","descrizione","stato","struttura","corriere","updated_at"] if x in kits]],use_container_width=True,hide_index=True)
        if not kmov.empty:
            st.caption("Storico movimenti")
            st.dataframe(kmov.sort_values("created_at",ascending=False).head(200),use_container_width=True,hide_index=True)
        ritirati=kits[kits["stato"]=="RITIRATO"] if (not kits.empty and "stato" in kits) else pd.DataFrame()
        st.divider()
        st.subheader("🏭 Rientri da confermare in magazzino")
        if ritirati.empty:
            st.success("Nessun kit ritirato in attesa di riscontro fisico.")
        else:
            ri=st.selectbox("Kit fisicamente rientrato",ritirati.index,format_func=lambda i:f'{ritirati.loc[i,"codice"]} · {ritirati.loc[i].get("struttura","")}',key="warehouse_return")
            rr=ritirati.loc[ri]
            st.warning("Confermare solo dopo aver verificato fisicamente il kit/materiale in magazzino.")
            if st.button("✅ Conferma rientro in magazzino",type="primary",key="confirm_warehouse_return"):
                sb().table("kit_logistici").update({"stato":"IN_MAGAZZINO","struttura_id":None,"missione_id":None,"corriere_id":None}).eq("id",int(rr["id"])).execute()
                sb().table("movimenti_kit_corrieri").insert({"kit_id":int(rr["id"]),"missione_id":int(rr["missione_id"]) if pd.notna(rr.get("missione_id")) else None,"corriere_id":int(rr["corriere_id"]) if pd.notna(rr.get("corriere_id")) else None,"struttura_id":int(rr["struttura_id"]) if pd.notna(rr.get("struttura_id")) else None,"movimento":"RIENTRO_MAGAZZINO","stato_precedente":"RITIRATO","stato_nuovo":"IN_MAGAZZINO","utente":str(st.session_state.get("user","")),"note":"Rientro fisico verificato e confermato dal personale autorizzato"}).execute()
                st.success("Rientro fisico registrato."); st.rerun()
    with tabs[5]:
        mov=mis.copy()
        if not mov.empty:
            mov["movimento"]=mov["tipo"].map({"CONSEGNA":"USCITA","RITIRO":"RIENTRO"})
            out=io.BytesIO()
            with pd.ExcelWriter(out,engine="xlsxwriter") as w:
                mov.to_excel(w,index=False,sheet_name="Missioni")
                tim.to_excel(w,index=False,sheet_name="Timbrature")
                df("kit_logistici").to_excel(w,index=False,sheet_name="Registro_Kit")
                df("movimenti_kit_corrieri").to_excel(w,index=False,sheet_name="Movimenti_Kit")
                cour.to_excel(w,index=False,sheet_name="Corrieri")
                stru.to_excel(w,index=False,sheet_name="Strutture")
                mov[mov["tipo"]=="CONSEGNA"].to_excel(w,index=False,sheet_name="Kit_Usciti")
                mov[mov["tipo"]=="RITIRO"].to_excel(w,index=False,sheet_name="Kit_Rientrati")
            st.download_button("⬇️ Excel movimentazione corrieri",out.getvalue(),"OrthoFlow_Report_Corrieri.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
else:
    uid=st.session_state.get("utente_id")
    link=cour[cour["user_id"].astype(str)==str(uid)] if (not cour.empty and "user_id" in cour) else pd.DataFrame()
    if link.empty: st.warning("Profilo corriere non collegato al tuo utente. La Direzione deve collegarlo."); st.stop()
    cid=int(link.iloc[0]["id"])
    mis=pd.DataFrame(sb().table("missioni_corrieri").select("*").eq("corriere_id",cid).order("data_missione",desc=True).limit(200).execute().data or [])
    if mis.empty: st.info("Nessuna missione assegnata."); st.stop()
    mis["struttura"]=mis["struttura_id"].map(smap)
    st.dataframe(mis[[x for x in ["codice","data_missione","tipo","struttura","kit_codice","stato"] if x in mis]],use_container_width=True,hide_index=True)
    sel=st.selectbox("Apri missione",mis.index,format_func=lambda i:f'{mis.loc[i,"codice"]} · {mis.loc[i,"struttura"]}')
    r=mis.loc[sel]; st.subheader(f'{r["codice"]} · {r["tipo"]}'); st.write(f'**{r["struttura"]}** · Kit: {r.get("kit_codice") or "-"}')
    st.caption("La posizione viene rilevata automaticamente dal telefono e non può essere modificata manualmente.")
    _geo_key=f"geo_request_{int(r.id)}"
    if st.button("📍 Acquisisci posizione e timbra",type="primary",key=f"stamp_{int(r.id)}"):
        st.session_state[_geo_key]=True
        st.rerun()
    if st.session_state.get(_geo_key):
        st.info("📡 Consenti l'accesso alla posizione quando il telefono lo richiede.")
        _loc=get_geolocation(component_key=f"gps_{int(r.id)}")
        if _loc and isinstance(_loc,dict) and _loc.get("error"):
            _err=_loc.get("error") or {}
            if int(_err.get("code",0) or 0)==1:
                st.error("Posizione non autorizzata. Abilita la localizzazione per OrthoFlow nelle impostazioni del browser e riprova.")
            else:
                st.error("Non riesco ad acquisire la posizione GPS. Riprova in un punto con migliore ricezione.")
            st.session_state[_geo_key]=False
        elif _loc and isinstance(_loc,dict) and _loc.get("coords"):
            _coords=_loc["coords"]; _lat=float(_coords["latitude"]); _lon=float(_coords["longitude"]); _acc=float(_coords.get("accuracy") or 0)
            sb().table("timbrature_corrieri").insert({"missione_id":int(r.id),"corriere_id":cid,"struttura_id":int(r.struttura_id),"tipo":"ARRIVO","latitudine":_lat,"longitudine":_lon,"precisione_m":_acc or None}).execute()
            sb().table("missioni_corrieri").update({"stato":"ARRIVATO"}).eq("id",int(r.id)).execute()
            if str(r.get("kit_codice") or "").strip():
                _kk=sb().table("kit_logistici").select("*").eq("codice",str(r.kit_codice).strip()).limit(1).execute().data or []
                if _kk:
                    _old=str(_kk[0].get("stato") or "ASSEGNATO"); _ns="IN_USCITA" if r["tipo"]=="CONSEGNA" else "DA_RITIRARE"
                    sb().table("kit_logistici").update({"stato":_ns,"missione_id":int(r.id),"corriere_id":cid,"struttura_id":int(r.struttura_id)}).eq("id",int(_kk[0]["id"])).execute()
                    sb().table("movimenti_kit_corrieri").insert({"kit_id":int(_kk[0]["id"]),"missione_id":int(r.id),"corriere_id":cid,"struttura_id":int(r.struttura_id),"movimento":"TIMBRATURA_ARRIVO","stato_precedente":_old,"stato_nuovo":_ns,"utente":str(st.session_state.get("user","")),"note":f"GPS automatico · precisione {_acc:.0f} m"}).execute()
            st.session_state[_geo_key]=False
            st.success(f"📍 Posizione acquisita · precisione circa {_acc:.0f} m")
            st.rerun()
    photos=st.file_uploader("📷 Foto consegna/ritiro",type=["jpg","jpeg","png"],accept_multiple_files=True,key=f"ph{r.id}")
    if photos and st.button("Carica foto"):
        for ph in photos:
            path=f'missioni/{r.id}/foto/{ph.name}'; sb().storage.from_("orthoflow-impianti").upload(path,ph.getvalue(),{"content-type":ph.type,"upsert":"true"}); sb().table("foto_missioni").insert({"missione_id":int(r.id),"tipo":str(r.tipo),"storage_path":path}).execute()
        st.success("Foto archiviate.")
    certok=True
    _pickup_signature_status=None
    if r["tipo"]=="RITIRO":
        st.subheader("📑 Certificazione lavaggio / decontaminazione")
        st.caption("Il ritiro deve restare rapido: scegli se la struttura firma oppure se il materiale viene ritirato senza firma.")
        _pickup_signature_status=st.radio("Esito firma struttura",["CON_FIRMA","SENZA_FIRMA"],format_func=lambda x:"✍️ Ritiro con firma" if x=="CON_FIRMA" else "⚠️ Ritiro senza firma",horizontal=True,key=f"sig_status_{r.id}")
        if _pickup_signature_status=="CON_FIRMA":
            cert=st.file_uploader("Allega certificazione",type=["pdf","jpg","jpeg","png"],key=f"cert{r.id}")
            firm=st.text_input("Nome e cognome firmatario",key=f"firm{r.id}"); ruolo=st.text_input("Ruolo firmatario",key=f"role{r.id}")
            st.markdown("**✍️ Firma del referente**")
            sign=st_canvas(fill_color="rgba(255,255,255,0)",stroke_width=3,stroke_color="#000000",background_color="#FFFFFF",height=180,width=500,drawing_mode="freedraw",key=f"signature_{int(r.id)}")
            _has_signature=bool(sign.json_data and sign.json_data.get("objects"))
            if cert and firm.strip() and ruolo.strip() and _has_signature and st.button("🔐 Firma e archivia certificazione",type="primary",key=f"archive_cert_{r.id}"):
                path=f'missioni/{r.id}/documenti/decontaminazione_{cert.name}'
                sb().storage.from_("orthoflow-impianti").upload(path,cert.getvalue(),{"content-type":cert.type,"upsert":"true"})
                _img=Image.fromarray(sign.image_data.astype("uint8"),"RGBA"); _buf=io.BytesIO(); _img.save(_buf,format="PNG")
                _sigpath=f'missioni/{r.id}/documenti/firma_decontaminazione.png'
                sb().storage.from_("orthoflow-impianti").upload(_sigpath,_buf.getvalue(),{"content-type":"image/png","upsert":"true"})
                sb().table("documenti_missioni").insert({"missione_id":int(r.id),"tipo_documento":"CERTIFICAZIONE_LAVAGGIO_DECONTAMINAZIONE","storage_path":path,"firma_storage_path":_sigpath,"nome_firmatario":firm.strip(),"ruolo_firmatario":ruolo.strip(),"firmato_at":datetime.now(timezone.utc).isoformat()}).execute()
                sb().table("missioni_corrieri").update({"esito_firma_ritiro":"CON_FIRMA","nota_firma_ritiro":None}).eq("id",int(r.id)).execute()
                st.success("Certificazione firmata e archiviata."); st.rerun()
            certok=bool(sb().table("documenti_missioni").select("id").eq("missione_id",int(r.id)).eq("tipo_documento","CERTIFICAZIONE_LAVAGGIO_DECONTAMINAZIONE").limit(1).execute().data)
            if not certok: st.info("Per usare 'Ritiro con firma', archivia prima certificazione e firma.")
        else:
            _no_sig_note=st.text_input("Nota facoltativa",placeholder="Es. referente non disponibile / struttura non firma",key=f"nosig_note_{r.id}")
            certok=True
            st.warning("Il ritiro potrà essere completato e verrà registrato chiaramente come SENZA FIRMA.")
    if st.button("✅ Conferma operazione",type="primary",disabled=not certok):
        _mission_update={"stato":"COMPLETATA"}
        if r["tipo"]=="RITIRO":
            _mission_update["esito_firma_ritiro"]=_pickup_signature_status
            _mission_update["nota_firma_ritiro"]=_no_sig_note.strip() if _pickup_signature_status=="SENZA_FIRMA" else None
        sb().table("missioni_corrieri").update(_mission_update).eq("id",int(r.id)).execute()
        if str(r.get("kit_codice") or "").strip():
            _kk=sb().table("kit_logistici").select("*").eq("codice",str(r.kit_codice).strip()).limit(1).execute().data or []
            if _kk:
                _old=str(_kk[0].get("stato") or ""); _ns="CONSEGNATO" if r["tipo"]=="CONSEGNA" else "RITIRATO"
                sb().table("kit_logistici").update({"stato":_ns,"missione_id":int(r.id),"corriere_id":cid,"struttura_id":int(r.struttura_id)}).eq("id",int(_kk[0]["id"])).execute()
                sb().table("movimenti_kit_corrieri").insert({"kit_id":int(_kk[0]["id"]),"missione_id":int(r.id),"corriere_id":cid,"struttura_id":int(r.struttura_id),"movimento":"CONSEGNA" if r["tipo"]=="CONSEGNA" else "RITIRO","stato_precedente":_old,"stato_nuovo":_ns,"utente":str(st.session_state.get("user",""))}).execute()
        st.rerun()

st.divider()
st.subheader("🧩 Reintegro fisico Kit")
st.caption("Dopo il Carico Mobile, assegna il nuovo componente ricevuto al kit corretto. Il lotto nuovo entra nella composizione aggiornata del kit.")
if manager:
 kits=pd.DataFrame(sb.table("kit_logistici").select("*").execute().data or [])
 drows=pd.DataFrame(sb.table("ddt_righe").select("*").execute().data or [])
 dheads=pd.DataFrame(sb.table("ddt").select("id,numero_ddt,data_ddt").execute().data or [])
 pending=pd.DataFrame(sb.table("reintegri_kit").select("*").in_("stato",["DA_REINTEGRARE","PARZIALE"]).execute().data or [])
 if not pending.empty:
  pending=pending.merge(kits[["id","codice"]].rename(columns={"id":"kit_id","codice":"kit"}),on="kit_id",how="left")
  st.dataframe(pending[[x for x in ["id","kit","codice","lotto_consumato","quantita_richiesta","quantita_reintegrata","stato"] if x in pending]],use_container_width=True,hide_index=True)
  rid=st.selectbox("Componente da reintegrare",pending["id"].astype(int).tolist(),format_func=lambda x:f'#{x} · {pending[pending["id"]==x].iloc[0]["kit"]} · {pending[pending["id"]==x].iloc[0]["codice"]}')
  rr=pending[pending["id"]==rid].iloc[0]
  cand=drows[drows["codice"].astype(str).str.strip().str.upper()==str(rr["codice"]).strip().upper()].copy()
  if not cand.empty and not dheads.empty: cand=cand.merge(dheads.rename(columns={"id":"ddt_id"}),on="ddt_id",how="left")
  if cand.empty: st.warning("Il codice non risulta ancora ricevuto tramite DDT Carico Mobile.")
  else:
   did=st.selectbox("Pezzo ricevuto da inserire nel kit",cand["id"].astype(int).tolist(),format_func=lambda x:(lambda z:f'{z.get("codice")} · lotto {z.get("lotto")} · qta {z.get("quantita")} · DDT {z.get("numero_ddt","")}')(cand[cand["id"]==x].iloc[0]))
   if st.button("✅ Inserisci nuovo pezzo nel Kit",type="primary"):
    dr=cand[cand["id"]==did].iloc[0]; q=min(float(dr.get("quantita") or 0),float(rr.get("quantita_richiesta") or 0)-float(rr.get("quantita_reintegrata") or 0))
    if q<=0: st.error("Quantità disponibile/non richiesta non valida.")
    else:
     sb.table("componenti_kit").insert({"kit_id":int(rr["kit_id"]),"codice":str(dr["codice"]),"lotto":None if pd.isna(dr.get("lotto")) else str(dr.get("lotto")),"scadenza":None if pd.isna(dr.get("scadenza")) else str(dr.get("scadenza")),"quantita":q,"ddt_riga_id":int(did)}).execute()
     newq=float(rr.get("quantita_reintegrata") or 0)+q; req=float(rr.get("quantita_richiesta") or 0)
     sb.table("reintegri_kit").update({"ddt_riga_id":int(did),"lotto_nuovo":None if pd.isna(dr.get("lotto")) else str(dr.get("lotto")),"scadenza_nuova":None if pd.isna(dr.get("scadenza")) else str(dr.get("scadenza")),"quantita_reintegrata":newq,"stato":"REINTEGRATO" if newq>=req else "PARZIALE","utente":str(st.session_state.get("user")),"reintegrato_at":datetime.now(timezone.utc).isoformat() if newq>=req else None}).eq("id",int(rid)).execute()
     st.success("Kit aggiornato con il nuovo lotto ricevuto."); st.rerun()
 else: st.info("Nessun componente Kit in attesa di reintegro.")
