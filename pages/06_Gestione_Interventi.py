import os
import re

import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Gestione Interventi · OrthoFlow", page_icon="💶", layout="wide")


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


def audit(action, record_id, detail):
    try:
        sb().table("audit_log").insert({
            "utente": user(),
            "ruolo": role(),
            "azione": action,
            "tabella": "righe_intervento",
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


st.title("💶 Gestione Interventi")
st.caption("Modifica i prezzi di un intervento già creato. Le quantità e il magazzino non vengono toccati.")

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
customer_code = clean(intervention.get("codice_cliente"))
line = clean(intervention.get("linea"))

c1, c2, c3, c4 = st.columns(4)
c1.metric("Intervento", f"#{intervention_id}")
c2.metric("Cliente", clean(intervention.get("cliente")) or "-")
c3.metric("Linea", line or "-")
c4.metric("Magazzino", clean(intervention.get("magazzino_scarico")) or "-")

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
        "quantita": qty,
        "prezzo": editable_price,
        "prezzo_offerta": offer_price,
        "fonte": source,
        "totale": (qty * editable_price) if editable_price is not None else None,
    })

df = pd.DataFrame(prepared)

st.subheader("Righe e prezzi")
st.info("Puoi modificare solo il prezzo. Quantità, codice e lotto restano invariati: il salvataggio NON genera nuovi movimenti di magazzino.")

edited = st.data_editor(
    df,
    hide_index=True,
    use_container_width=True,
    disabled=["id", "codice", "descrizione", "lotto", "quantita", "prezzo_offerta", "fonte", "totale"],
    column_config={
        "id": st.column_config.NumberColumn("ID riga", format="%d"),
        "codice": st.column_config.TextColumn("Codice"),
        "descrizione": st.column_config.TextColumn("Descrizione"),
        "lotto": st.column_config.TextColumn("Lotto"),
        "quantita": st.column_config.NumberColumn("Qtà", format="%.2f"),
        "prezzo": st.column_config.NumberColumn("Prezzo €", min_value=0.0, step=0.01, format="€ %.2f"),
        "prezzo_offerta": st.column_config.NumberColumn("Prezzo offerta €", format="€ %.2f"),
        "fonte": st.column_config.TextColumn("Fonte"),
        "totale": st.column_config.NumberColumn("Totale attuale €", format="€ %.2f"),
    },
    key=f"intervento_editor_{intervention_id}",
)

preview = edited.copy()
preview["totale_nuovo"] = pd.to_numeric(preview["quantita"], errors="coerce").fillna(0) * pd.to_numeric(preview["prezzo"], errors="coerce")
new_total = preview["totale_nuovo"].fillna(0).sum()
old_total = pd.to_numeric(df["totale"], errors="coerce").fillna(0).sum()

m1, m2 = st.columns(2)
m1.metric("Totale attuale", f"€ {old_total:,.2f}")
m2.metric("Nuovo totale", f"€ {new_total:,.2f}")

if st.button("💾 Salva prezzi e aggiorna intervento", type="primary", use_container_width=True):
    missing_codes = []
    updates = []
    original_by_id = {int(r["id"]): r for r in prepared}

    for _, row in edited.iterrows():
        rid = int(row["id"])
        code = clean(row["codice"])
        qty = float(row["quantita"] or 0)
        price = row["prezzo"]
        if pd.isna(price):
            missing_codes.append(code)
            continue
        price = float(price)
        if price < 0:
            st.error(f"Prezzo non valido per {code}.")
            st.stop()
        total = qty * price
        old_price = original_by_id[rid].get("prezzo")
        if old_price is None or abs(float(old_price) - price) > 0.0001:
            updates.append((rid, code, price, total, old_price))

    if missing_codes:
        st.error("Inserisci un prezzo per tutti i codici prima di salvare: " + ", ".join(sorted(set(missing_codes))))
    elif not updates:
        st.info("Nessuna modifica da salvare.")
    else:
        try:
            for rid, code, price, total, old_price in updates:
                sb().table("righe_intervento").update({
                    "prezzo": price,
                    "totale": total,
                }).eq("id", rid).eq("intervento_id", intervention_id).execute()
                audit(
                    "AGGIORNA_PREZZO_INTERVENTO",
                    rid,
                    f"Intervento {intervention_id} · {code} · prezzo precedente {old_price} · nuovo prezzo {price:.2f} · totale {total:.2f}",
                )
            st.success(f"Intervento #{intervention_id} aggiornato. Righe modificate: {len(updates)}. Nuovo totale: € {new_total:,.2f}")
            st.rerun()
        except Exception as e:
            st.error(f"Aggiornamento non completato: {e}")
