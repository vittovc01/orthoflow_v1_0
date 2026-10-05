"""Shared classification for the Home and anomaly resolution page."""
def normalized_code(value):
    return "".join(c for c in str(value or "").upper() if c.isascii() and c.isalnum())


def normalized_lot(value):
    return str(value or "").strip().upper()


def split_stock_anomalies(anomalies, interventions, materials):
    headers = {str(i["id"]): i for i in interventions}
    by_item = {}
    for row in materials:
        key = (str(row.get("intervento_id")), normalized_code(row.get("codice")), normalized_lot(row.get("lotto")))
        by_item.setdefault(key, []).append(row)
    active, unlinked, structure = [], [], []
    for anomaly in anomalies:
        intervention = headers.get(str(anomaly.get("intervento_id")))
        if not intervention:
            unlinked.append(anomaly)
            continue
        key = (str(anomaly.get("intervento_id")), normalized_code(anomaly.get("codice")), normalized_lot(anomaly.get("lotto")))
        matches = by_item.get(key, [])
        if str(intervention.get("codice_cliente")) == "9010013" and matches and all(
                r.get("origine") == "CONTO DEPOSITO STRUTTURA" for r in matches):
            structure.append(anomaly)
            continue
        active.append({**anomaly, "cliente": intervention.get("cliente"),
                       "cartella_clinica": intervention.get("cartella_clinica")})
    return active, unlinked, structure


