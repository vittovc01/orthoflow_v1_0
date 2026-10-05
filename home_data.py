"""Read-only operational Home snapshot. No revenue or patient identifiers."""
from datetime import timedelta

from stock_anomalies import split_stock_anomalies


def paginated(query, page_size=500):
    """Use a stable ordering at the call site; never mistake the API cap for a total."""
    result, offset = [], 0
    while True:
        batch = query.range(offset, offset + page_size - 1).execute().data or []
        if not batch:
            return result
        result.extend(batch)
        offset += len(batch)


def load_home(client, today):
    errors = []

    def read(label, callback):
        try:
            return callback()
        except Exception:
            errors.append(label)
            return None

    def count(query):
        value = query.execute().count
        if value is None:
            raise ValueError('Exact count unavailable')
        return value

    first = today.replace(day=1)
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    monthly = read('Interventi del mese', lambda: count(client.table('interventi')
        .select('id', count='exact', head=True).gte('data_intervento', first.isoformat())
        .lt('data_intervento', next_month.isoformat())))
    daily = read('Interventi di oggi', lambda: count(client.table('interventi')
        .select('id', count='exact', head=True).eq('data_intervento', today.isoformat())))
    recent = read('Interventi recenti', lambda: client.table('interventi')
        .select('id,data_intervento,cliente,struttura,agente,linea').order('data_intervento', desc=True)
        .order('id', desc=True).limit(6).execute().data or [])
    missions = read('Missioni', lambda: paginated(client.table('missioni_corrieri')
        .select('id,codice,data_missione,tipo,stato,colli')
        .in_('stato', ['PROGRAMMATA', 'ARRIVATO']).order('data_missione').order('id')))
    prices = read('Anomalie prezzi', lambda: count(client.table('righe_intervento')
        .select('id', count='exact', head=True).eq('prezzo_source', 'DA_VERIFICARE_DIREZIONE')))

    def stock_anomalies():
        anomalies = paginated(client.table('anomalie_giacenza')
            .select('id,intervento_id,codice,lotto').eq('stato', 'DA_VERIFICARE').order('id'))
        ids = sorted({a['intervento_id'] for a in anomalies if a.get('intervento_id') is not None})
        headers, materials = [], []
        for start in range(0, len(ids), 100):
            chunk = ids[start:start + 100]
            headers.extend(paginated(client.table('interventi')
                .select('id,codice_cliente').in_('id', chunk).order('id')))
            materials.extend(paginated(client.table('righe_intervento')
                .select('id,intervento_id,codice,lotto,origine').in_('intervento_id', chunk).order('id')))
        active, _, _ = split_stock_anomalies(anomalies, headers, materials)
        return len(active)

    stock = read('Anomalie giacenza', stock_anomalies)
    lots = read('Disponibilità magazzino', lambda: count(client.table('giacenze')
        .select('id', count='exact', head=True).gt('quantita', 0)))
    expiring = read('Scadenze', lambda: paginated(client.table('giacenze')
        .select('id,codice,lotto,scadenza,quantita,codice_magazzino').gt('quantita', 0)
        .lte('scadenza', (today + timedelta(days=90)).isoformat()).order('scadenza').order('id')))
    return {'today': daily, 'month': monthly, 'recent': recent, 'missions': missions,
            'price_anomalies': prices, 'stock_anomalies': stock,
            'anomalies': None if prices is None or stock is None else prices + stock,
            'lots': lots, 'expiring': expiring, 'errors': errors}
