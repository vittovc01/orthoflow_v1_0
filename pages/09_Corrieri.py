import streamlit as st
import pandas as pd
from datetime import date
from supabase import create_client
st.set_page_config(page_title="Corrieri · OrthoFlow",page_icon="🚐",layout="wide")

if not st.session_state.get("user"): st.stop()
_ofp=set(st.session_state.get("permessi",[]) or [])
_ofd=str(st.session_state.get("ruolo",""))=="Admin" or "DIREZIONE" in _ofp
if not _ofd and not (_ofp & set(["LOGISTICA","CORRIERE"])):
    st.error("Non sei autorizzato ad accedere a questa area."); st.stop()
if not st.session_state.get("user"): st.switch_page("pages/99_Login.py")
@st.cache_resource
def sb():
    url=st.secrets.get("SUPABASE_URL")
    key=st.secrets.get("SUPABASE_SERVICE_KEY") or st.secrets.get("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_KEY")
    if not url or not key:
        st.error("Supabase non configurato nei Secrets."); st.stop()
    return create_client(str(url).rstrip("/"),str(key))
st.title("🚐 Corrieri & Missioni")
st.caption("Consegne, ritiri, timbrature GPS, foto e certificazioni.")
tab1,tab2,tab3=st.tabs(["📋 Missioni","➕ Nuova missione","⚙️ Anagrafiche"])
with tab3:
    a,b=st.columns(2)
    with a:
        st.subheader("Corrieri")
        with st.form("new_courier"):
            nome=st.text_input("Nome corriere"); tel=st.text_input("Telefono")
            if st.form_submit_button("Aggiungi corriere") and nome: sb().table("corrieri").insert({"nome":nome,"telefono":tel}).execute(); st.rerun()
        st.dataframe(pd.DataFrame(sb().table("corrieri").select("*").eq("attivo",True).execute().data or []),use_container_width=True,hide_index=True)
    with b:
        st.subheader("Strutture")
        with st.form("new_structure"):
            nome=st.text_input("Nome struttura"); ind=st.text_input("Indirizzo"); ref=st.text_input("Referente")
            if st.form_submit_button("Aggiungi struttura") and nome: sb().table("strutture_logistiche").insert({"nome":nome,"indirizzo":ind,"referente":ref}).execute(); st.rerun()
        st.dataframe(pd.DataFrame(sb().table("strutture_logistiche").select("*").eq("attiva",True).execute().data or []),use_container_width=True,hide_index=True)
cour=pd.DataFrame(sb().table("corrieri").select("*").eq("attivo",True).execute().data or [])
stru=pd.DataFrame(sb().table("strutture_logistiche").select("*").eq("attiva",True).execute().data or [])
with tab2:
    if cour.empty or stru.empty: st.info("Inserisci prima almeno un corriere e una struttura.")
    else:
        with st.form("new_mission"):
            codice=st.text_input("Codice missione",value=f"M-{date.today().strftime('%Y%m%d')}-")
            dm=st.date_input("Data",value=date.today()); ci=st.selectbox("Corriere",cour.index,format_func=lambda i:cour.loc[i,"nome"])
            si=st.selectbox("Struttura",stru.index,format_func=lambda i:stru.loc[i,"nome"]); tipo=st.selectbox("Tipo",["CONSEGNA","RITIRO"])
            kit=st.text_input("Kit / materiale"); colli=st.number_input("Colli",min_value=0,step=1); note=st.text_area("Note")
            if st.form_submit_button("Crea missione",type="primary"):
                sb().table("missioni_corrieri").insert({"codice":codice,"data_missione":str(dm),"corriere_id":int(cour.loc[ci,"id"]),"struttura_id":int(stru.loc[si,"id"]),"tipo":tipo,"kit_codice":kit,"colli":int(colli),"note":note}).execute(); st.success("Missione creata."); st.rerun()
with tab1:
    mis=pd.DataFrame(sb().table("missioni_corrieri").select("*").order("data_missione",desc=True).limit(200).execute().data or [])
    if mis.empty: st.info("Nessuna missione.")
    else:
        cmap=dict(zip(cour.id,cour.nome)) if not cour.empty else {}; smap=dict(zip(stru.id,stru.nome)) if not stru.empty else {}
        mis["corriere"]=mis["corriere_id"].map(cmap); mis["struttura"]=mis["struttura_id"].map(smap)
        st.dataframe(mis[["codice","data_missione","tipo","corriere","struttura","kit_codice","colli","stato"]],use_container_width=True,hide_index=True)
        sel=st.selectbox("Apri missione",mis.index,format_func=lambda i:f'{mis.loc[i,"codice"]} · {mis.loc[i,"struttura"]}')
        r=mis.loc[sel]; st.subheader(f'{r["codice"]} · {r["tipo"]}'); st.write(f'**{r["struttura"]}** · {r["corriere"]} · Kit: {r.get("kit_codice") or "-"}')
        lat=st.number_input("Latitudine GPS",format="%.6f"); lon=st.number_input("Longitudine GPS",format="%.6f")
        if st.button("📍 Timbra arrivo"):
            sb().table("timbrature_corrieri").insert({"missione_id":int(r.id),"corriere_id":int(r.corriere_id),"struttura_id":int(r.struttura_id),"tipo":"ARRIVO","latitudine":lat or None,"longitudine":lon or None}).execute()
            sb().table("missioni_corrieri").update({"stato":"ARRIVATO"}).eq("id",int(r.id)).execute(); st.success("Arrivo registrato."); st.rerun()
        photos=st.file_uploader("📷 Foto consegna/ritiro",type=["jpg","jpeg","png"],accept_multiple_files=True,key=f"ph{r.id}")
        if photos and st.button("Carica foto"):
            for ph in photos:
                path=f'missioni/{r.id}/foto/{ph.name}'; sb().storage.from_("orthoflow-impianti").upload(path,ph.getvalue(),{"content-type":ph.type,"upsert":"true"})
                sb().table("foto_missioni").insert({"missione_id":int(r.id),"tipo":str(r.tipo),"storage_path":path}).execute()
            st.success("Foto archiviate.")
        if r["tipo"]=="RITIRO":
            cert=st.file_uploader("📑 Certificazione lavaggio/decontaminazione (obbligatoria)",type=["pdf","jpg","jpeg","png"],key=f"cert{r.id}")
            firm=st.text_input("Nome firmatario",key=f"firm{r.id}"); ruolo=st.text_input("Ruolo firmatario",key=f"role{r.id}")
            if cert and st.button("Archivia certificazione"):
                path=f'missioni/{r.id}/documenti/decontaminazione_{cert.name}'; sb().storage.from_("orthoflow-impianti").upload(path,cert.getvalue(),{"content-type":cert.type,"upsert":"true"})
                sb().table("documenti_missioni").insert({"missione_id":int(r.id),"tipo_documento":"CERTIFICAZIONE_LAVAGGIO_DECONTAMINAZIONE","storage_path":path,"nome_firmatario":firm,"ruolo_firmatario":ruolo}).execute(); st.success("Certificazione archiviata."); st.rerun()
            certok=bool(sb().table("documenti_missioni").select("id").eq("missione_id",int(r.id)).eq("tipo_documento","CERTIFICAZIONE_LAVAGGIO_DECONTAMINAZIONE").limit(1).execute().data)
        else: certok=True
        if st.button("✅ Conferma operazione",type="primary",disabled=not certok):
            sb().table("missioni_corrieri").update({"stato":"COMPLETATA"}).eq("id",int(r.id)).execute(); st.success("Missione completata."); st.rerun()
