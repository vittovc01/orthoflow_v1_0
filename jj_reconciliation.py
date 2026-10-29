"""Three-source reconciliation. Missing lots are evidence gaps, never invented values."""
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter, defaultdict
from decimal import Decimal
import pandas as pd
from jj_closures import decimal, prepare_closure

DIVISIONS=('TRAUMA','PROTESICA')
ORDER_COLUMNS=['Presidio','CAC','PO cliente','Numero ordine J&J','Numero fattura','REF','Descrizione','Quantità','Prezzo unitario','Totale riga','Riferimento intervento']

def text(value):
    return '' if value is None or pd.isna(value) or str(value).strip().lower() in ('nan','nat','none') else str(value).strip()

def normalized(value):
    return re.sub(r'[^A-Z0-9]+',' ',unicodedata.normalize('NFKD',text(value).upper()).encode('ascii','ignore').decode()).strip()

def money(value):
    return format(decimal(value).normalize(),'f')

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def positive_quantity(value):
    q=decimal(value)
    if q<=0 or q!=q.to_integral_value(): raise ValueError('Quantità obbligatoria, intera e maggiore di zero')
    return int(q)

def ref(value):
    result=text(value).upper()
    if not result or not re.fullmatch(r'[A-Z0-9][A-Z0-9._/-]*',result):raise ValueError(f'REF non valido: {result or "mancante"}')
    return result

def date(value):
    if not text(value):return ''
    parsed=pd.to_datetime(value,dayfirst=not bool(re.match(r'^\d{4}-\d{2}-\d{2}',str(value))),errors='coerce')
    return parsed.date().isoformat() if pd.notna(parsed) else ''

def frames(content,filename):
    if filename.lower().endswith('.csv'):
        return {'CSV':pd.read_csv(io.BytesIO(content),sep=None,engine='python',dtype=object)}
    return pd.read_excel(io.BytesIO(content),sheet_name=None,dtype=object)

def select_frame(content,filename,required):
    found=[]
    for name,frame in frames(content,filename).items():
        frame.columns=[normalized(c) for c in frame.columns]
        if set(required).issubset(frame.columns):found.append((name,frame))
    if len(found)!=1:raise ValueError('Serve un solo foglio di dettaglio con le colonne richieste')
    return found[0]

def accounts(records):
    result={}
    for r in records:
        if r['kind']=='CHIUSURA':
            for line in r['payload']['lines']:
                if line.get('cac'):result[line['cac']]=line.get('customer') or line['cac']
    return result

def resolve_cac(cac,customer,po,records):
    if text(cac):
        value=text(cac).removesuffix('.0')
        if not value.isdigit():raise ValueError('CAC deve contenere solo cifre')
        return value
    matches=set()
    for r in records:
        for line in r['payload'].get('lines',[]):
            if not line.get('cac'):continue
            if customer and normalized(customer) in {normalized(v) for v in [line.get('customer')]+line.get('aliases',[])}:matches.add(line['cac'])
            elif not customer and po and r['kind']=='CHIUSURA' and text(po).upper()==text(line.get('po')).upper():matches.add(line['cac'])
    if len(matches)==1:return next(iter(matches))
    return ''

def group_lines(lines,kind):
    groups={}
    for line in lines:
        # Repeated labels/rows add quantity. Differing lots/prices remain separate.
        identity=[line['ref'],line.get('lot',''),line.get('price'),line.get('invoice',''),line.get('type',''),line.get('cac',''),line.get('po','')]
        key=digest(identity)[:24]
        if key not in groups:groups[key]={**line,'key':key,'quantity':0,'total':None,'source_rows':[]}
        g=groups[key];g['quantity']+=line['quantity'];g['source_rows']+=line.get('source_rows',[])
        if line.get('total') is not None:g['total']=money(decimal(g['total'])+decimal(line['total']))
    return sorted(groups.values(),key=lambda r:r['key'])

def prepare_tab(content,filename,division,records=(),mapping=None):
    _,frame=select_frame(content,filename,['TIPO','NUMERO','CLIENTE','ARTICOLO','LOTTO','RIFERIMENTO','DATA','QUANTITA','SERIE','CAUSALE'])
    documents={};mapping=dict(mapping or {});cac_cache={}
    prior={r['source_key']:r['payload'] for r in records if r['kind']=='IMPIANTO'}
    for customer in frame['CLIENTE'].dropna().map(text).unique():
        if normalized(customer)=='ASL SALERNO':
            if mapping.get(customer):raise ValueError('ASL Salerno: assegnare Sapri, Nocera o Battipaglia al singolo documento')
            continue
        previous={r['payload'].get('cac') for r in records if r['kind']=='IMPIANTO' and normalized(r['payload'].get('customer'))==normalized(customer) and r['payload'].get('cac')}
        if len(previous)==1:mapping.setdefault(customer,next(iter(previous)))
    for index,row in frame.iterrows():
        if all(not text(v) for v in row):continue
        if division not in normalized(row['CAUSALE']):raise ValueError(f'Riga {index+2}: causale diversa da {division}')
        docdate=date(row['DATA'])
        if not docdate:raise ValueError(f'Riga {index+2}: data documento non valida')
        customer=text(row['CLIENTE']);reference=text(row['RIFERIMENTO'])
        match=re.search(r'(?i)\bCC\s*[:.n°]*\s*(\d+)\s+DEL\s+(\d{1,2}/\d{1,2}/\d{4})',reference)
        encounter=match[1] if match else '';event=date(match[2]) if match else ''
        number=text(row['NUMERO']).removesuffix('.0')
        if not number or not text(row['TIPO']):raise ValueError(f'Riga {index+2}: documento incompleto')
        key='|'.join([docdate[:4],text(row['TIPO']),text(row['SERIE']),number])
        if customer not in cac_cache:cac_cache[customer]='' if normalized(customer)=='ASL SALERNO' else (mapping.get(customer,'') or resolve_cac('',customer,'',records))
        cac=cac_cache[customer]
        previous=prior.get(key,{})
        if normalized(previous.get('customer'))==normalized(customer):
            cac=previous.get('cac') or cac
            if previous.get('reference')==reference and previous.get('document_date')==docdate:
                event=previous.get('event_date') or event
        line={'ref':ref(row['ARTICOLO']),'lot':text(row['LOTTO']).upper(),'quantity':positive_quantity(row['QUANTITA']),
              'expiry':date(row.get('SCADENZA')),'description':text(row.get('DESCRIZIONE')),'source_rows':[int(index)+2]}
        payload={'customer':customer,'cac':cac,'reference':reference,'encounter':encounter,'event_date':event,'source_ref_date':date(match[2]) if match else '','document_date':docdate,'lines':[]}
        if key in documents and any(documents[key][k]!=payload[k] for k in ['customer','reference','document_date']):raise ValueError(f'Documento {key} con intestazioni discordanti')
        documents.setdefault(key,payload)['lines'].append(line)
    result=[]
    for key,payload in documents.items():
        payload['lines']=group_lines(payload['lines'],'IMPIANTO')
        for l in payload['lines']:l['cac']=payload['cac'];l['customer']=payload['customer']
        result.append({'source_key':key,'payload':payload})
    if not result:raise ValueError('TAB senza righe utilizzabili')
    return result

def prepare_orders(content,filename,division,records=()):
    allframes=frames(content,filename)
    preferred={'Ordini':allframes['Ordini']} if 'Ordini' in allframes else allframes
    candidates=[]
    aliases={'ORDINE':'PO CLIENTE','CODICE':'REF','CODICE PRODOTTO':'REF','TOTALE':'TOTALE RIGA'}
    for _,frame in preferred.items():
        frame.columns=[aliases.get(normalized(c),normalized(c)) for c in frame.columns]
        if {'PO CLIENTE','REF','QUANTITA'}.issubset(frame.columns):candidates.append(frame)
    if len(candidates)!=1:raise ValueError('Colonne richieste: PO cliente, REF, Quantità')
    documents={}
    for index,row in candidates[0].iterrows():
        if all(not text(v) for v in row):continue
        # Customer's copy/paste can repeat the table header between orders.
        if normalized(row['REF']) in ('CODICE PRODOTTO','REF','CODICE') and normalized(row['QUANTITA'])=='QUANTITA':continue
        po=text(row['PO CLIENTE']);customer=text(row.get('PRESIDIO'));number=text(row.get('NUMERO ORDINE J J'))
        if not po:raise ValueError(f'Riga {index+2}: PO cliente mancante')
        cac=resolve_cac(row.get('CAC'),customer,po,records)
        if not cac:raise ValueError(f'Riga {index+2}, PO {po}: presidio non univoco. Compila Presidio o CAC')
        invoice=text(row.get('NUMERO FATTURA'))
        key=cac+'|'+('JJ|'+number if number else 'PO|'+po)
        prior=[r for r in records if r['kind']=='ORDINE' and r['division']==division and r['payload'].get('cac')==cac]
        same_number=[r for r in prior if number and r['payload'].get('number')==number]
        same_po=[r for r in prior if r['payload'].get('po')==po and (not number or not r['payload'].get('number') or r['payload'].get('number')==number)]
        previous=same_number or same_po
        if len(previous)>1:raise ValueError(f'PO {po}: più ordini esistenti, compila il numero ordine J&J')
        if previous:key=previous[0]['source_key']
        q=positive_quantity(row['QUANTITA']);price=money(row['PREZZO UNITARIO']) if text(row.get('PREZZO UNITARIO')) else None
        total=money(row['TOTALE RIGA']) if text(row.get('TOTALE RIGA')) else (money(decimal(price)*q) if price is not None else None)
        if price is not None and total is not None and abs(decimal(price)*q-decimal(total))>Decimal('.02'):raise ValueError(f'Riga {index+2}: prezzo × quantità diverso dal totale')
        line={'ref':ref(row['REF']),'lot':text(row.get('LOTTO')).upper(),'quantity':q,'price':price,'total':total,
              'cac':cac,'customer':customer or accounts(records).get(cac,cac),'invoice':invoice,'po':po,
              'description':text(row.get('DESCRIZIONE')),'source_rows':[int(index)+2]}
        payload={'customer':line['customer'],'cac':cac,'po':po,'number':number,'invoice':invoice,'reference':text(row.get('RIFERIMENTO INTERVENTO')),'lines':[]}
        if key in documents and documents[key]['number']!=number:raise ValueError(f'PO {po} riutilizzato: aggiorna prima il numero J&J dell’ordine già presente')
        if key in documents and documents[key]['invoice']!=invoice:raise ValueError(f'PO {po} su più fatture: usa il numero ordine J&J per distinguere gli ordini')
        documents.setdefault(key,payload)['lines'].append(line)
    result=[]
    for key,payload in documents.items():payload['lines']=group_lines(payload['lines'],'ORDINE');result.append({'source_key':key,'payload':payload})
    if not result:raise ValueError('Nessuna riga ordine compilata')
    return result

def prepare_month(content,filename,division,month):
    prepared=prepare_closure(content,filename,division);lines=[];economic=[]
    for row in prepared['rows']:
        raw=row['raw_data'];year=raw.get('Calendar[D. Year]');period=raw.get('Calendar[D. Month Code]')
        if year and period and f'{int(float(year)):04d}-{int(float(period)):02d}'!=month[:7]:raise ValueError('Il mese selezionato non corrisponde al periodo della chiusura')
    for row in prepared['rows']:
        raw=row['raw_data'];typ=raw.get('Order Type[O. Sub Type]','')
        if typ and typ not in ('Consignment Sale','Orthokit Sale','Standard Orders','Return Order'):
            economic.append(row);continue
        qty=decimal(row.get('quantita',0))
        if not qty or qty!=qty.to_integral_value():raise ValueError('Quantità chiusura mancante o non intera')
        total=decimal(row.get('invoiced_sales',row.get('totale_riga',0)))
        lines.append({'ref':ref(row['codice']),'lot':text(row.get('lotto')),'quantity':int(qty),'cac':text(row.get('cac')),
         'customer':text(row.get('account_name')),'aliases':[text(raw.get(k)) for k in ['C Bill To[C. Bill To]','C Ship To[C. Ship To]','C Account[C. Account]']],'po':text(row.get('riferimento_cliente')),
         'invoice':text(raw.get('Order Transactions[O. Invoice Number]')),'date':date(raw.get('Calendar[Date]')),
         'total':money(total),'price':money(total/qty),'type':'RESO' if qty<0 else 'VENDITA',
         'source_rows':[raw.get('_riga_fonte')]})
    return [{'source_key':month[:7],'payload':{'month':month[:7],'total':prepared['total'],'nis':prepared['nis'],
      'invoiced_sales':prepared['invoiced_sales'],'source_row_count':len(prepared['rows']),
      'lines':group_lines(lines,'CHIUSURA'),'economic_rows':economic}}]

def line_rows(records):
    for record in records:
        for line in record['payload'].get('lines',[]):yield record,line

def allocated(links,record_id,line_key,kind):
    side={'CHIUSURA':'closure','ORDINE':'order','IMPIANTO':'implant'}[kind]
    return sum(int(l['quantity']) for l in links if not l.get('revoked_at') and int(l[side+'_id'])==int(record_id) and l[side+'_line']==line_key)

def proposals(records,links,closure_id=None):
    result=[]
    active=[r for r in records if not r.get('pending_payload')]
    closures=[r for r in active if r['kind']=='CHIUSURA' and (closure_id is None or r['id']==closure_id)]
    for closing,a in line_rows(closures):
        remaining=a['quantity']-allocated(links,closing['id'],a['key'],'CHIUSURA')
        if remaining<=0 or not a.get('cac'):continue
        for order,b in line_rows([r for r in active if r['kind']=='ORDINE' and r['division']==closing['division']]):
            if a['ref']!=b['ref'] or a['cac']!=b.get('cac') or text(a.get('po')).upper()!=text(b.get('po')).upper():continue
            if not a.get('po'):continue
            if a.get('invoice') and b.get('invoice') and a['invoice'].split('-')[0]!=b['invoice'].split('-')[0]:continue
            ordr=b['quantity']-allocated(links,order['id'],b['key'],'ORDINE')
            if ordr<=0:continue
            impl_records=[r for r in active if r['kind']=='IMPIANTO' and r['division']==closing['division']]
            order_signature=Counter()
            for ol in order['payload']['lines']:order_signature[ol['ref']]+=ol['quantity']
            full=[]
            for doc in impl_records:
                if doc['payload'].get('cac')!=a['cac']:continue
                if a.get('date') and doc['payload'].get('event_date') and doc['payload']['event_date']>a['date']:continue
                signature=Counter()
                for il in doc['payload']['lines']:signature[il['ref']]+=il['quantity']
                if signature==order_signature:full.append(doc)
            if len(full)==1:impl_records=full
            for implant,c in line_rows(impl_records):
                if a['ref']!=c['ref'] or a['cac']!=c.get('cac'):continue
                if b.get('lot') and c.get('lot') and b['lot']!=c['lot']:continue
                if a.get('date') and implant['payload'].get('event_date') and implant['payload']['event_date']>a['date']:continue
                imr=c['quantity']-allocated(links,implant['id'],c['key'],'IMPIANTO')
                if imr<=0:continue
                result.append({'closure_id':closing['id'],'closure_line':a['key'],'order_id':order['id'],'order_line':b['key'],
                  'implant_id':implant['id'],'implant_line':c['key'],'quantity':min(remaining,ordr,imr),
                  'Fattura':a.get('invoice',''),'PO':a.get('po',''),'REF':a['ref'],'Presidio':a.get('customer') or a['cac'],
                  'Ordine':order['payload'].get('number') or order['payload'].get('po'),
                  'Documento impianto':implant['source_key'],'Riferimento intervento':implant['payload'].get('reference',''),
                  'Riscontro documento':'Composizione completa ordine coincidente' if len(full)==1 else 'Candidato per riga; verificare intervento',
                  'Data intervento':implant['payload'].get('event_date',''),'Lotto impianto':c.get('lot',''),
                  'Metodo':'REF e quantità, lotto ordine non disponibile' if not b.get('lot') else 'REF e lotto',
                  'Differenza prezzo':float(decimal(a['price'])-decimal(b['price'])) if a.get('price') is not None and b.get('price') is not None else None})
    sides={side:Counter((r[side+'_id'],r[side+'_line']) for r in result) for side in ('closure','order','implant')}
    for r in result:r['Univoco']=all(sides[side][(r[side+'_id'],r[side+'_line'])]==1 for side in sides)
    return result

def residuals(records,links):
    result=[]
    for record,line in line_rows(records):
        kind=record['kind'];rid=record['id'];q=line['quantity'];used=allocated(links,rid,line['key'],kind)
        result.append({'Tipo':kind,'Documento':record['source_key'],'REF':line['ref'],'Presidio':line.get('customer',''),
          'Quantità':q,'Quantità riconciliata':used,'Residuo':q-used,'Valore riga':float(line['total']) if line.get('total') is not None else None,
          'Stato':'REVISIONE DA VERIFICARE' if record.get('pending_payload') else ('RESO DA VERIFICARE' if q<0 else ('NON RISCONTRATO CON LE FONTI CARICATE' if used<q else 'QUANTITÀ RICONCILIATA'))})
    return result
