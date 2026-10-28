"""Division-specific closure parsing. Customer PO is never an order number."""
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import pandas as pd

DIVISIONS = ('TRAUMA', 'PROTESICA')

def read_all(client, table, filters=None):
    """PostgREST caps a single response: closure details often exceed 1,000 rows."""
    rows=[]
    offset=0
    while True:
        query=client.table(table).select('*').order('id')
        for key,value in (filters or {}).items():
            query=query.eq(key,value)
        page=query.range(offset,offset+499).execute().data or []
        rows.extend(page)
        if len(page)<500:
            return pd.DataFrame(rows)
        offset+=500

def division(value):
    value = str(value or '').strip().upper()
    return value if value in DIVISIONS else 'DA CLASSIFICARE'

def select_division(frame, selected, column='divisione'):
    if frame.empty:
        return frame.copy()
    if column not in frame:
        return frame.iloc[:0].copy()
    return frame[frame[column].map(division) == selected].copy()

def column(frame, *names):
    lookup = {str(c).strip().lower(): c for c in frame.columns}
    return next((lookup[n.lower()] for n in names if n.lower() in lookup), None)

def decimal(value):
    if pd.isna(value) or str(value).strip() == '':
        return Decimal(0)
    text = str(value).strip().replace('EUR', '').replace('€', '').replace(' ', '')
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    try:
        result = Decimal(text)
        if not result.is_finite():
            raise ValueError('Importo non finito')
        return result
    except InvalidOperation as exc:
        raise ValueError(f'Valore numerico non valido: {value}') from exc

def read_detail(content, filename):
    if filename.lower().endswith('.csv'):
        frames = {'CSV': pd.read_csv(io.BytesIO(content), sep=None, engine='python', dtype=object)}
    else:
        frames = pd.read_excel(io.BytesIO(content), sheet_name=None, dtype=object)
    candidates = []
    for name, frame in frames.items():
        # Prefer the transaction detail over the first-sheet pivot.
        if column(frame, 'Product[P. Code]', 'codice', 'codice prodotto', 'product code') is not None and column(frame, '[Invoiced_Sales__IS_]', 'invoiced_sales', 'totale', 'totale riga', 'total') is not None:
            candidates.append((name, frame))
    if len(candidates) != 1:
        raise ValueError('Selezionare un file con un solo foglio di dettaglio riconoscibile; il riepilogo pivot non basta.')
    return candidates[0]

def prepare_closure(content, filename, selected):
    if selected not in DIVISIONS:
        raise ValueError('Divisione obbligatoria')
    sheet, frame = read_detail(content, filename)
    ref = column(frame, 'Product[P. Code]', 'codice', 'codice prodotto', 'product code')
    franchise = column(frame, 'Product[P. Bravo Franchise]', 'divisione', 'linea')
    if franchise is not None:
        classes = frame[franchise].map(division)
        if (classes != selected).any():
            raise ValueError('Il file contiene righe di un’altra divisione o da classificare. Separarle prima dell’importazione.')
    aliases = {
        'codice': ref,
        'quantita': column(frame, '[Volumes_Primary]', 'quantita', 'quantità', 'quantity'),
        'totale_riga': column(frame, '[Invoiced_Sales__IS_]', 'invoiced_sales', 'totale', 'totale riga', 'total'),
        'nis': column(frame, '[NIS]', 'nis', 'sum of [nis]'),
        'invoiced_sales': column(frame, '[Invoiced_Sales__IS_]', 'invoiced_sales', 'invoiced sales'),
        'numero_ordine': column(frame, 'numero ordine', 'numero_ordine', 'order'),
        'riferimento_cliente': column(frame, 'Order Transactions[O. Customer PO]', 'riferimento_cliente', 'customer po'),
        'lotto': column(frame, 'lotto', 'lot'),
        'cac': column(frame, 'C Account[C. Account Code (CAC)]', 'cac'),
        'account_name': column(frame, 'C Account[C. Account]', 'account'),
        'bill_to': column(frame, 'C Bill To[C. Bill To]', 'bill to'),
        'famiglia_prodotto': column(frame, 'Product[P. Bravo Major]', 'famiglia prodotto'),
        'regione': column(frame, 'C Account[C. Account Region]', 'region'),
        'provincia': column(frame, 'C Account[C. Account County]', 'county'),
    }
    numeric = {'quantita', 'totale_riga', 'nis', 'invoiced_sales'}
    rows=[]
    for index, row in frame.iterrows():
        result={'raw_data': {str(k): None if pd.isna(v) else str(v) for k,v in row.items()}}
        result['raw_data']['_riga_fonte'] = int(index)+2
        for key, col in aliases.items():
            if col is not None and pd.notna(row[col]):
                result[key] = str(decimal(row[col])) if key in numeric else str(row[col]).strip()
        if not result.get('codice'):
            raise ValueError(f'Riga {index+2}: codice prodotto mancante')
        rows.append(result)
    if not rows:
        raise ValueError('File privo di righe')
    # Identity derives from data, so renaming or selecting another month cannot duplicate it.
    canonical=json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',', ':'))
    return {'sheet':sheet,'rows':rows,'fingerprint':hashlib.sha256(canonical.encode()).hexdigest(),
            'total':str(sum((decimal(r.get('totale_riga',0)) for r in rows),Decimal(0))),
            'nis':str(sum((decimal(r.get('nis',0)) for r in rows),Decimal(0))),
            'invoiced_sales':str(sum((decimal(r.get('invoiced_sales',0)) for r in rows),Decimal(0)))}
