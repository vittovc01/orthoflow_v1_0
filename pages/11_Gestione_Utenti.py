import streamlit as st
from orthoflow_branding import configure_page
import pandas as pd
import hashlib
import os
from datetime import datetime, timezone
from supabase import create_client

configure_page(page_title="Utenti & Permessi · OrthoFlow",page_icon="👥",layout="wide")
if not st.session_state.get("user"): st.stop()
perms=set(st.session_state.get("permessi",[]) or [])
if str(st.session_state.get("ruolo",""))!="Admin" and "DIREZIONE" not in perms:
    st.error("Area riservata alla Direzione."); st.stop()

def sb():
    url=st.secrets.get("SUPABASE_URL")
    key=st.secrets.get("SUPABASE_SERVICE_KEY") or st.secrets.get("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_KEY")
    return create_client(str(url).rstrip("/"),str(key))

LABELS={
 "DIREZIONE":"Direzione · accesso completo",
 "OPERATIVITA":"Gestionale operativo",
 "AMMINISTRAZIONE":"Amministrazione",
 "LOGISTICA":"Logistica & Magazzino",
 "AGENTE":"Agente",
 "CORRIERE":"Corriere"
}
st.title("👥 Utenti & Permessi")
st.caption("Approva gli accessi e assegna una o più funzioni. Ogni utente visualizza soltanto le aree autorizzate.")

try:
    agent_names=[str(x['nome']) for x in sb().table('agenti').select('nome').order('nome').execute().data or [] if x.get('nome')]
except Exception:
    agent_names=[]

with st.expander('Crea un nuovo accesso'):
    with st.form('create_managed_account',clear_on_submit=True):
        new_name=st.text_input('Nome e cognome del nuovo utente')
        new_username=st.text_input('Nome utente del nuovo accesso')
        new_password=st.text_input('Password del nuovo accesso',type='password')
        repeated_password=st.text_input('Conferma password del nuovo accesso',type='password')
        new_permissions=st.multiselect('Funzioni del nuovo accesso',list(LABELS),format_func=lambda x:LABELS[x])
        new_agent=st.selectbox('Agente del nuovo accesso',['']+agent_names)
        create_account=st.form_submit_button('Crea e abilita accesso',type='primary')
    if create_account:
        if not new_name.strip() or not new_username.strip() or len(new_password)<8:
            st.error('Inserisci nome, username e una password di almeno 8 caratteri.')
        elif new_password!=repeated_password:
            st.error('Le password non coincidono.')
        elif not new_permissions:
            st.error('Assegna almeno una funzione.')
        elif 'AGENTE' in new_permissions and not new_agent:
            st.error('Collega il nuovo accesso a un agente.')
        else:
            new_role='Admin' if 'DIREZIONE' in new_permissions else ('Amministrazione' if 'AMMINISTRAZIONE' in new_permissions else ('Magazzino' if 'LOGISTICA' in new_permissions else ('Agente' if 'AGENTE' in new_permissions else ('Corriere' if 'CORRIERE' in new_permissions else 'Operatore'))))
            salt=os.urandom(16).hex()
            digest=hashlib.pbkdf2_hmac('sha256',new_password.encode(),salt.encode(),210_000).hex()
            try:
                sb().table('utenti_app').insert({'username':new_username.strip(),'nome_completo':new_name.strip(),
                    'password_salt':salt,'password_hash':digest,'ruolo':new_role,'permessi':new_permissions,
                    'agente_nome':new_agent if 'AGENTE' in new_permissions else '',
                    'stato_accesso':'APPROVATO','attivo':True,'approvato_da':str(st.session_state.get('user','')),
                    'approvato_at':datetime.now(timezone.utc).isoformat()}).execute()
                st.success('Accesso creato e abilitato.');st.rerun()
            except Exception:
                st.error('Accesso non creato. Verifica che il nome utente non sia già presente.')

rows=sb().table("utenti_app").select("id,username,nome_completo,ruolo,permessi,agente_nome,stato_accesso,attivo,ultimo_accesso,created_at").order("created_at",desc=True).execute().data or []
df=pd.DataFrame(rows)
if df.empty: st.info("Nessun utente."); st.stop()
pending=df[df["stato_accesso"].fillna("APPROVATO")=="IN_ATTESA"]
a,b,c=st.columns(3); a.metric("Utenti",len(df)); b.metric("In attesa",len(pending)); c.metric("Attivi",int(df["attivo"].fillna(False).sum()))
if len(pending): st.warning(f"Ci sono {len(pending)} richieste da approvare.")

idx=st.selectbox("Seleziona utente",df.index,format_func=lambda i:f'{df.loc[i].get("nome_completo") or df.loc[i,"username"]} · {df.loc[i,"stato_accesso"]}')
r=df.loc[idx]
st.subheader(r.get("nome_completo") or r["username"])
st.caption(f'Username: {r["username"]} · Ultimo accesso: {r.get("ultimo_accesso") or "mai"}')
current=list(r.get("permessi") or [])
selected=st.multiselect("Funzioni autorizzate",list(LABELS),default=[x for x in current if x in LABELS],format_func=lambda x:LABELS[x])
agent_options=['']+list(dict.fromkeys(agent_names+([str(r.get('agente_nome'))] if r.get('agente_nome') else [])))
assigned_agent=st.selectbox('Agente collegato alle strutture',agent_options,index=agent_options.index(str(r.get('agente_nome') or '')),disabled='AGENTE' not in selected)
col1,col2,col3=st.columns(3)
if col1.button("✅ Approva / Salva",type="primary",use_container_width=True):
    if not selected: st.error("Assegna almeno una funzione.")
    elif 'AGENTE' in selected and not assigned_agent: st.error('Collega l’utente a un agente per assegnare le strutture.')
    else:
        ruolo="Admin" if "DIREZIONE" in selected else ("Amministrazione" if "AMMINISTRAZIONE" in selected else ("Magazzino" if "LOGISTICA" in selected else ("Agente" if "AGENTE" in selected else ("Corriere" if "CORRIERE" in selected else "Operatore"))))
        try:
            sb().table("utenti_app").update({"permessi":selected,"ruolo":ruolo,"agente_nome":assigned_agent,"stato_accesso":"APPROVATO","attivo":True,"approvato_da":str(st.session_state.get("user","")),"approvato_at":datetime.now(timezone.utc).isoformat()}).eq("id",int(r["id"])).execute()
            st.success("Utente approvato e permessi aggiornati."); st.rerun()
        except Exception as exc:
            st.error("Impossibile salvare i permessi. Controlla configurazione e vincoli dell'utente.")
            st.caption(str(exc))
if col2.button("⛔ Sospendi",use_container_width=True):
    if str(r["username"])==str(st.session_state.get("user")): st.error("Non puoi sospendere il tuo stesso account.")
    else:
        sb().table("utenti_app").update({"attivo":False}).eq("id",int(r["id"])).execute(); st.success("Account sospeso."); st.rerun()
if col3.button("❌ Rifiuta richiesta",use_container_width=True):
    if str(r["username"])==str(st.session_state.get("user")): st.error("Operazione non consentita sul tuo account.")
    else:
        sb().table("utenti_app").update({"stato_accesso":"RIFIUTATO","attivo":False,"permessi":[]}).eq("id",int(r["id"])).execute(); st.rerun()

st.divider()
st.subheader("🚐 Gestione dati corrieri")
try:
    cor=pd.DataFrame(sb().table("corrieri").select("*").order("nome").execute().data or [])
except Exception:
    cor=pd.DataFrame()
if cor.empty:
    st.info("Nessun corriere registrato.")
else:
    ci=st.selectbox("Seleziona corriere da modificare",cor.index,format_func=lambda i:str(cor.loc[i].get("nome","")),key="manage_courier")
    cr=cor.loc[ci]
    with st.form("edit_courier"):
        cn=st.text_input("Nome corriere",value=str(cr.get("nome") or ""))
        ct=st.text_input("Telefono corriere",value=str(cr.get("telefono") or ""))
        cuid=st.selectbox("Collega a utente",[""]+df["id"].astype(str).tolist(),index=([""]+df["id"].astype(str).tolist()).index(str(cr.get("user_id"))) if str(cr.get("user_id")) in df["id"].astype(str).tolist() else 0,format_func=lambda x:"— Nessun utente —" if not x else str(df.loc[df["id"].astype(str)==x,"username"].iloc[0]))
        active=st.checkbox("Corriere attivo",value=bool(cr.get("attivo",True)))
        if st.form_submit_button("💾 Salva corriere",type="primary"):
            sb().table("corrieri").update({"nome":cn.strip(),"telefono":ct.strip(),"user_id":int(cuid) if cuid else None,"attivo":active}).eq("id",int(cr["id"])).execute(); st.success("Corriere aggiornato."); st.rerun()
    if st.button("🗑️ Elimina corriere",key="delete_courier"):
        used=sb().table("missioni_corrieri").select("id").eq("corriere_id",int(cr["id"])).limit(1).execute().data or []
        if used: st.error("Il corriere ha missioni registrate: per mantenere lo storico disattivalo invece di eliminarlo.")
        else: sb().table("corrieri").delete().eq("id",int(cr["id"])).execute(); st.rerun()

st.divider()
st.subheader("🗂️ Gestione completa dati Corrieri")
st.caption("Area Direzione: modifica o elimina missioni, timbrature GPS, foto/documenti e movimenti kit creati nel flusso corrieri.")
_tables=["missioni_corrieri","timbrature_corrieri","foto_missioni","documenti_missioni","kit_logistici","movimenti_kit_corrieri","strutture_logistiche"]
_tab=st.selectbox("Archivio da gestire",_tables,format_func=lambda x:{
"missioni_corrieri":"Missioni","timbrature_corrieri":"Timbrature GPS","foto_missioni":"Foto missioni","documenti_missioni":"Documenti / certificazioni","kit_logistici":"Kit logistici","movimenti_kit_corrieri":"Movimenti kit","strutture_logistiche":"Strutture"}[x],key="courier_data_table")
try:
    _data=pd.DataFrame(sb().table(_tab).select("*").order("id",desc=True).limit(2000).execute().data or [])
except Exception as exc:
    _data=pd.DataFrame(); st.error(str(exc))
if _data.empty:
    st.info("Nessun record presente.")
else:
    st.dataframe(_data,use_container_width=True,hide_index=True)
    _rid=st.selectbox("Seleziona ID",_data["id"].tolist(),key="courier_record_id")
    _rec=_data[_data["id"]==_rid].iloc[0]
    st.markdown("**Modifica record**")
    _editable=[x for x in _data.columns if x not in ("id","created_at","updated_at")]
    _changes={}
    _cols=st.columns(2)
    for _n,_col in enumerate(_editable):
        _val=_rec.get(_col)
        if _col in ("attivo","attiva"):
            _changes[_col]=_cols[_n%2].checkbox(_col,value=bool(_val),key=f"edit_{_tab}_{_rid}_{_col}")
        elif _col in ("colli","corriere_id","struttura_id","missione_id","kit_id","user_id"):
            _txt=_cols[_n%2].text_input(_col,value="" if pd.isna(_val) else str(int(_val)),key=f"edit_{_tab}_{_rid}_{_col}")
            _changes[_col]=int(_txt) if _txt.strip() else None
        else:
            _changes[_col]=_cols[_n%2].text_input(_col,value="" if pd.isna(_val) else str(_val),key=f"edit_{_tab}_{_rid}_{_col}")
    _b1,_b2=st.columns(2)
    if _b1.button("💾 Salva modifiche",type="primary",use_container_width=True,key=f"save_{_tab}_{_rid}"):
        try:
            sb().table(_tab).update(_changes).eq("id",int(_rid)).execute()
            st.success(f"ID {_rid} aggiornato."); st.rerun()
        except Exception as exc: st.error(f"Modifica non riuscita: {exc}")
    _confirm=_b2.checkbox("Confermo eliminazione definitiva",key=f"confirm_del_{_tab}_{_rid}")
    if st.button("🗑️ Elimina ID selezionato",disabled=not _confirm,key=f"del_{_tab}_{_rid}"):
        try:
            if _tab=="missioni_corrieri":
                _assets=[]
                for _asset_table in ("foto_missioni","documenti_missioni"):
                    _ar=sb().table(_asset_table).select("*").eq("missione_id",int(_rid)).execute().data or []
                    for _a in _ar:
                        for _field in ("storage_path","firma_storage_path"):
                            if _a.get(_field): _assets.append(_a[_field])
                if _assets: sb().storage.from_("orthoflow-impianti").remove(list(dict.fromkeys(_assets)))
                sb().rpc("elimina_missione_corriere_completa",{"p_missione_id":int(_rid)}).execute()
            elif _tab in ("foto_missioni","documenti_missioni"):
                _assets=[_rec.get("storage_path"),_rec.get("firma_storage_path")]
                _assets=[x for x in _assets if x and not pd.isna(x)]
                if _assets: sb().storage.from_("orthoflow-impianti").remove(_assets)
                sb().table(_tab).delete().eq("id",int(_rid)).execute()
            elif _tab=="kit_logistici":
                sb().table("movimenti_kit_corrieri").delete().eq("kit_id",int(_rid)).execute(); sb().table(_tab).delete().eq("id",int(_rid)).execute()
            else:
                sb().table(_tab).delete().eq("id",int(_rid)).execute()
            st.success(f"ID {_rid} eliminato."); st.rerun()
        except Exception as exc: st.error(f"Eliminazione non riuscita: {exc}")

st.divider()
show=df.copy()
show["permessi"]=show["permessi"].apply(lambda x:", ".join(x or []))
st.dataframe(show[["nome_completo","username","stato_accesso","attivo","permessi","ultimo_accesso"]],use_container_width=True,hide_index=True)
