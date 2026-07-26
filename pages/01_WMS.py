import io
from datetime import date, timedelta

import pandas as pd
import qrcode
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="OrthoFlow WMS", page_icon="📦", layout="wide")


def sb():
    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_SERVICE_KEY") or st.secrets.get("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_KEY")
    if not url or not key:
        st.error("Supabase non configurato nei Secrets.")
        st.stop()
    return create_client(str(url).rstrip("/"), str(key))


def user(): return str(st.session_state.get("user", ""))
def role(): return str(st.session_state.get("ruolo", ""))


def require_access():
    if not user():
        st.warning("Accedi prima dalla pagina principale di OrthoFlow.")
        st.stop()
    if role() not in {"Admin", "Magazzino"}:
        st.error("Modulo disponibile per Admin e Magazzino.")
        st.stop()


def table(name, order="id", desc=False):
    try:
        return pd.DataFrame(sb().table(name).select("*").order(order, desc=desc).execute().data or [])
    except Exception as exc:
        st.error(f"Errore lettura {name}: {exc}")
        return pd.DataFrame()


def qr_png(token):
    image = qrcode.make(f"OFWMS:LOC:{token}")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def loc_label(row):
    return f"{row.get('codice_magazzino','')} · {row.get('codice_ubicazione','')}"


def icon(status):
    return {"SCADUTO":"🔴", "URGENTE":"🟠", "ATTENZIONE":"🟡", "MONITORARE":"🔵", "NORMALE":"🟢"}.get(str(status), "⚪")


require_access()
st.title("📦 OrthoFlow WMS")
st.caption("Ubicazioni, QR, trasferimenti e recupero scadenze FEFO.")
section = st.sidebar.radio("WMS", ["Dashboard", "Ubicazioni", "Scanner", "Trasferimenti", "Scadenze", "Movimenti"])

if section == "Dashboard":
    locations = table("ubicazioni_magazzino")
    stock = table("giacenze_ubicazioni")
    expiries = table("v_scadenze_ubicazioni", "scadenza")
    expired = len(expiries[expiries["stato_scadenza"] == "SCADUTO"]) if not expiries.empty else 0
    urgent = len(expiries[expiries["stato_scadenza"] == "URGENTE"]) if not expiries.empty else 0
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Ubicazioni", len(locations))
    c2.metric("Righe ubicate", len(stock))
    c3.metric("Scaduti", expired)
    c4.metric("Entro 30 giorni", urgent)
    if not expiries.empty:
        priority = expiries[expiries["stato_scadenza"].isin(["SCADUTO","URGENTE","ATTENZIONE"])].copy()
        if not priority.empty:
            priority["stato"] = priority["stato_scadenza"].map(lambda x: f"{icon(x)} {x}")
            cols=[c for c in ["stato","codice","descrizione","lotto","scadenza","giorni_scadenza","quantita_disponibile","nome_magazzino","codice_ubicazione"] if c in priority]
            st.dataframe(priority[cols], use_container_width=True, hide_index=True)
        else:
            st.success("Nessuna scadenza critica.")

elif section == "Ubicazioni":
    mags = table("magazzini", "codice_magazzino")
    mag_opts = mags["codice_magazzino"].astype(str).tolist() if not mags.empty else ["MAG1"]
    with st.form("new_location"):
        mag = st.selectbox("Magazzino", mag_opts)
        a,b,c,d = st.columns(4)
        corsia=a.text_input("Corsia","A"); scaffale=b.text_input("Scaffale","01"); ripiano=c.text_input("Ripiano","A"); posizione=d.text_input("Posizione","01")
        codice=st.text_input("Codice ubicazione", f"{corsia}-{scaffale}-{ripiano}-{posizione}")
        descrizione=st.text_input("Descrizione")
        capacita=st.number_input("Capacità indicativa", min_value=0.0, value=0.0)
        save=st.form_submit_button("Crea ubicazione", use_container_width=True)
    if save:
        try:
            sb().table("ubicazioni_magazzino").insert({"codice_magazzino":mag.strip(),"codice_ubicazione":codice.strip().upper(),"corsia":corsia.strip().upper(),"scaffale":scaffale.strip().upper(),"ripiano":ripiano.strip().upper(),"posizione":posizione.strip().upper(),"descrizione":descrizione.strip(),"capacita":capacita or None,"attiva":True}).execute()
            st.success("Ubicazione creata."); st.rerun()
        except Exception as exc: st.error(f"Impossibile creare l'ubicazione: {exc}")
    locations=table("ubicazioni_magazzino", "codice_ubicazione")
    if not locations.empty:
        st.dataframe(locations, use_container_width=True, hide_index=True)
        loc_id=st.selectbox("Etichetta QR", locations["id"].tolist(), format_func=lambda x: loc_label(locations[locations["id"]==x].iloc[0].to_dict()))
        row=locations[locations["id"]==loc_id].iloc[0].to_dict(); data=qr_png(row.get("qr_token"))
        x,y=st.columns([1,3]); x.image(data, width=220)
        y.markdown(f"### {row.get('codice_ubicazione')}\n**Magazzino:** {row.get('codice_magazzino')}  \nCorsia {row.get('corsia')} → Scaffale {row.get('scaffale')} → Ripiano {row.get('ripiano')} → Posizione {row.get('posizione')}")
        y.download_button("Scarica QR", data, file_name=f"QR_{row.get('codice_magazzino')}_{row.get('codice_ubicazione')}.png", mime="image/png")

elif section == "Scanner":
    st.camera_input("Fotocamera", key="wms_camera")
    raw=st.text_input("Codice letto", placeholder="OFWMS:LOC:uuid")
    if raw:
        token=raw.strip().split(":")[-1]
        rows=sb().table("ubicazioni_magazzino").select("*").eq("qr_token",token).limit(1).execute().data or []
        if not rows: st.error("QR non riconosciuto.")
        else:
            row=rows[0]; st.success(f"Ubicazione: {loc_label(row)}")
            stock=pd.DataFrame(sb().table("giacenze_ubicazioni").select("*").eq("ubicazione_id",row["id"]).execute().data or [])
            st.info("Ubicazione vuota.") if stock.empty else st.dataframe(stock, use_container_width=True, hide_index=True)

elif section == "Trasferimenti":
    locations=table("ubicazioni_magazzino", "codice_ubicazione"); stock=table("giacenze_ubicazioni", "updated_at", True)
    if locations.empty or stock.empty: st.info("Servono almeno due ubicazioni e una giacenza ubicata.")
    else:
        stock["label"]=stock.apply(lambda r:f"{r.get('codice')} · Lotto {r.get('lotto')} · Q.tà {r.get('quantita')} · Ub. {r.get('ubicazione_id')}",axis=1)
        with st.form("move"):
            sid=st.selectbox("Prodotto",stock["id"].tolist(),format_func=lambda x:stock.loc[stock["id"]==x,"label"].iloc[0]); row=stock[stock["id"]==sid].iloc[0].to_dict()
            dests=locations[(locations["codice_magazzino"]==row["codice_magazzino"])&(locations["id"]!=row["ubicazione_id"])]
            did=st.selectbox("Destinazione",dests["id"].tolist(),format_func=lambda x:loc_label(dests[dests["id"]==x].iloc[0].to_dict()))
            qty=st.number_input("Quantità",min_value=0.01,max_value=float(row["quantita"]),value=1.0); note=st.text_input("Note")
            go=st.form_submit_button("Conferma spostamento",use_container_width=True)
        if go:
            try:
                sb().rpc("wms_sposta_materiale",{"p_ubicazione_origine_id":int(row["ubicazione_id"]),"p_ubicazione_destinazione_id":int(did),"p_codice":str(row["codice"]),"p_lotto":str(row["lotto"]),"p_origine":str(row.get("origine","")),"p_sterile":bool(row.get("sterile",True)),"p_quantita":float(qty),"p_utente":user(),"p_note":note}).execute()
                st.success("Spostamento registrato."); st.rerun()
            except Exception as exc: st.error(f"Spostamento non eseguito: {exc}")

elif section == "Scadenze":
    horizon=st.select_slider("Orizzonte",options=[30,60,90,180,365],value=90,format_func=lambda x:f"{x} giorni")
    expiries=table("v_scadenze_ubicazioni", "scadenza")
    if expiries.empty: st.info("Nessuna giacenza ubicata.")
    else:
        expiries["scadenza"]=pd.to_datetime(expiries["scadenza"],errors="coerce").dt.date
        filtered=expiries[expiries["scadenza"].notna()&(expiries["scadenza"]<=date.today()+timedelta(days=int(horizon)))].copy()
        filtered=filtered.sort_values(["scadenza","codice_magazzino","corsia","scaffale","ripiano","posizione"])
        if filtered.empty: st.success("Nessun prodotto in scadenza nell'orizzonte selezionato.")
        else:
            filtered["stato"]=filtered["stato_scadenza"].map(lambda x:f"{icon(x)} {x}")
            cols=[c for c in ["stato","codice","descrizione","lotto","scadenza","giorni_scadenza","quantita_disponibile","nome_magazzino","corsia","scaffale","ripiano","posizione","codice_ubicazione"] if c in filtered]
            st.dataframe(filtered[cols],use_container_width=True,hide_index=True)
            st.download_button("Esporta giro scadenze CSV",filtered[cols].to_csv(index=False).encode("utf-8-sig"),file_name=f"giro_scadenze_{date.today()}.csv",mime="text/csv")

elif section == "Movimenti":
    moves=table("movimenti_ubicazioni","data_movimento",True)
    st.info("Nessun movimento registrato.") if moves.empty else st.dataframe(moves,use_container_width=True,hide_index=True)
