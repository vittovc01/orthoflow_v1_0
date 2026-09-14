import os
import re
from datetime import date

import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Gestione Interventi · OrthoFlow", page_icon="🛠️", layout="wide")


def secret(name, default=None):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, default)


@st.cache_resource
def client():
    url = secret("SUPABASE_URL")
    key = secret("SUPABASE_SERVICE_KEY") or secret("SUPABASE_ANON_KEY") or secret("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Supabase non configurato nei Secrets")
    return create_client(str(url).rstrip("/"), str(key))


def sb():
    return client()


def clean(v):
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    return str(v).strip()


def ncode(v):
    return re.sub(r"[^A-Z0-9]", "", clean(v).upper())


def user():
    return clean(st.session_state.get("user"))


def role():
    return clean(st.session_state.get("ruolo"))


if not user():
    st.warning("Accedi prima a OrthoFlow Control Tower.")
    st.stop()

if role() not in {"Admin", "Amministrazione"}:
    st.error("Questa pagina è riservata ad Admin e Amministrazione.")
    st.stop()


def audit(action, table_name, record_id, detail):
    try:
        sb().table("audit_log").insert({
            "utente": user(),
            "ruolo": role(),
            "azione": action,
            "tabella": table_name,
            "record_id": str(record_id),
            "dettaglio": detail,
        }).execute()
    except Exception:
        pass


def offer_ids_for(customer_code, line):
    try:
        links = (sb().table("offerte_clienti").select("offerta_id")
                 .eq("codice_cliente", customer_code).execute().data or [])
        out = []
        for link in links:
            oid = link.get("offerta_id")
            heads = (sb().table("offerte_header").select("id,linea")
                     .eq("id", oid).limit(1).execute().data or [])
            if heads and clean(heads[0].get("linea")).upper() == clean(line).upper():
                out.append(oid)
        return out
    except Exception:
        return []


def price_for(customer_code, product_code, line):
    target = clean(product_code).upper()
    if not target:
        return None
    try:
        for oid in offer_ids_for(customer_code, line):
            rows = (sb().table("offerte_prezzi").select("codice,prezzo")
                    .eq("offerta_id", oid).eq("codice", target)
                    .limit(1).execute().data or [])
            if rows:
                return float(rows[0].get("prezzo") or 0)
            rows = (sb().table("offerte_prezzi").select("codice,prezzo")
                    .eq("offerta_id", oid).ilike("codice", target)
                    .limit(20).execute().data or [])
            for p in rows:
                if ncode(p.get("codice")) == ncode(target):
                    return float(p.get("prezzo") or 0)
    except Exception:
        pass
    return None


def available_qty(mag, code, lot):
    try:
        rows = (sb().table("giacenze").select("codice,lotto,quantita")
                .eq("codice_magazzino", mag).eq("lotto", lot).execute().data or [])
        return sum(float(r.get("quantita") or 0) for r in rows if ncode(r.get("codice")) == ncode(code))
    except Exception:
        return 0.0


def warehouse_codes():
    try:
        rows = sb().table("magazzini").select("codice_magazzino").order("id").execute().data or []
        vals = [clean(r.get("codice_magazzino")) for r in rows if clean(r.get("codice_magazzino"))]
        return vals or ["MAG1"]
    except Exception:
        return ["MAG1"]


st.title("🛠️ Gestione Interventi")
st.caption("Controllo completo post-intervento: puoi correggere dati clinici, codice, lotto, scadenza, quantità, descrizione e prezzo. Le correzioni che cambiano il materiale generano movimenti di rettifica del magazzino, così la giacenza resta coerente.")

try:
    interventions = (sb().table("interventi").select("*")
                     .order("id", desc=True).limit(300).execute().data or [])
except Exception as e:
    st.error(f"Errore lettura interventi: {e}")
    st.stop()

if not interventions:
    st.info("Nessun intervento disponibile.")
    st.stop()

labels = {}
for item in interventions:
    iid = item.get("id")
    label = f"#{iid} · {clean(item.get('data_intervento'))} · {clean(item.get('cliente'))} · {clean(item.get('cartella_clinica')) or 'senza cartella'}"
    labels[label] = item

selected_label = st.selectbox("Seleziona intervento", list(labels.keys()))
intervention = labels[selected_label]
intervention_id = intervention.get("id")

st.subheader("Dati intervento")
with st.form(f"header_{intervention_id}"):
    h1, h2, h3 = st.columns(3)
    with h1:
        data_value = pd.to_datetime(intervention.get("data_intervento"), errors="coerce")
        edit_date = st.date_input("Data intervento", value=data_value.date() if pd.notna(data_value) else date.today())
        edit_customer_code = st.text_input("Codice cliente", value=clean(intervention.get("codice_cliente")))
        edit_client = st.text_input("Cliente / struttura", value=clean(intervention.get("cliente") or intervention.get("struttura")))
    with h2:
        edit_record = st.text_input("Cartella clinica", value=clean(intervention.get("cartella_clinica")))
        edit_surgeon = st.text_input("Chirurgo", value=clean(intervention.get("chirurgo")))
        edit_agent = st.text_input("Agente", value=clean(intervention.get("agente")))
    with h3:
        lines = ["TRAUMA", "PROTESICA", "CMF", "SPINE", "SPORTS", "ALTRO"]
        current_line = clean(intervention.get("linea")) or "TRAUMA"
        edit_line = st.selectbox("Linea", lines, index=lines.index(current_line) if current_line in lines else 0)
        mags = warehouse_codes()
        current_mag = clean(intervention.get("magazzino_scarico") or intervention.get("magazzino")) or mags[0]
        if current_mag not in mags:
            mags = [current_mag] + mags
        edit_mag = st.selectbox("Magazzino scarico", mags, index=mags.index(current_mag))
        edit_notes = st.text_area("Note", value=clean(intervention.get("note")), height=88)
    save_header = st.form_submit_button("💾 Salva dati intervento", use_container_width=True)

if save_header:
    try:
        old_mag = clean(intervention.get("magazzino_scarico") or intervention.get("magazzino"))
        if edit_mag != old_mag:
            st.warning("Il cambio di magazzino va effettuato insieme alle righe materiali sotto, così OrthoFlow può rettificare correttamente le giacenze. Modifica il magazzino nella testata e poi salva anche le righe.")
        sb().table("interventi").update({
            "data_intervento": edit_date.isoformat(),
            "codice_cliente": clean(edit_customer_code),
            "cliente": clean(edit_client),
            "struttura": clean(edit_client),
            "cartella_clinica": clean(edit_record),
            "chirurgo": clean(edit_surgeon),
            "agente": clean(edit_agent),
            "linea": edit_line,
            "magazzino_scarico": edit_mag,
            "magazzino": edit_mag,
            "note": clean(edit_notes),
        }).eq("id", intervention_id).execute()
        audit("AGGIORNA_INTERVENTO", "interventi", intervention_id, "Modificati dati testata intervento")
        st.success("Dati intervento aggiornati.")
        st.rerun()
    except Exception as e:
        st.error(f"Aggiornamento testata non completato: {e}")

customer_code = clean(intervention.get("codice_cliente"))
line = clean(intervention.get("linea"))
mag = clean(intervention.get("magazzino_scarico") or intervention.get("magazzino")) or "MAG1"

try:
    rows = (sb().table("righe_intervento").select("*")
            .eq("intervento_id", intervention_id).order("id").execute().data or [])
except Exception as e:
    st.error(f"Errore lettura righe intervento: {e}")
    st.stop()

if not rows:
    st.info("L'intervento non contiene righe materiale.")
    st.stop()

prepared = []
for r in rows:
    current_price = r.get("prezzo")
    offer_price = price_for(customer_code, r.get("codice"), line)
    if current_price is None and offer_price is not None:
        editable_price = float(offer_price)
        source = "OFFERTA DA APPLICARE"
    elif current_price is None:
        editable_price = None
        source = "DA INSERIRE"
    else:
        editable_price = float(current_price)
        source = "INTERVENTO"
    qty = float(r.get("quantita") or 0)
    prepared.append({
        "id": r.get("id"),
        "codice": clean(r.get("codice")),
        "descrizione": clean(r.get("descrizione")),
        "lotto": clean(r.get("lotto")),
        "scadenza": clean(r.get("scadenza")),
        "quantita": qty,
        "produttore": clean(r.get("produttore")),
        "validazione": clean(r.get("validazione")),
        "origine": clean(r.get("origine")),
        "prezzo": editable_price,
        "prezzo_offerta": offer_price,
        "fonte": source,
        "reintegro": bool(r.get("reintegro", True)),
        "totale": (qty * editable_price) if editable_price is not None else None,
    })

df = pd.DataFrame(prepared)

st.subheader("Controllo completo materiali")
st.info("Puoi correggere tutti i dati operativi della riga. Se cambi codice, lotto, quantità o magazzino, OrthoFlow crea automaticamente una rettifica: riporta a magazzino il vecchio materiale e scarica quello corretto. Prezzo e descrizione non muovono la giacenza.")

edited = st.data_editor(
    df,
    hide_index=True,
    use_container_width=True,
    num_rows="fixed",
    disabled=["id", "prezzo_offerta", "fonte", "totale"],
    column_config={
        "id": st.column_config.NumberColumn("ID", format="%d"),
        "codice": st.column_config.TextColumn("Codice Johnson/REF", required=True),
        "descrizione": st.column_config.TextColumn("Descrizione"),
        "lotto": st.column_config.TextColumn("Lotto", required=True),
        "scadenza": st.column_config.TextColumn("Scadenza YYYY-MM-DD"),
        "quantita": st.column_config.NumberColumn("Qtà", min_value=0.01, step=1.0, format="%.2f", required=True),
        "produttore": st.column_config.TextColumn("Produttore"),
        "validazione": st.column_config.TextColumn("Validazione"),
        "origine": st.column_config.TextColumn("Origine"),
        "prezzo": st.column_config.NumberColumn("Prezzo €", min_value=0.0, step=0.01, format="€ %.2f"),
        "prezzo_offerta": st.column_config.NumberColumn("Prezzo offerta €", format="€ %.2f"),
        "fonte": st.column_config.TextColumn("Fonte"),
        "reintegro": st.column_config.CheckboxColumn("Reintegro"),
        "totale": st.column_config.NumberColumn("Totale attuale €", format="€ %.2f"),
    },
    key=f"intervento_editor_full_{intervention_id}",
)

preview = edited.copy()
preview["totale_nuovo"] = pd.to_numeric(preview["quantita"], errors="coerce").fillna(0) * pd.to_numeric(preview["prezzo"], errors="coerce")
new_total = preview["totale_nuovo"].fillna(0).sum()
old_total = pd.to_numeric(df["totale"], errors="coerce").fillna(0).sum()
m1, m2 = st.columns(2)
m1.metric("Totale attuale", f"€ {old_total:,.2f}")
m2.metric("Nuovo totale", f"€ {new_total:,.2f}")

confirm = st.checkbox("Confermo di aver verificato codice, lotto, scadenza, quantità e prezzo delle righe modificate.", key=f"confirm_full_{intervention_id}")

if st.button("💾 Salva tutte le modifiche", type="primary", use_container_width=True, disabled=not confirm):
    original_by_id = {int(r["id"]): r for r in prepared}
    changes = []
    errors = []

    for _, row in edited.iterrows():
        rid = int(row["id"])
        old = original_by_id[rid]
        code = clean(row["codice"]).upper()
        lot = clean(row["lotto"])
        desc = clean(row["descrizione"])
        expiry = clean(row["scadenza"]) or None
        manufacturer = clean(row["produttore"])
        validation = clean(row["validazione"])
        origin = clean(row["origine"]) or "CONTO DEPOSITO"
        reintegro = bool(row["reintegro"])
        try:
            qty = float(row["quantita"])
        except Exception:
            qty = 0
        price = row["prezzo"]
        if not code or not lot or qty <= 0:
            errors.append(f"Riga {rid}: codice, lotto e quantità devono essere validi.")
            continue
        if pd.isna(price):
            errors.append(f"Riga {rid} ({code}): prezzo mancante.")
            continue
        try:
            price = float(price)
        except Exception:
            errors.append(f"Riga {rid} ({code}): prezzo non valido.")
            continue
        if price < 0:
            errors.append(f"Riga {rid} ({code}): prezzo negativo non consentito.")
            continue
        if expiry:
            dt = pd.to_datetime(expiry, errors="coerce")
            if pd.isna(dt):
                errors.append(f"Riga {rid} ({code}): scadenza non valida. Usa YYYY-MM-DD.")
                continue
            expiry = dt.date().isoformat()

        stock_changed = (
            ncode(code) != ncode(old.get("codice"))
            or lot != clean(old.get("lotto"))
            or abs(qty - float(old.get("quantita") or 0)) > 0.0001
        )

        if stock_changed:
            old_code = clean(old.get("codice")).upper()
            old_lot = clean(old.get("lotto"))
            old_qty = float(old.get("quantita") or 0)
            # Il vecchio scarico verrà annullato prima del nuovo. Se la nuova identità è la stessa,
            # la quantità effettivamente disponibile dopo l'annullo include old_qty.
            avail = available_qty(mag, code, lot)
            if ncode(code) == ncode(old_code) and lot == old_lot:
                avail += old_qty
            if avail < qty:
                errors.append(f"Riga {rid} ({code} lotto {lot}): disponibile {avail:g}, richiesto {qty:g} in {mag}.")
                continue

        changes.append({
            "rid": rid,
            "old": old,
            "code": code,
            "lot": lot,
            "desc": desc,
            "expiry": expiry,
            "qty": qty,
            "manufacturer": manufacturer,
            "validation": validation,
            "origin": origin,
            "reintegro": reintegro,
            "price": price,
            "total": qty * price,
            "stock_changed": stock_changed,
        })

    if errors:
        st.error("Correggi questi punti prima di salvare:")
        for e in errors:
            st.write("•", e)
        st.stop()

    modified = 0
    try:
        for ch in changes:
            rid = ch["rid"]
            old = ch["old"]
            old_code = clean(old.get("codice")).upper()
            old_lot = clean(old.get("lotto"))
            old_qty = float(old.get("quantita") or 0)
            old_expiry = clean(old.get("scadenza")) or None
            old_desc = clean(old.get("descrizione"))
            old_origin = clean(old.get("origine")) or "CONTO DEPOSITO"

            if ch["stock_changed"]:
                # 1) annulla il vecchio scarico: quantità positiva => rientro in giacenza
                sb().table("movimenti_magazzino").insert({
                    "tipo_movimento": "RETTIFICA_INTERVENTO",
                    "codice_magazzino": mag,
                    "codice": old_code,
                    "descrizione": old_desc,
                    "lotto": old_lot,
                    "scadenza": old_expiry,
                    "quantita": abs(old_qty),
                    "origine": old_origin,
                    "riferimento_tipo": "INTERVENTO",
                    "riferimento_id": str(intervention_id),
                    "note": f"Rettifica riga {rid}: annullo scarico precedente",
                    "utente": user(),
                }).execute()
                # 2) applica il materiale corretto
                sb().table("movimenti_magazzino").insert({
                    "tipo_movimento": "RETTIFICA_INTERVENTO",
                    "codice_magazzino": mag,
                    "codice": ch["code"],
                    "descrizione": ch["desc"],
                    "lotto": ch["lot"],
                    "scadenza": ch["expiry"],
                    "quantita": -abs(ch["qty"]),
                    "origine": ch["origin"],
                    "riferimento_tipo": "INTERVENTO",
                    "riferimento_id": str(intervention_id),
                    "note": f"Rettifica riga {rid}: applicato materiale corretto",
                    "utente": user(),
                }).execute()

            payload = {
                "codice": ch["code"],
                "descrizione": ch["desc"],
                "lotto": ch["lot"],
                "scadenza": ch["expiry"],
                "quantita": ch["qty"],
                "produttore": ch["manufacturer"],
                "validazione": ch["validation"],
                "origine": ch["origin"],
                "prezzo": ch["price"],
                "totale": ch["total"],
                "reintegro": ch["reintegro"],
            }
            before = {k: old.get(k) for k in payload.keys()}
            changed_fields = [k for k, v in payload.items() if clean(before.get(k)) != clean(v)]
            if changed_fields:
                sb().table("righe_intervento").update(payload).eq("id", rid).eq("intervento_id", intervention_id).execute()
                audit(
                    "RETTIFICA_RIGA_INTERVENTO",
                    "righe_intervento",
                    rid,
                    f"Intervento {intervention_id} · campi modificati: {', '.join(changed_fields)} · vecchio {old_code}/{old_lot}/{old_qty:g} · nuovo {ch['code']}/{ch['lot']}/{ch['qty']:g}",
                )
                modified += 1

        if modified:
            st.success(f"Intervento #{intervention_id} aggiornato. Righe modificate: {modified}. Nuovo totale: € {new_total:,.2f}")
            st.rerun()
        else:
            st.info("Nessuna modifica da salvare.")
    except Exception as e:
        st.error(f"Aggiornamento non completato: {e}")
        st.warning("Se l'errore è avvenuto durante una rettifica di magazzino, controlla i movimenti dell'intervento prima di riprovare.")
