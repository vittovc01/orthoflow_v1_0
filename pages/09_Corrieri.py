import io
from datetime import date
import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Controllo Corrieri · OrthoFlow",page_icon="🚐",layout="wide")
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
    tabs=st.tabs(["🛰️ Controllo live","📋 Missioni","➕ Nuova missione","⚙️ Anagrafiche","📊 Report Excel"])
    with tabs[0]:
        if tim.empty: st.info("Nessuna timbratura.")
        else:
            t=tim.copy(); t["corriere"]=t["corriere_id"].map(cmap); t["struttura"]=t["struttura_id"].map(smap)
            cols=[x for x in ["created_at","tipo","corriere","struttura","latitudine","longitudine","precisione_m"] if x in t]
            st.dataframe(t[cols].head(100),use_container_width=True,hide_index=True)
            last=t.iloc[0]; st.success(f'Ultima timbratura: {last.get("corriere","")} · {last.get("struttura","")} · {last.get("created_at","")}')
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
                    sb().table("missioni_corrieri").insert({"codice":codice,"data_missione":str(dm),"corriere_id":int(ac.loc[ci,"id"]),"struttura_id":int(ast.loc[si,"id"]),"tipo":tipo,"kit_codice":kit,"colli":int(colli),"note":note}).execute(); st.rerun()
    with tabs[3]:
        st.subheader("Corrieri")
        with st.form("new_courier"):
            n=st.text_input("Nome"); tel=st.text_input("Telefono")
            if st.form_submit_button("Aggiungi") and n: sb().table("corrieri").insert({"nome":n,"telefono":tel}).execute(); st.rerun()
        st.dataframe(cour,use_container_width=True,hide_index=True)
        st.subheader("Strutture"); st.dataframe(stru,use_container_width=True,hide_index=True)
    with tabs[4]:
        mov=mis.copy()
        if not mov.empty:
            mov["movimento"]=mov["tipo"].map({"CONSEGNA":"USCITA","RITIRO":"RIENTRO"})
            out=io.BytesIO()
            with pd.ExcelWriter(out,engine="xlsxwriter") as w:
                mov.to_excel(w,index=False,sheet_name="Missioni")
                tim.to_excel(w,index=False,sheet_name="Timbrature")
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
    lat=st.number_input("Latitudine GPS",format="%.6f"); lon=st.number_input("Longitudine GPS",format="%.6f")
    if st.button("📍 Timbra arrivo"):
        sb().table("timbrature_corrieri").insert({"missione_id":int(r.id),"corriere_id":cid,"struttura_id":int(r.struttura_id),"tipo":"ARRIVO","latitudine":lat or None,"longitudine":lon or None}).execute()
        sb().table("missioni_corrieri").update({"stato":"ARRIVATO"}).eq("id",int(r.id)).execute(); st.rerun()
    photos=st.file_uploader("📷 Foto consegna/ritiro",type=["jpg","jpeg","png"],accept_multiple_files=True,key=f"ph{r.id}")
    if photos and st.button("Carica foto"):
        for ph in photos:
            path=f'missioni/{r.id}/foto/{ph.name}'; sb().storage.from_("orthoflow-impianti").upload(path,ph.getvalue(),{"content-type":ph.type,"upsert":"true"}); sb().table("foto_missioni").insert({"missione_id":int(r.id),"tipo":str(r.tipo),"storage_path":path}).execute()
        st.success("Foto archiviate.")
    certok=True
    if r["tipo"]=="RITIRO":
        cert=st.file_uploader("📑 Certificazione lavaggio/decontaminazione (obbligatoria)",type=["pdf","jpg","jpeg","png"],key=f"cert{r.id}")
        firm=st.text_input("Nome firmatario"); ruolo=st.text_input("Ruolo firmatario")
        if cert and st.button("Archivia certificazione"):
            path=f'missioni/{r.id}/documenti/decontaminazione_{cert.name}'; sb().storage.from_("orthoflow-impianti").upload(path,cert.getvalue(),{"content-type":cert.type,"upsert":"true"}); sb().table("documenti_missioni").insert({"missione_id":int(r.id),"tipo_documento":"CERTIFICAZIONE_LAVAGGIO_DECONTAMINAZIONE","storage_path":path,"nome_firmatario":firm,"ruolo_firmatario":ruolo}).execute(); st.rerun()
        certok=bool(sb().table("documenti_missioni").select("id").eq("missione_id",int(r.id)).eq("tipo_documento","CERTIFICAZIONE_LAVAGGIO_DECONTAMINAZIONE").limit(1).execute().data)
    if st.button("✅ Conferma operazione",type="primary",disabled=not certok):
        sb().table("missioni_corrieri").update({"stato":"COMPLETATA"}).eq("id",int(r.id)).execute(); st.rerun()
