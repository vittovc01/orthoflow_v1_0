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
from tab_agents import agent_name, payload_agent

DIVISIONS=('TRAUMA','PROTESICA')
BASE_ACCOUNTS={'6977429':'H- CIVILE SAPRI','7533619':'FARM.P.O.UMBERTO I NOCERA INFERIORE','6977437':'H- CIVILE BATTIPAGLIA'}
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

def clinical_reference(value):
    """Keep CC suffixes/leading zeroes; never infer an absent CC or mistyped year."""
    value=text(value)
    cc=re.search(r'(?i)\bCC\s*[:.n°]*\s*(\d+(?:/\d+)?)\s+DEL',value)
    when=re.search(r'(?i)\bDEL\s*(\d{1,2}[/-]\d{1,2}[/-](?:\d{4}|\d{2}))\b',value)
    return (cc[1] if cc else '',date(when[1]) if when else '')

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
    result=dict(BASE_ACCOUNTS)
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
    if customer:
        matches.update(c for c,name in BASE_ACCOUNTS.items() if normalized(customer)==normalized(name))
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

def prepare_tab(content,filename,division,records=(),mapping=None,customers=()):
    if division not in DIVISIONS:raise ValueError('Divisione non valida')
    records=[r for r in records if r['division']==division]
    _,frame=select_frame(content,filename,['TIPO','NUMERO','CLIENTE','ARTICOLO','LOTTO','RIFERIMENTO','DATA','QUANTITA','SERIE','CAUSALE'])
    documents={};mapping=dict(mapping or {});cac_cache={}
    customer_codes=defaultdict(set)
    for c in customers:
        if text(c.get('codice_cliente')):customer_codes[normalized(text(c.get('descrizione')) or text(c.get('descrizione_cliente')))].add(text(c['codice_cliente']))
    prior={r['source_key']:r['payload'] for r in records if r['kind']=='IMPIANTO'}
    for customer in frame['CLIENTE'].dropna().map(text).unique():
        if normalized(customer)=='ASL SALERNO':
            if mapping.get(customer):raise ValueError('ASL Salerno: assegnare Sapri, Nocera o Battipaglia al singolo documento')
            continue
        previous={r['payload'].get('cac') for r in records if r['kind']=='IMPIANTO' and normalized(r['payload'].get('customer'))==normalized(customer) and r['payload'].get('cac')}
        if len(previous)==1:mapping.setdefault(customer,next(iter(previous)))
    for index,row in frame.iterrows():
        if all(not text(v) for v in row):continue
        cause=normalized(row['CAUSALE'])
        if (division=='TRAUMA' and ('TRAUMA' not in cause or 'PROTESICA' in cause)) or (division=='PROTESICA' and ('TRAUMA' in cause or ('PROTESICA' not in cause and cause!='AVVENUTO IMPIANTO'))):raise ValueError(f'Riga {index+2}: causale diversa da {division}')
        docdate=date(row['DATA'])
        if not docdate:raise ValueError(f'Riga {index+2}: data documento non valida')
        customer=text(row['CLIENTE']);reference=text(row['RIFERIMENTO'])
        encounter,event=clinical_reference(reference)
        source_event=event
        number=text(row['NUMERO']).removesuffix('.0')
        if not number or not text(row['TIPO']):raise ValueError(f'Riga {index+2}: documento incompleto')
        key='|'.join([docdate[:4],text(row['TIPO']),text(row['SERIE']),number])
        if customer not in cac_cache:cac_cache[customer]='' if normalized(customer)=='ASL SALERNO' else (mapping.get(customer,'') or resolve_cac('',customer,'',records))
        cac=cac_cache[customer]
        previous=prior.get(key,{})
        same_source_customer=normalized(previous.get('source_customer') or previous.get('customer'))==normalized(customer)
        if same_source_customer:
            cac=previous.get('cac') or cac
            if previous.get('reference')==reference and previous.get('document_date')==docdate:
                event=previous.get('event_date') or event
                encounter=previous.get('encounter') or encounter
        try:quantity=positive_quantity(row['QUANTITA'])
        except ValueError as exc:raise ValueError(f'Riga {index+2}, documento {key}, REF {text(row["ARTICOLO"])}: {exc}') from exc
        line={'ref':ref(row['ARTICOLO']),'lot':text(row['LOTTO']).upper(),'quantity':quantity,
              'expiry':date(row.get('SCADENZA')),'description':text(row.get('DESCRIZIONE')),'source_rows':[int(index)+2]}
        payload={'customer':customer,'cac':cac,'reference':reference,'encounter':encounter,'event_date':event,'source_ref_date':source_event,'document_date':docdate,'lines':[]}
        if same_source_customer and previous.get('source_customer'):
            payload['source_customer']=customer
            payload['customer']=previous['customer']
        agent=text(row.get('AGENTE')).removesuffix('.0')
        if agent.isdigit():agent=str(int(agent))
        if agent and agent!='0':
            if agent.isdigit():
                payload['agent_code']=agent
                payload['agent']=agent_name(agent)
            else:payload['agent']=agent
        matched_codes=customer_codes[normalized(customer)]
        if same_source_customer and previous.get('source_customer') and previous.get('customer_code'):payload['customer_code']=previous['customer_code']
        elif len(matched_codes)==1:payload['customer_code']=next(iter(matched_codes))
        elif previous.get('customer_code') and same_source_customer:payload['customer_code']=previous['customer_code']
        if key in documents and any(documents[key][k]!=payload[k] for k in ['customer','reference','document_date']):raise ValueError(f'Documento {key} con intestazioni discordanti')
        if key in documents and any(documents[key].get(k)!=payload.get(k) for k in ('agent_code','agent')):raise ValueError(f'Documento {key} con agenti diversi nelle righe: verificare il gestionale')
        documents.setdefault(key,payload)['lines'].append(line)
    result=[]
    for key,payload in documents.items():
        payload['lines']=group_lines(payload['lines'],'IMPIANTO')
        for l in payload['lines']:l['cac']=payload['cac'];l['customer']=payload['customer']
        result.append({'source_key':key,'payload':payload})
    if not result:raise ValueError('TAB senza righe utilizzabili')
    return result

def prepare_orders(content,filename,division,records=(),customers=()):
    if division not in DIVISIONS:raise ValueError('Divisione non valida')
    records=[r for r in records if r['division']==division]
    allframes=frames(content,filename)
    settings=allframes.get('Impostazioni')
    if settings is not None and {'Campo','Valore'}.issubset(settings.columns):
        declared=[text(r['Valore']).upper() for _,r in settings.iterrows() if text(r['Campo'])=='Divisione']
        if declared and (len(set(declared))!=1 or declared[0]!=division):raise ValueError('Questo file ordini appartiene a una divisione diversa: caricalo nella chiusura '+(declared[0] or 'corretta'))
    from jj_order_template import structure_catalog
    catalog=structure_catalog(customers,records)
    by_code={r['Codice struttura']:r for r in catalog}
    by_label={r['Scelta struttura']:r for r in catalog}
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
        internal_code=text(row.get('CODICE STRUTTURA')).removesuffix('.0')
        selected=by_label.get(customer) or by_code.get(internal_code)
        if internal_code and not selected:raise ValueError(f'Riga {index+2}: codice struttura non presente nell’anagrafica OrthoFlow')
        if selected:
            if internal_code and internal_code!=selected['Codice struttura']:raise ValueError(f'Riga {index+2}: codice struttura discordante dalla selezione')
            if customer and customer!=selected['Scelta struttura'] and normalized(customer)!=normalized(selected['Struttura']):raise ValueError(f'Riga {index+2}: struttura e codice cliente discordanti')
            internal_code=selected['Codice struttura'];customer=selected['Struttura']
        if not po:raise ValueError(f'Riga {index+2}: PO cliente mancante')
        cac=resolve_cac(row.get('CAC'),'','',records) if text(row.get('CAC')) else (selected['CAC J&J'] if selected else resolve_cac('',customer,po,records))
        if selected and selected['CAC J&J'] and cac!=selected['CAC J&J']:raise ValueError(f'Riga {index+2}: CAC diverso dalla corrispondenza verificata della struttura')
        if internal_code and cac==internal_code:raise ValueError(f'Riga {index+2}: il codice struttura interno non è il CAC J&J')
        if not cac:raise ValueError(f'Riga {index+2}, PO {po}: presidio non univoco. Verifica la corrispondenza cliente/presidio negli strumenti avanzati oppure compila il CAC J&J corretto')
        invoice=text(row.get('NUMERO FATTURA'))
        key=cac+'|'+('JJ|'+number if number else 'PO|'+po)
        prior=[r for r in records if r['kind']=='ORDINE' and r['division']==division and r['payload'].get('cac')==cac]
        same_number=[r for r in prior if number and r['payload'].get('number')==number]
        same_po=[r for r in prior if r['payload'].get('po')==po and (not number or not r['payload'].get('number') or r['payload'].get('number')==number)]
        previous=same_number or same_po
        if len(previous)>1:raise ValueError(f'PO {po}: più ordini esistenti, compila il numero ordine J&J')
        if previous:
            key=previous[0]['source_key']
            if not number:number=previous[0]['payload'].get('number','')
            if not invoice:invoice=previous[0]['payload'].get('invoice','')
        q=positive_quantity(row['QUANTITA']);price=money(row['PREZZO UNITARIO']) if text(row.get('PREZZO UNITARIO')) else (money(decimal(row['TOTALE RIGA'])/q) if text(row.get('TOTALE RIGA')) else None)
        total=money(row['TOTALE RIGA']) if text(row.get('TOTALE RIGA')) else (money(decimal(price)*q) if price is not None else None)
        if price is not None and total is not None and abs(decimal(price)*q-decimal(total))>Decimal('.02'):raise ValueError(f'Riga {index+2}: prezzo × quantità diverso dal totale')
        line={'ref':ref(row['REF']),'lot':text(row.get('LOTTO')).upper(),'quantity':q,'price':price,'total':total,
              'cac':cac,'customer':customer or accounts(records).get(cac,cac),'invoice':invoice,'po':po,
              'description':text(row.get('DESCRIZIONE')),'source_rows':[int(index)+2]}
        payload={'customer':line['customer'],'cac':cac,'po':po,'number':number,'invoice':invoice,'reference':text(row.get('RIFERIMENTO INTERVENTO')),'lines':[]}
        if internal_code:
            line['customer_code']=internal_code;payload['customer_code']=internal_code
        if key in documents and documents[key].get('customer_code')!=payload.get('customer_code'):raise ValueError(f'PO {po}: codici struttura discordanti nello stesso ordine')
        if key in documents and documents[key]['number']!=number:raise ValueError(f'PO {po} riutilizzato: aggiorna prima il numero J&J dell’ordine già presente')
        if key in documents and documents[key]['invoice']!=invoice:
            if not number:raise ValueError(f'PO {po} su più fatture: usa il numero ordine J&J per distinguere gli ordini')
            documents[key]['invoice']=''
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
                  'Cartella clinica':text(implant['payload'].get('encounter')),
                  'Riscontro documento':'Candidato per riga dello stesso presidio; verificare CC',
                  'Data intervento':implant['payload'].get('event_date',''),'Lotto impianto':c.get('lot',''),
                  'Metodo':'REF e quantità, lotto ordine non disponibile' if not b.get('lot') else 'REF e lotto',
                  'Differenza prezzo':float(decimal(a['price'])-decimal(b['price'])) if a.get('price') is not None and b.get('price') is not None else None})
    sides={side:Counter((r[side+'_id'],r[side+'_line']) for r in result) for side in ('closure','order','implant')}
    for r in result:r['Univoco']=all(sides[side][(r[side+'_id'],r[side+'_line'])]==1 for side in sides)
    return result

def allocation_plan(records,links,closure_id,candidates=None):
    """Reviewable FIFO draft, never a saved or proven clinical attribution.

    Consume capacities on all three sources globally. Sorting is stable, with
    earlier invoice deadlines first and older eligible CCs first. Ambiguous
    undated/unidentified CCs require manual review instead of arbitrary ranking.
    """
    candidates=proposals(records,links,closure_id) if candidates is None else candidates
    by_id={r['id']:r for r in records}
    capacity={}
    for record,line in line_rows(records):
        side={'CHIUSURA':'closure','ORDINE':'order','IMPIANTO':'implant'}[record['kind']]
        capacity[(side,record['id'],line['key'])]=max(0,line['quantity']-allocated(links,record['id'],line['key'],record['kind']))
    alternatives=defaultdict(set)
    for row in candidates:
        alternatives[(row['closure_id'],row['closure_line'],row['order_id'],row['order_line'])].add((row['implant_id'],row['implant_line']))
    def sort_key(row):
        closing=by_id[row['closure_id']]
        line=next(l for l in closing['payload']['lines'] if l['key']==row['closure_line'])
        return (line.get('date') or '9999-12-31',row['closure_id'],row['closure_line'],
          len(alternatives[(row['closure_id'],row['closure_line'],row['order_id'],row['order_line'])]),
          row['order_id'],row['order_line'],row.get('Data intervento') or '9999-12-31',row['implant_id'],row['implant_line'])
    result=[]
    for row in sorted(candidates,key=sort_key):
        if row['closure_id']!=closure_id or not row.get('Cartella clinica'):continue
        if not row.get('Univoco') and not row.get('Data intervento'):continue
        keys=[(side,row[side+'_id'],row[side+'_line']) for side in ('closure','order','implant')]
        quantity=min([int(row['quantity'])]+[capacity.get(k,0) for k in keys])
        if quantity<=0:continue
        for key in keys:capacity[key]-=quantity
        count=len(alternatives[(row['closure_id'],row['closure_line'],row['order_id'],row['order_line'])])
        result.append({**row,'quantity':quantity,'Alternative compatibili':count,
          'Criterio proposta':'Corrispondenza senza alternative' if row.get('Univoco') else 'CC meno recente prima (FIFO): da verificare',
          'proposal_criterion':'UNIQUE_CANDIDATE' if row.get('Univoco') else 'FIFO_CC_DATE_DRAFT'})
    return result


def residuals(records,links):
    result=[]
    for record,line in line_rows(records):
        kind=record['kind'];rid=record['id'];q=line['quantity'];used=allocated(links,rid,line['key'],kind)
        result.append({'Tipo':kind,'Documento':record['source_key'],'REF':line['ref'],'Presidio':line.get('customer',''),
          'Quantità':q,'Quantità riconciliata':used,'Residuo':q-used,'Valore riga':float(line['total']) if line.get('total') is not None else None,
          'Stato':'REVISIONE DA VERIFICARE' if record.get('pending_payload') else (('RESO VERIFICATO IN CHIUSURA' if record.get('closed_at') else 'RESO DA VERIFICARE') if q<0 else ('NON RISCONTRATO CON LE FONTI CARICATE' if used<q else 'QUANTITÀ RICONCILIATA'))})
    return result

def closing_orders(records,closure_id):
    closing=next(r for r in records if r['id']==closure_id)
    grouped={}
    for line in closing['payload']['lines']:
        key=(line['cac'],line.get('po',''),line.get('invoice',''),line.get('type','VENDITA'))
        if key not in grouped:
            present=[r['payload'].get('number') or 'PO '+r['payload'].get('po','') for r in records if r['kind']=='ORDINE' and r['division']==closing['division'] and r['payload'].get('cac')==key[0] and r['payload'].get('po')==key[1]]
            grouped[key]={'Presidio':line.get('customer',''),'CAC':key[0],'PO cliente':key[1],'Fattura':key[2],
              'Tipo':key[3],'Righe prodotto':0,'Totale EUR':0.0,'Ordini presenti':', '.join(present),
              'Da acquisire':'Documento di reso' if line['quantity']<0 else ('Righe ordine presenti: verificare completezza' if present else 'Distinta ordine')}
        grouped[key]['Righe prodotto']+=1
        grouped[key]['Totale EUR']+=float(line.get('total') or 0)
    return list(grouped.values())


def confirmed_associations(records,links,closure_id):
    """One row per confirmed allocation: an order may span several clinical records."""
    by_id={r['id']:r for r in records}
    result=[]
    for link in links:
        if link.get('revoked_at') or link['closure_id']!=closure_id:continue
        closing,order,implant=[by_id[link[side+'_id']] for side in ('closure','order','implant')]
        c=next(x for x in closing['payload']['lines'] if x['key']==link['closure_line'])
        o=next(x for x in order['payload']['lines'] if x['key']==link['order_line'])
        i=next(x for x in implant['payload']['lines'] if x['key']==link['implant_line'])
        difference=float(decimal(c['price'])-decimal(o['price'])) if c.get('price') is not None and o.get('price') is not None else None
        result.append({'Ordine':order['payload'].get('number') or order['payload'].get('po') or o.get('po'),
          'PO':c.get('po'),'Fattura':c.get('invoice'),'Presidio':c.get('customer') or c.get('cac'),'CAC':c.get('cac'),
          'Cartella clinica':text(implant['payload'].get('encounter')),'Riferimento intervento':implant['payload'].get('reference',''),
          'Agente':payload_agent(implant['payload']),
          'Data intervento':implant['payload'].get('event_date',''),'Documento impianto':implant['source_key'],
          'REF':c['ref'],'Descrizione':o.get('description') or i.get('description',''),'Lotto impianto':i.get('lot',''),
          'Quantità':link['quantity'],'Prezzo ordine':o.get('price'),'Prezzo chiusura':c.get('price'),'Differenza unit.':difference,
          'Collegamento':link['id'],'Metodo':link['method'],'Utente':link['actor'],'Data':link['created_at']})
    return result
