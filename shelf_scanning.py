"""Product GS1 and authenticated shelf links. No stock writes or AI calls."""
from datetime import date
from urllib.parse import urlencode,urlparse,parse_qs
from label_pipeline import gs1_parse
from catalog_import import valid_gtin

DEFAULT_APP_URL='https://orthoflowv10-nsu2xsctf5m5wexpgnduap.streamlit.app'


def normalize_scan(raw):
    if isinstance(raw,dict):
        raw=raw.get('rawValue') or raw.get('text') or raw.get('data') or ''
    return str(raw or '').strip().replace('|','\x1d')


def parse_product(raw):
    value=normalize_scan(raw)
    result={'raw':value,'gtin':'','lotto':'','scadenza':None,'seriale':''}
    if valid_gtin(value):
        result['gtin']=value
        return result
    decoded=gs1_parse(value)
    if decoded.get('error'):
        result['error']=decoded['error']
        return result
    result.update(gtin=decoded.get('gtin') or '',lotto=decoded.get('lot') or '',
                  scadenza=date.fromisoformat(decoded['expiry']) if decoded.get('expiry') else None,
                  seriale=decoded.get('ais',{}).get('21',''))
    return result


def find_product_mapping(client,parsed):
    gtin=parsed.get('gtin')
    if gtin:
        try:
            rows=client.table('articoli_gtin').select('gtin,ref,descrizione').eq('gtin',gtin).limit(1).execute().data or []
            if rows and rows[0].get('ref'):
                return dict(rows[0],codice_articolo=rows[0]['ref'])
        except Exception:
            pass  # Existing learned associations remain usable if catalogue is unavailable.
    try:
        q=client.table('codici_prodotto_scan').select('*').eq('attivo',True)
        rows=(q.eq('gtin',gtin) if gtin else q.eq('codice_scansionato',parsed.get('raw',''))).execute().data or []
        refs={str(r.get('codice_articolo') or '').strip().upper() for r in rows if r.get('codice_articolo')}
        if len(refs)>1:
            return {'mapping_error':'GTIN associato a più REF: verifica l’associazione prima di salvare.'}
        return next((r for r in rows if r.get('codice_articolo')),None)
    except Exception:
        return None


def shelf_target(value):
    if isinstance(value,(tuple,list)) and len(value)==3:
        return tuple(str(p).strip().upper() for p in value) if all(str(p).strip() for p in value) else None
    text=str(value or '').strip()
    if text.startswith(('https://','http://')):
        text=parse_qs(urlparse(text).query).get('shelf',[''])[0]
    text=text.removeprefix('OFWMS:SHELF:')
    parts=text.split('|')
    if len(parts)!=3 or not all(p.strip() for p in parts):
        return None
    return tuple(p.strip().upper() for p in parts)


def shelf_url(base,mag,corsia,scaffale):
    parsed=urlparse(str(base).strip())
    if parsed.scheme not in {'http','https'} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError('Inserisci un indirizzo web valido dell’app, con https://')
    root=parsed._replace(query='',fragment='').geturl().rstrip('/')+'/'
    token='OFWMS:SHELF:'+'|'.join(str(x).strip().upper() for x in (mag,corsia,scaffale))
    return root+'?'+urlencode({'shelf':token})
