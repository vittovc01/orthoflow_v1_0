"""TAB-backed management read model. Never writes legacy stock/intervention tables."""
from collections import defaultdict
from decimal import Decimal
import re
from jj_reconciliation import date,decimal,digest,normalized,text
from tab_agents import payload_agent

def customer_code(payload,customers):
    code=text(payload.get('customer_code'))
    if code:
        return (code,'') if any(text(c.get('codice_cliente'))==code for c in customers) else ('','Codice struttura non presente in anagrafica')
    names={text(l.get('customer')) for l in payload.get('lines',[]) if text(l.get('customer'))}
    name=text(payload.get('customer')) or (next(iter(names)) if len(names)==1 else '')
    matches={text(c.get('codice_cliente')) for c in customers if text(c.get('codice_cliente')) and normalized(text(c.get('descrizione')) or text(c.get('descrizione_cliente')))==normalized(name)}
    if len(matches)==1:return next(iter(matches)),''
    return '', 'Struttura non univoca in anagrafica' if matches else 'Struttura non trovata in anagrafica'

def price_index(headers,connections,prices):
    heads={}
    for h in headers:
        if text(h.get('stato_record')).upper() not in ('','ATTIVO','ACTIVE'):continue
        start,end=date(h.get('data_inizio')),date(h.get('data_fine'))
        if (text(h.get('data_inizio')) and not start) or (text(h.get('data_fine')) and not end):continue
        heads[h['id']]=(h,start,end)
    clients=defaultdict(set)
    for c in connections:clients[c['offerta_id']].add(text(c.get('codice_cliente')))
    exact=defaultdict(list);canonical=defaultdict(list)
    for p in prices:
        header=heads.get(p.get('offerta_id'))
        if not header or p.get('prezzo') is None or not text(p.get('prezzo')):continue
        h,start,end=header
        try:value=decimal(p['prezzo'])
        except ValueError:continue
        if value<0:continue
        for code in clients[h['id']]:
            product=text(p.get('codice')).upper();entry=(product,value,h['id'],start,end)
            prefix=(code,text(h.get('linea')).upper())
            exact[(*prefix,product)].append(entry)
            canonical[(*prefix,re.sub(r'[^A-Z0-9]','',product))].append(entry)
    return exact,canonical

def offered_price(index,code,division,ref,event):
    exact,canonical=index
    valid=lambda x: not ((x[3] or x[4]) and not event) and not (event and ((x[3] and event<x[3]) or (x[4] and event>x[4])))
    target=text(ref).upper();matches=[x for x in exact.get((code,division,target),[]) if valid(x)]
    if not matches:
        matches=[x for x in canonical.get((code,division,re.sub(r'[^A-Z0-9]','',target)),[]) if valid(x)]
        if len({x[0] for x in matches})>1:return None,[], 'REF ambiguo nelle offerte'
    if not matches:return None,[],'Prezzo offerta mancante o offerta non valida alla data intervento'
    if len({x[1] for x in matches})!=1:return None,[],'Più offerte valide con prezzi diversi'
    return matches[0][1],sorted({x[2] for x in matches}),''

def management_report(records,links,customers,headers,connections,prices,status_builder,division=None,structure=None,year=None,agent=None):
    status=status_builder(records,links,division,structure,year)
    source={(r['division'],r['source_key']):r for r in records if r['kind']=='IMPIANTO'}
    index=price_index(headers,connections,prices)
    grouping={};interventions=[]
    for h in status['Interventi chiusi']+status['Interventi da chiudere']:
        documents=h['Documenti TAB'].split(', ')
        identifier=digest([h['Divisione'],h['CAC'] or h['Struttura'],h['Cartella clinica'],h['Data intervento'],documents if not h['CAC'] or not h['Cartella clinica'] or not h['Data intervento'] else []])[:16]
        for doc in documents:grouping[(h['Divisione'],doc)]=identifier
        interventions.append({'ID intervento TAB':identifier,**h})
    rows=[];issues=[];row_lookup={};associated=defaultdict(Decimal);missing_amount=set();by_intervention=defaultdict(list)
    for a in status['Ordini e fatture']:
        key=(a['Divisione'],a['Documento TAB'],a['REF'],a['Lotto'])
        if a['Valore fatturato associato'] is not None:associated[key]+=decimal(a['Valore fatturato associato'])
        else:missing_amount.add(key)
    for d in status['Dettaglio prodotti']:
        r=source[(d['Divisione'],d['Documento TAB'])];p=r['payload'];name=payload_agent(p)
        if agent and name!=agent:continue
        code,reason=customer_code(p,customers)
        price,offers,price_reason=offered_price(index,code,d['Divisione'],d['REF'],d['Data intervento']) if code else (None,[],reason)
        reason=reason or price_reason
        key=(d['Divisione'],d['Documento TAB'],d['REF'],d['Lotto'])
        row={'ID intervento TAB':grouping[(d['Divisione'],d['Documento TAB'])],**d,'Codice struttura':code,'Agente':name,
          'Periodo':d['Data intervento'][:7] if d['Data intervento'] else 'Data mancante',
          'Prezzo offerta':float(price) if price is not None else None,'Valore atteso':float(price*d['Quantità impiantata']) if price is not None else None,
          'Valore fatturato associato':None if key in missing_amount else float(associated[key]),'Offerte':', '.join(map(str,offers)),'Motivo / azione':reason}
        rows.append(row);row_lookup[key]=row;by_intervention[row['ID intervento TAB']].append(row)
        if reason:issues.append({**row,'Esito':'VALORIZZAZIONE DA VERIFICARE'})
    selected_ids={r['ID intervento TAB'] for r in rows}
    for h in interventions:
        if h['ID intervento TAB'] not in selected_ids:continue
        own=by_intervention[h['ID intervento TAB']]
        h['Righe senza prezzo']=sum(r['Valore atteso'] is None for r in own)
        h['Valore atteso valorizzato']=float(sum((decimal(r['Valore atteso']) for r in own if r['Valore atteso'] is not None),Decimal(0)))
        h['Agente']=', '.join(sorted({r['Agente'] for r in own}))
        if agent:
            h['Pezzi impiantati']=sum(r['Quantità impiantata'] for r in own)
            h['Pezzi associati']=sum(r['Quantità associata'] for r in own)
            h['Pezzi chiusi']=sum(r['Quantità chiusa'] for r in own)
            h['Pezzi da chiudere']=sum(r['Quantità da chiudere'] for r in own)
            h['Valore fatturato associato']=None if any(r['Valore fatturato associato'] is None for r in own) else float(sum((decimal(r['Valore fatturato associato']) for r in own),Decimal(0)))
            h['Stato intervento completo']=h.pop('Stato')
    interventions=[h for h in interventions if h['ID intervento TAB'] in selected_ids]
    allocations=[]
    for a in status['Ordini e fatture']:
        own=row_lookup.get((a['Divisione'],a['Documento TAB'],a['REF'],a['Lotto']))
        if not own:continue
        allocations.append({'ID intervento TAB':own['ID intervento TAB'],**a,'Agente':own['Agente'],'Prezzo offerta':own['Prezzo offerta']})
        if a['Prezzo chiusura'] is None:
            issues.append({**a,'Agente':own['Agente'],'Esito':'PREZZO FATTURA MANCANTE','Motivo / azione':'Verificare il valore della chiusura ufficiale'});continue
        if own['Prezzo offerta'] is None:continue
        delta=decimal(a['Prezzo chiusura'])-decimal(own['Prezzo offerta']);q=a['Quantità']
        if abs(delta)>=Decimal('.005') or abs(delta*q)>=Decimal('.01'):
            issues.append({**a,'Agente':own['Agente'],'Prezzo offerta':own['Prezzo offerta'],'Differenza unit.':float(delta),
              'Scostamento sulla quantità':float(delta*q),'Esito':'FATTURA DIVERSA DALL’OFFERTA','Motivo / azione':'Verificare prezzo fatturato e offerta della struttura alla data intervento'})
    if agent:
        for h in interventions:
            own=[a for a in allocations if a['ID intervento TAB']==h['ID intervento TAB']]
            for target,column in [('Ordini','Ordine'),('PO','PO'),('Fatture','Fattura'),('Mesi fatturazione','Mese fatturazione')]:
                h[target]=', '.join(sorted({text(a.get(column)) for a in own if text(a.get(column))}))
    def aggregate(dimension):
        groups={}
        for r in rows:
            key=(r['Divisione'],r[dimension]);g=groups.setdefault(key,{'Divisione':r['Divisione'],dimension:r[dimension],
              '_ids':set(),'_missing_actual':False,'Pezzi':0,'Valore atteso valorizzato':Decimal(0),'Valore fatturato associato':Decimal(0),'Righe senza prezzo':0})
            g['_ids'].add(r['ID intervento TAB']);g['Pezzi']+=r['Quantità impiantata']
            if r['Valore atteso'] is None:g['Righe senza prezzo']+=1
            else:g['Valore atteso valorizzato']+=decimal(r['Valore atteso'])
            if r['Valore fatturato associato'] is not None:g['Valore fatturato associato']+=decimal(r['Valore fatturato associato'])
            else:g['_missing_actual']=True
        return [{k:float(v) if isinstance(v,Decimal) else v for k,v in g.items() if not k.startswith('_')}|{'Interventi distinti':len(g['_ids']),'Valore fatturato associato':None if g['_missing_actual'] else float(g['Valore fatturato associato'])} for g in groups.values()]
    by_structure=aggregate('Struttura');by_agent=aggregate('Agente')
    by_period=aggregate('Periodo')
    summary=[{'Voce':'Report generato il (Italia)','Valore':status['status']['read_at']},
      {'Voce':'Fonte','Valore':'TAB del gestionale: unica fonte per queste analisi. Gli scarichi storici sono consultabili separatamente e non sono sommati.'},
      {'Voce':'Divisione','Valore':division or 'Tutte'},{'Voce':'Struttura','Valore':structure or 'Tutte'},{'Voce':'Anno intervento','Valore':year or 'Tutti'},
      {'Voce':'Agente','Valore':agent or 'Tutti'},{'Voce':'Interventi','Valore':len(interventions)},
      {'Voce':'Pezzi','Valore':sum(r['Quantità impiantata'] for r in rows)},
      {'Voce':'Valore atteso valorizzato','Valore':float(sum((decimal(r['Valore atteso']) for r in rows if r['Valore atteso'] is not None),Decimal(0)))},
      {'Voce':'Righe senza prezzo','Valore':sum(r['Valore atteso'] is None for r in rows)},
      {'Voce':'Valorizzazione','Valore':'Offerte della struttura, della divisione e valide alla data clinica. Valori attesi e fatturato associato sono misure distinte. Le righe senza prezzo non sono valorizzate a zero.'},
      {'Voce':'Conteggi','Valore':'Interventi distinti per struttura/CC/data; documenti con identificativi mancanti restano separati. Con più agenti, lo stesso intervento può comparire in più gruppi agente.'},
      {'Voce':'Magazzino','Valore':'Nessun movimento generato da importazione o consultazione TAB.'}]
    return {'Riepilogo':summary,'Interventi TAB':interventions,'Prodotti TAB':rows,'Per struttura':by_structure,'Per agente':by_agent,
      'Per periodo':by_period,'Prezzi da verificare':issues,'Ordini e fatture':allocations}
