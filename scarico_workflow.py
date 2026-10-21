"""Server-side scarico helpers; no shared session data or database writes."""
import re
from review_editor import text_value

LINES = ('TRAUMA', 'PROTESICA', 'CMF', 'SPINE', 'SPORTS', 'ALTRO')


def reset_destination(state):
    """Called before widgets on a fresh extraction or after a completed discharge."""
    state['scarico_destination_client'] = None
    state['scarico_price_line'] = None
    state.pop('scarico_missing_prices', None)
    state.pop('scarico_stock_errors', None)


def destination_errors(client, line):
    errors = []
    if not isinstance(client, dict) or not text_value(client.get('codice_cliente')):
        errors.append('Seleziona la struttura / cliente prima di creare l’intervento.')
    if line not in LINES:
        errors.append('Seleziona la linea prima di creare l’intervento.')
    return errors


def stock_snapshot(client, warehouse):
    """One paginated read per submit, including capped server pages."""
    rows, offset = [], 0
    while True:
        batch = (client.table('giacenze').select('codice,lotto,scadenza,quantita')
            .eq('codice_magazzino', warehouse).eq('origine', 'CONTO DEPOSITO')
            .order('id').range(offset, offset + 499).execute().data or [])
        if not batch:
            return rows
        rows.extend(batch)
        offset += len(batch)


def stock_quantities(rows):
    quantities = {}
    for row in rows:
        code = re.sub(r'[^A-Z0-9]', '', text_value(row.get('codice')).upper())
        key = (code, text_value(row.get('lotto')))
        quantities[key] = quantities.get(key, 0.0) + max(0.0, float(row.get('quantita') or 0))
    return quantities
