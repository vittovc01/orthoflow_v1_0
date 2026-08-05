import io
import re
import zipfile
from datetime import date, timedelta

import pandas as pd
import qrcode
import streamlit as st
from supabase import create_client

try:
    from streamlit_qrcode_scanner import qrcode_scanner
except Exception:
    qrcode_scanner = None

st.set_page_config(page_title="OrthoFlow WMS", page_icon="📦", layout="wide")

st.markdown(
    """
    <style>
    .block-container {max-width: 1500px; padding-top: 1.2rem;}
    [data-testid="stMetric"] {border: 1px solid rgba(23,107,87,.16); border-radius: 16px; padding: 14px;}
    .wms-card {padding: 16px; border: 1px solid rgba(49,51,63,.14); border-radius: 16px; margin-bottom: 12px;}
    @media (max-width: 760px) {
      .block-container {padding-left: .7rem; padding-right: .7rem;}
      .stButton button {min-height: 48px;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def sb():
    url = st.secrets.get("SUPABASE_URL")
    key = (
        st.secrets.get("SUPABASE_SERVICE_KEY")
        or st.secrets.get("SUPABASE_ANON_KEY")
        or st.secrets.get("SUPABASE_KEY")
    )
    if not url or not key:
        st.error("Supabase non configurato nei Secrets.")
        st.stop()
    return create_client(str(url).rstrip("/"), str(key))


def user():
    return str(st.session_state.get("user", ""))


def role():
    return str(st.session_state.get("ruolo", ""))


def require_access():
    if not user():
        st.warning("Accedi prima dalla pagina principale di OrthoFlow.")
        st.stop()
    if role() not in {"Admin", "Magazzino"}:
        st.error("Il WMS è riservato ad Amministratore e Logistica/Magazzino.")
        st.caption("Gli agenti continuano a usare Scarico sala senza vedere ubicazioni, quantità o scaffali.")
        st.stop()


def table(name, order="id", desc=False):
    try:
        return pd.DataFrame(
            sb().table(name).select("*").order(order, desc=desc).execute().data or []
        )
    except Exception as exc:
        st.error(f"Errore lettura {name}: {exc}")
        return pd.DataFrame()


def audit(action, detail=""):
    try:
        sb().table("audit_log").insert(
            {
                "utente": user(),
                "ruolo": role(),
                "azione": action,
                "tabella": "WMS",
                "dettaglio": detail,
            }
        ).execute()
    except Exception:
        pass


def qr_payload(token):
    return f"OFWMS:LOC:{token}"


def qr_png(token, box_size=10):
    qr = qrcode.QRCode(version=None, box_size=box_size, border=4)
    qr.add_data(qr_payload(token))
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def qr_zip(locations):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for _, row in locations.iterrows():
            name = f"QR_{row.get('codice_magazzino','')}_{row.get('codice_ubicazione','')}.png"
            archive.writestr(name.replace("/", "_"), qr_png(row.get("qr_token")))
    return output.getvalue()


def loc_label(row):
    return f"{row.get('codice_magazzino','')} · {row.get('codice_ubicazione','')}"


def icon(status):
    return {
        "SCADUTO": "🔴",
        "URGENTE": "🟠",
        "ATTENZIONE": "🟡",
        "MONITORARE": "🔵",
        "NORMALE": "🟢",
    }.get(str(status), "⚪")


def normalize_scan(raw):
    value = str(raw or "").strip()
    value = value.replace("\u001d", "|")
    return value


def parse_gs1(raw):
    """Estrae i campi GS1 più comuni. Il risultato va sempre confermato dall'operatore."""
    value = normalize_scan(raw)
    result = {"raw": value, "gtin": "", "lotto": "", "scadenza": None, "seriale": ""}
    compact = value.removeprefix("]d2").removeprefix("]C1")

    # Formato leggibile con parentesi: (01)...(17)...(10)...
    for ai, val in re.findall(r"\((01|10|17|21)\)([^()]+)", compact):
        val = val.strip("|")
        if ai == "01": result["gtin"] = val[:14]
        elif ai == "10": result["lotto"] = val
        elif ai == "21": result["seriale"] = val
        elif ai == "17" and len(val) >= 6:
            try: result["scadenza"] = pd.to_datetime(val[:6], format="%y%m%d").date()
            except Exception: pass

    # Formato GS1 concatenato più frequente: 01 + 14 cifre, 17 + 6 cifre.
    if not result["gtin"]:
        match = re.search(r"01(\d{14})", compact)
        if match: result["gtin"] = match.group(1)
    if result["scadenza"] is None:
        match = re.search(r"17(\d{6})", compact)
        if match:
            try: result["scadenza"] = pd.to_datetime(match.group(1), format="%y%m%d").date()
            except Exception: pass

    # AI variabili delimitati da FNC1, rappresentato qui con |.
    lot_match = re.search(r"(?:^|\|)10([^|]+)", compact)
    if lot_match and not result["lotto"]: result["lotto"] = lot_match.group(1)
    serial_match = re.search(r"(?:^|\|)21([^|]+)", compact)
    if serial_match and not result["seriale"]: result["seriale"] = serial_match.group(1)
    return result


def scan_widget(key, label="Scansiona codice"):
    st.caption(label)
    scanned = None
    if qrcode_scanner is not None:
        scanned = qrcode_scanner(key=key)
    else:
        st.warning("Scanner live non disponibile: usa inserimento manuale. Controlla requirements.txt.")
    manual = st.text_input("Codice manuale", key=f"{key}_manual")
    return normalize_scan(scanned or manual)


def location_from_scan(raw):
    token = normalize_scan(raw).split(":")[-1]
    if not token:
        return None
    rows = (
        sb().table("ubicazioni_magazzino")
        .select("*")
        .eq("qr_token", token)
        .limit(1)
        .execute().data
        or []
    )
    return rows[0] if rows else None


def find_article(scan_data):
    raw = scan_data.get("raw", "")
    gtin = scan_data.get("gtin", "")
    try:
        query = sb().table("codici_prodotto_scan").select("*")
        if gtin:
            rows = query.eq("gtin", gtin).limit(1).execute().data or []
        else:
            rows = query.eq("codice_scansionato", raw).limit(1).execute().data or []
        return rows[0] if rows else None
    except Exception:
        return None


require_access()
st.title("📦 OrthoFlow WMS")
st.caption("Area riservata a logistica: ubicazioni, QR, posizionamento, trasferimenti e scadenze FEFO.")
section = st.sidebar.radio(
    "WMS",
    ["Dashboard", "Ubicazioni", "Scanner", "Posizionamento", "Trasferimenti", "Scadenze", "Movimenti"],
)

if section == "Dashboard":
    locations = table("ubicazioni_magazzino")
    stock = table("giacenze_ubicazioni")
    expiries = table("v_scadenze_ubicazioni", "scadenza")
    expired = len(expiries[expiries["stato_scadenza"] == "SCADUTO"]) if not expiries.empty else 0
    urgent = len(expiries[expiries["stato_scadenza"] == "URGENTE"]) if not expiries.empty else 0
    unlocated = 0
    try:
        unlocated = int(sb().rpc("wms_conta_righe_non_ubicate", {}).execute().data or 0)
    except Exception:
        pass
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Ubicazioni", len(locations))
    c2.metric("Righe ubicate", len(stock))
    c3.metric("Da ubicare", unlocated)
    c4.metric("Scaduti", expired)
    c5.metric("Entro 30 giorni", urgent)
    if not expiries.empty:
        priority = expiries[
            expiries["stato_scadenza"].isin(["SCADUTO", "URGENTE", "ATTENZIONE"])
        ].copy()
        if not priority.empty:
            priority["stato"] = priority["stato_scadenza"].map(lambda x: f"{icon(x)} {x}")
            cols = [
                c for c in ["stato", "codice", "descrizione", "lotto", "scadenza",
                            "giorni_scadenza", "quantita_disponibile", "nome_magazzino",
                            "codice_ubicazione"] if c in priority
            ]
            st.subheader("Priorità scadenze")
            st.dataframe(priority[cols], use_container_width=True, hide_index=True)
        else:
            st.success("Nessuna scadenza critica.")

elif section == "Ubicazioni":
    mags = table("magazzini", "codice_magazzino")
    mag_opts = mags["codice_magazzino"].astype(str).tolist() if not mags.empty else ["MAG1"]
    with st.form("new_location"):
        mag = st.selectbox("Magazzino", mag_opts)
        a, b, c, d = st.columns(4)
        corsia = a.text_input("Corsia", "A")
        scaffale = b.text_input("Scaffale", "01")
        ripiano = c.text_input("Ripiano", "A")
        posizione = d.text_input("Postazione", "01")
        suggested = f"{mag}-{corsia}-{scaffale}-{ripiano}-{posizione}".upper()
        codice = st.text_input("Codice ubicazione", suggested)
        descrizione = st.text_input("Descrizione")
        capacita = st.number_input("Capacità indicativa", min_value=0.0, value=0.0)
        save = st.form_submit_button("Crea ubicazione", use_container_width=True)
    if save:
        try:
            sb().table("ubicazioni_magazzino").insert(
                {
                    "codice_magazzino": mag.strip(),
                    "codice_ubicazione": codice.strip().upper(),
                    "corsia": corsia.strip().upper(),
                    "scaffale": scaffale.strip().upper(),
                    "ripiano": ripiano.strip().upper(),
                    "posizione": posizione.strip().upper(),
                    "descrizione": descrizione.strip(),
                    "capacita": capacita or None,
                    "attiva": True,
                }
            ).execute()
            audit("CREA_UBICAZIONE", codice)
            st.success("Ubicazione creata.")
            st.rerun()
        except Exception as exc:
            st.error(f"Impossibile creare l'ubicazione: {exc}")

    locations = table("ubicazioni_magazzino", "codice_ubicazione")
    if not locations.empty:
        st.dataframe(locations, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Scarica tutti i QR in ZIP",
            qr_zip(locations),
            file_name="orthoflow_qr_ubicazioni.zip",
            mime="application/zip",
            use_container_width=True,
        )
        loc_id = st.selectbox(
            "Etichetta QR singola",
            locations["id"].tolist(),
            format_func=lambda x: loc_label(locations[locations["id"] == x].iloc[0].to_dict()),
        )
        row = locations[locations["id"] == loc_id].iloc[0].to_dict()
        data = qr_png(row.get("qr_token"))
        x, y = st.columns([1, 3])
        x.image(data, width=220)
        y.markdown(
            f"### {row.get('codice_ubicazione')}\n"
            f"**Magazzino:** {row.get('codice_magazzino')}  \n"
            f"Corsia {row.get('corsia')} → Scaffale {row.get('scaffale')} → "
            f"Ripiano {row.get('ripiano')} → Postazione {row.get('posizione')}"
        )
        y.download_button(
            "Scarica QR",
            data,
            file_name=f"QR_{row.get('codice_magazzino')}_{row.get('codice_ubicazione')}.png",
            mime="image/png",
        )
        st.info("Stampa consigliata: QR minimo 30×30 mm sul ripiano/postazione; 40×40 mm sulla testata dello scaffale. Mantieni il codice ubicazione scritto anche in chiaro.")

elif section == "Scanner":
    mode = st.radio("Cosa vuoi scansionare?", ["Ubicazione OrthoFlow", "Prodotto Johnson / GS1"], horizontal=True)
    if mode == "Ubicazione OrthoFlow":
        raw = scan_widget("wms_location_scanner", "Inquadra il QR OrthoFlow dello scaffale, ripiano o postazione")
        if raw:
            row = location_from_scan(raw)
            if not row:
                st.error("QR ubicazione non riconosciuto.")
            else:
                st.success(f"Ubicazione: {loc_label(row)}")
                stock = pd.DataFrame(
                    sb().table("giacenze_ubicazioni").select("*")
                    .eq("ubicazione_id", row["id"]).execute().data or []
                )
                if stock.empty:
                    st.info("Ubicazione vuota.")
                else:
                    st.dataframe(stock, use_container_width=True, hide_index=True)
    else:
        raw = scan_widget("wms_product_scanner", "Inquadra il DataMatrix o codice a barre Johnson")
        if raw:
            parsed = parse_gs1(raw)
            mapped = find_article(parsed)
            c1, c2, c3 = st.columns(3)
            c1.metric("GTIN", parsed.get("gtin") or "Non letto")
            c2.metric("Lotto", parsed.get("lotto") or "Da confermare")
            c3.metric("Scadenza", str(parsed.get("scadenza") or "Da confermare"))
            if mapped:
                st.success(f"Articolo associato: {mapped.get('codice_articolo')} · {mapped.get('descrizione','')}")
                positions = pd.DataFrame(
                    sb().table("v_scadenze_ubicazioni").select("*")
                    .eq("codice", mapped.get("codice_articolo"))
                    .order("scadenza").execute().data or []
                )
                if positions.empty:
                    st.warning("Articolo riconosciuto ma non ancora ubicato.")
                else:
                    st.subheader("Dove si trova — ordine FEFO")
                    st.dataframe(positions, use_container_width=True, hide_index=True)
            else:
                st.warning("Codice non ancora associato all'anagrafica articoli.")
                with st.form("map_scan"):
                    article_code = st.text_input("Codice articolo Johnson")
                    description = st.text_input("Descrizione")
                    save_map = st.form_submit_button("Salva associazione", use_container_width=True)
                if save_map and article_code.strip():
                    sb().table("codici_prodotto_scan").upsert(
                        {
                            "codice_scansionato": parsed.get("raw"),
                            "gtin": parsed.get("gtin") or None,
                            "codice_articolo": article_code.strip().upper(),
                            "descrizione": description.strip(),
                            "attivo": True,
                        },
                        on_conflict="codice_scansionato",
                    ).execute()
                    audit("ASSOCIA_CODICE_SCAN", article_code)
                    st.success("Associazione salvata.")
                    st.rerun()

elif section == "Posizionamento":
    st.subheader("Posiziona una giacenza già caricata")
    st.caption("Il DDT o l'import iniziale carica la giacenza generale; qui la distribuisci fisicamente tra scaffali e postazioni.")
    general = table("giacenze", "id", True)
    locations = table("ubicazioni_magazzino", "codice_ubicazione")
    if general.empty or locations.empty:
        st.info("Servono una giacenza generale e almeno un'ubicazione.")
    else:
        general["label"] = general.apply(
            lambda r: f"{r.get('codice')} · Lotto {r.get('lotto')} · Q.tà {r.get('quantita')} · {r.get('codice_magazzino')}", axis=1
        )
        with st.form("place_stock"):
            gid = st.selectbox(
                "Prodotto / lotto",
                general["id"].tolist(),
                format_func=lambda x: general.loc[general["id"] == x, "label"].iloc[0],
            )
            grow = general[general["id"] == gid].iloc[0].to_dict()
            compatible = locations[locations["codice_magazzino"].astype(str) == str(grow.get("codice_magazzino"))]
            lid = st.selectbox(
                "Ubicazione",
                compatible["id"].tolist(),
                format_func=lambda x: loc_label(compatible[compatible["id"] == x].iloc[0].to_dict()),
            )
            qty = st.number_input("Quantità da ubicare", min_value=0.01, value=1.0)
            sterile = st.checkbox("Sterile", True)
            place = st.form_submit_button("Conferma posizionamento", use_container_width=True)
        if place:
            try:
                sb().rpc(
                    "wms_ubica_da_giacenza",
                    {
                        "p_giacenza_id": int(gid),
                        "p_ubicazione_id": int(lid),
                        "p_quantita": float(qty),
                        "p_sterile": bool(sterile),
                        "p_utente": user(),
                    },
                ).execute()
                audit("POSIZIONA_MATERIALE", f"giacenza={gid}; ubicazione={lid}; qta={qty}")
                st.success("Materiale ubicato.")
                st.rerun()
            except Exception as exc:
                st.error(f"Posizionamento non eseguito: {exc}")

elif section == "Trasferimenti":
    locations = table("ubicazioni_magazzino", "codice_ubicazione")
    stock = table("giacenze_ubicazioni", "updated_at", True)
    if locations.empty or stock.empty:
        st.info("Servono almeno due ubicazioni e una giacenza ubicata.")
    else:
        stock["label"] = stock.apply(
            lambda r: f"{r.get('codice')} · Lotto {r.get('lotto')} · Q.tà {r.get('quantita')} · Ub. {r.get('ubicazione_id')}", axis=1
        )
        with st.form("move"):
            sid = st.selectbox(
                "Prodotto",
                stock["id"].tolist(),
                format_func=lambda x: stock.loc[stock["id"] == x, "label"].iloc[0],
            )
            row = stock[stock["id"] == sid].iloc[0].to_dict()
            dests = locations[
                (locations["codice_magazzino"] == row["codice_magazzino"])
                & (locations["id"] != row["ubicazione_id"])
            ]
            did = st.selectbox(
                "Destinazione",
                dests["id"].tolist(),
                format_func=lambda x: loc_label(dests[dests["id"] == x].iloc[0].to_dict()),
            )
            available = float(row.get("quantita", 0)) - float(row.get("quantita_impegnata", 0))
            qty = st.number_input("Quantità", min_value=0.01, max_value=max(0.01, available), value=min(1.0, max(0.01, available)))
            note = st.text_input("Note")
            go = st.form_submit_button("Conferma spostamento", use_container_width=True)
        if go:
            try:
                sb().rpc(
                    "wms_sposta_materiale",
                    {
                        "p_ubicazione_origine_id": int(row["ubicazione_id"]),
                        "p_ubicazione_destinazione_id": int(did),
                        "p_codice": str(row["codice"]),
                        "p_lotto": str(row["lotto"]),
                        "p_origine": str(row.get("origine", "")),
                        "p_sterile": bool(row.get("sterile", True)),
                        "p_quantita": float(qty),
                        "p_utente": user(),
                        "p_note": note,
                    },
                ).execute()
                audit("SPOSTA_MATERIALE", f"stock={sid}; dest={did}; qta={qty}")
                st.success("Spostamento registrato.")
                st.rerun()
            except Exception as exc:
                st.error(f"Spostamento non eseguito: {exc}")

elif section == "Scadenze":
    horizon = st.select_slider(
        "Orizzonte",
        options=[30, 60, 90, 180, 365],
        value=90,
        format_func=lambda x: f"{x} giorni",
    )
    expiries = table("v_scadenze_ubicazioni", "scadenza")
    if expiries.empty:
        st.info("Nessuna giacenza ubicata.")
    else:
        expiries["scadenza"] = pd.to_datetime(expiries["scadenza"], errors="coerce").dt.date
        filtered = expiries[
            expiries["scadenza"].notna()
            & (expiries["scadenza"] <= date.today() + timedelta(days=int(horizon)))
        ].copy()
        filtered = filtered.sort_values(
            ["scadenza", "codice_magazzino", "corsia", "scaffale", "ripiano", "posizione"]
        )
        if filtered.empty:
            st.success("Nessun prodotto in scadenza nell'orizzonte selezionato.")
        else:
            filtered["stato"] = filtered["stato_scadenza"].map(lambda x: f"{icon(x)} {x}")
            cols = [
                c for c in ["stato", "codice", "descrizione", "lotto", "scadenza",
                            "giorni_scadenza", "quantita_disponibile", "nome_magazzino",
                            "corsia", "scaffale", "ripiano", "posizione", "codice_ubicazione"]
                if c in filtered
            ]
            c1, c2, c3 = st.columns(3)
            c1.metric("Righe da controllare", len(filtered))
            c2.metric("Quantità complessiva", float(filtered["quantita_disponibile"].fillna(0).sum()))
            c3.metric("Scaffali coinvolti", filtered["codice_ubicazione"].nunique())
            st.subheader("Giro di recupero FEFO")
            st.dataframe(filtered[cols], use_container_width=True, hide_index=True)
            st.download_button(
                "Esporta giro scadenze CSV",
                filtered[cols].to_csv(index=False).encode("utf-8-sig"),
                file_name=f"giro_scadenze_{date.today()}.csv",
                mime="text/csv",
                use_container_width=True,
            )

elif section == "Movimenti":
    moves = table("movimenti_ubicazioni", "data_movimento", True)
    if moves.empty:
        st.info("Nessun movimento registrato.")
    else:
        st.dataframe(moves, use_container_width=True, hide_index=True)
        st.download_button(
            "Esporta movimenti CSV",
            moves.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"movimenti_ubicazioni_{date.today()}.csv",
            mime="text/csv",
            use_container_width=True,
        )
