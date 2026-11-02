"""Read-only intervention reconciliation across all loaded billing months."""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from jj_reconciliation import normalized, text
from jj_report import unit_price
from tab_agents import payload_agent

def build_status(records,links,division=None,structure=None,year=None):
    records=[r for r in records if division is None or r['division']==division]
    by_id={r['id']:r for r in records}
    lines={(r['id'],l['key']):l for r in records for l in r['payload']['lines']}
    groups={};record_group={};details=[];associations=[];prices=[];documents=[]
    for r in records:
        if r['kind']!='IMPIANTO':continue
        p=r['payload'];customer=text(p.get('customer')) or text(p.get('cac')) or 'Presidio da assegnare'
        event=text(p.get('event_date'));cc=text(p.get('encounter'))
        # Keep undated records visible; invoice dates never filter clinical dates.
        if year and event and event[:4]!=str(year):continue
        identity=(r['division'],text(p.get('cac')) or text(p.get('customer_code')) or normalized(customer),cc,event)
        if not cc or not event or not p.get('cac'):identity+=('DOCUMENTO',r['id'])
        key='|'.join(map(str,identity));record_group[r['id']]=key
        group=groups.setdefault(key,{'Divisione':r['division'],'Stato':'','Struttura':customer,'CAC':text(p.get('cac')),
          'Codice struttura':text(p.get('customer_code')),'Cartella clinica':cc,'Data intervento':event,
          '_documents':set(),'_names':set(),'_agents':set(),'_orders':set(),'_po':set(),'_invoices':set(),'_months':set(),
          '_reasons':set(),'_price_diffs':set(),'_price_missing':set(),'_value':Decimal(0),'_missing_value':False,
          'Pezzi impiantati':0,'Pezzi associati':0,'Pezzi chiusi':0})
        group['_documents'].add(r['source_key'])
        group['_names'].add(customer)
        group['_agents'].add(payload_agent(p))
        if r.get('pending_payload'):group['_reasons'].add('Revisione del TAB da verificare')
        if not p.get('cac'):group['_reasons'].add('Presidio da assegnare')
        if not cc:group['_reasons'].add('Cartella clinica mancante')
        if not event:group['_reasons'].add('Data intervento mancante')
    if structure:
        groups={k:g for k,g in groups.items() if structure in g['_names']}
        record_group={rid:k for rid,k in record_group.items() if k in groups}
    active=[l for l in links if not l.get('revoked_at') and l.get('implant_id') in by_id]
    capacities=defaultdict(int)
    for link in active:
        for side in ('closure','order','implant'):capacities[(link.get(side+'_id'),link.get(side+'_line'))]+=int(link['quantity'])
    implant_links=defaultdict(list);pair_links=defaultdict(list);used=defaultdict(int)
    for link in active:
        try:
            c,o,i=[by_id[link[s+'_id']] for s in ('closure','order','implant')]
            a,b,d=[lines[(link[s+'_id'],link[s+'_line'])] for s in ('closure','order','implant')]
        except KeyError:
            if link['implant_id'] in record_group:groups[record_group[link['implant_id']]]['_reasons'].add('Collegamento con documento mancante: da verificare')
            continue
        valid=(c['kind']=='CHIUSURA' and o['kind']=='ORDINE' and i['kind']=='IMPIANTO'
          and c['division']==o['division']==i['division'] and int(link['quantity'])>0
          and a['ref']==b['ref']==d['ref'] and bool(a.get('cac')) and a.get('cac')==b.get('cac')==d.get('cac')
          and bool(text(a.get('po'))) and text(a.get('po')).upper()==text(b.get('po')).upper()
          and (not a.get('invoice') or not b.get('invoice') or a['invoice'].split('-')[0]==b['invoice'].split('-')[0])
          and all(capacities[(link[s+'_id'],link[s+'_line'])]<=int(lines[(link[s+'_id'],link[s+'_line'])]['quantity']) for s in ('closure','order','implant')))
        if not valid:
            if i['id'] in record_group:groups[record_group[i['id']]]['_reasons'].add('Collegamento discordante o quantità eccessiva: da verificare')
            continue
        pending=any(r.get('pending_payload') for r in (c,o,i))
        invoice=text(a.get('invoice'));invoice_ok=bool(invoice and invoice!='0')
        item=(link,c,o,i,a,b,d,pending,invoice_ok)
        implant_links[(i['id'],d['key'])].append(item)
        pair_links[(c['id'],a['key'],o['id'],b['key'])].append(item)
        for side in ('closure','order','implant'):used[(link[side+'_id'],link[side+'_line'])]+=int(link['quantity'])
        if i['id'] not in record_group:continue
        group=groups[record_group[i['id']]]
        order=text(o['payload'].get('number')) or text(b.get('po'));q=int(link['quantity']);cp,op=unit_price(a),unit_price(b)
        group['_orders'].add(order);group['_po'].add(text(a.get('po')));group['_invoices'].add(invoice);group['_months'].add(c['source_key'])
        if cp is None:group['_missing_value']=True
        else:group['_value']+=cp*q
        if pending:group['_reasons'].add('Revisione di un documento collegato da verificare')
        if not invoice_ok:group['_reasons'].add('Numero fattura mancante o non identificato')
        associations.append({'Divisione':i['division'],'Struttura':group['Struttura'],'Cartella clinica':group['Cartella clinica'],
          'Data intervento':group['Data intervento'],'Documento TAB':i['source_key'],'REF':d['ref'],'Descrizione':d.get('description') or b.get('description',''),
          'Lotto':d.get('lot',''),'Quantità':q,'Ordine':order,'PO':a.get('po'),'Fattura':invoice,'Mese fatturazione':c['source_key'],
          'Prezzo ordine':float(op) if op is not None else None,'Prezzo chiusura':float(cp) if cp is not None else None,
          'Valore fatturato associato':float(cp*q) if cp is not None else None,'Stato associazione':'DA VERIFICARE' if pending or not invoice_ok else 'CONFERMATA',
          'Mese confermato':'Sì' if c.get('closed_at') else 'No','Metodo':link.get('method',''),'Collegamento':link['id']})
    relevant_cac={g['CAC'] for g in groups.values() if g['CAC']}
    orders=defaultdict(list);orders_by_ref=defaultdict(list)
    for r in records:
        if r['kind']=='ORDINE':
            for l in r['payload']['lines']:
                orders[(r['division'],l.get('cac'),l['ref'],text(l.get('po')).upper())].append((r,l))
                orders_by_ref[(r['division'],l.get('cac'),l['ref'])].append((r,l))
    for r in records:
        if r['kind']!='CHIUSURA':continue
        for a in r['payload']['lines']:
            if int(a['quantity'])<=0:continue
            if structure and a.get('cac') not in relevant_cac and a.get('customer')!=structure:continue
            candidates=[(o,b) for o,b in orders[(r['division'],a.get('cac'),a['ref'],text(a.get('po')).upper())]
              if not a.get('invoice') or not b.get('invoice') or a['invoice'].split('-')[0]==b['invoice'].split('-')[0]]
            for o,b in candidates or [(None,None)]:
                cp=unit_price(a);op=unit_price(b) if b else None
                allocated=pair_links.get((r['id'],a['key'],o['id'],b['key']),[]) if o else []
                group_keys={record_group[item[3]['id']] for item in allocated if item[3]['id'] in record_group}
                if allocated and not group_keys:continue
                qty=sum(int(item[0]['quantity']) for item in allocated if item[3]['id'] in record_group) if allocated else min(int(a['quantity']),int(b['quantity'])) if b else int(a['quantity'])
                delta=cp-op if cp is not None and op is not None else None
                if delta is not None and abs(delta)<Decimal('.005') and abs(delta*qty)<Decimal('.01'):continue
                verdict='DIFFERENZA PREZZO' if delta is not None else ('DISTINTA ORDINE MANCANTE' if b is None else 'PREZZO MANCANTE')
                price_key=(r['id'],a['key'],o['id'] if o else None,b['key'] if b else None)
                for key in group_keys:groups[key]['_price_diffs' if delta is not None else '_price_missing'].add(price_key)
                prices.append({'Divisione':r['division'],'Esito':verdict,'Struttura':a.get('customer') or a.get('cac'),'CAC':a.get('cac'),
                  'Cartelle cliniche':', '.join(sorted({groups[k]['Cartella clinica'] for k in group_keys})),
                  'Ordine':o['payload'].get('number') or b.get('po') if o else '', 'PO':a.get('po'),'Fattura':a.get('invoice'),
                  'Mese fatturazione':r['source_key'],'REF':a['ref'],'Quantità confrontata':qty,
                  'Prezzo ordine':float(op) if op is not None else None,'Prezzo chiusura':float(cp) if cp is not None else None,
                  'Differenza unit.':float(delta) if delta is not None else None,'Scostamento sulla quantità':float(delta*qty) if delta is not None else None,
                  'Base confronto':'Quantità associata alle CC selezionate' if allocated else 'Documento non associato: attribuzione alla CC da verificare',
                  'Azione':'Verificare il prezzo fatturato rispetto alla distinta ordine' if delta is not None else 'Caricare la distinta ordine o integrare prezzo / totale riga'})
    for r in records:
        if r['kind']!='IMPIANTO' or r['id'] not in record_group:continue
        group=groups[record_group[r['id']]]
        for l in r['payload']['lines']:
            qty=int(l['quantity']);items=implant_links.get((r['id'],l['key']),[])
            associated=sum(int(item[0]['quantity']) for item in items)
            closed=sum(int(item[0]['quantity']) for item in items if not item[7] and item[8])
            group['Pezzi impiantati']+=qty;group['Pezzi associati']+=associated;group['Pezzi chiusi']+=closed
            if associated<qty:
                available=[(o,b) for o,b in orders_by_ref[(r['division'],l.get('cac'),l['ref'])] if int(b['quantity'])>used[(o['id'],b['key'])]]
                group['_reasons'].add('Ordine presente: verificare fattura e associazione' if available else 'Quantità non riscontrata con le fonti caricate: verificare distinte e chiusure')
            details.append({'Divisione':r['division'],'Struttura':group['Struttura'],'CAC':group['CAC'],'Cartella clinica':group['Cartella clinica'],
              'Data intervento':group['Data intervento'],'Documento TAB':r['source_key'],'REF':l['ref'],'Descrizione':l.get('description',''),
              'Lotto':l.get('lot',''),'Scadenza':l.get('expiry',''),'Quantità impiantata':qty,'Quantità associata':associated,'Quantità chiusa':closed,'Quantità da chiudere':qty-closed})
    for r in records:
        if r['kind']=='IMPIANTO':continue
        for l in r['payload']['lines']:
            if int(l['quantity'])<=0:continue
            if structure and l.get('cac') not in relevant_cac and l.get('customer')!=structure:continue
            remaining=int(l['quantity'])-used[(r['id'],l['key'])]
            if remaining>0:documents.append({'Divisione':r['division'],'Fonte':r['kind'],'Struttura':l.get('customer') or l.get('cac'),
              'CAC':l.get('cac'),'Documento':r['source_key'],'Ordine':r['payload'].get('number',''),'PO':l.get('po'),
              'Fattura':l.get('invoice'),'REF':l['ref'],'Quantità da associare':remaining,
              'Motivo':'Revisione da verificare' if r.get('pending_payload') else 'Da associare alle CC: non attribuito al periodo interventi selezionato'})
    closed_rows=[];open_rows=[]
    for key,g in groups.items():
        remaining=g['Pezzi impiantati']-g['Pezzi chiusi']
        reasons=g['_reasons'];closed=remaining==0 and not reasons and g['Pezzi impiantati']>0
        row={k:v for k,v in g.items() if not k.startswith('_')}
        row.update({'Stato':'CHIUSO CON ORDINE E FATTURA' if closed else ('DA VERIFICARE' if remaining==0 else 'PARZIALMENTE CHIUSO' if g['Pezzi chiusi'] else 'DA CHIUDERE'),
          'Agente':', '.join(sorted(g['_agents'])),'Documenti TAB':', '.join(sorted(g['_documents'])),'Pezzi da chiudere':remaining,
          'Ordini':', '.join(sorted(g['_orders'])),'PO':', '.join(sorted(g['_po'])),'Fatture':', '.join(sorted(g['_invoices'])),
          'Mesi fatturazione':', '.join(sorted(g['_months'])),'Valore fatturato associato':None if g['_missing_value'] else float(g['_value']),
          'Differenze prezzo':len(g['_price_diffs']),'Prezzi non confrontabili':len(g['_price_missing']),
          'Motivo / azione':'; '.join(sorted(reasons))})
        (closed_rows if closed else open_rows).append(row)
    timestamp=datetime.now(ZoneInfo('Europe/Rome')).isoformat(timespec='seconds')
    status={'closed':len(closed_rows),'open':len(open_rows),'remaining_quantity':sum(r['Pezzi da chiudere'] for r in open_rows),
      'price_differences':sum(p['Esito']=='DIFFERENZA PREZZO' for p in prices),'price_missing':sum(p['Esito']!='DIFFERENZA PREZZO' for p in prices),'read_at':timestamp}
    summary=[{'Voce':'Dati letti il (Italia)','Valore':timestamp},{'Voce':'Divisione','Valore':division or 'Tutte'},
      {'Voce':'Struttura','Valore':structure or 'Tutte'},{'Voce':'Anno intervento','Valore':str(year or 'Tutti')},
      {'Voce':'Interventi chiusi con ordine e fattura','Valore':status['closed']},{'Voce':'Interventi da chiudere / verificare','Valore':status['open']},
      {'Voce':'Pezzi da chiudere','Valore':status['remaining_quantity']},{'Voce':'Differenze prezzo','Valore':status['price_differences']},
      {'Voce':'Prezzi non confrontabili','Valore':status['price_missing']},
      {'Voce':'Ambito','Valore':'Interventi dai TAB caricati. Una CC è chiusa quando tutte le quantità sono associate a ordine e fattura, senza revisioni pendenti. Documenti senza presidio, CC o data restano separati da verificare. La conferma del mese è uno stato distinto.'},
      {'Voce':'Periodo','Valore':'Il filtro anno riguarda la data intervento; fatture di altri mesi sono incluse nei collegamenti. Le date mancanti restano visibili.'},
      {'Voce':'Documenti non associati','Valore':'Fatture, ordini e prezzi non attribuiti a CC restano inclusi per divisione e struttura, anche fuori dal periodo interventi. Un residuo non dimostra che il materiale non sia fatturato.'},
      {'Voce':'Fonte prezzi','Valore':'Confronto fra distinta ordine e chiusura ufficiale; i prezzi mancanti non sono considerati uguali. Non è una verifica delle offerte commerciali.'}]
    return {'status':status,'Riepilogo':summary,'Interventi chiusi':closed_rows,'Interventi da chiudere':open_rows,
      'Dettaglio prodotti':details,'Ordini e fatture':associations,'Prezzi da verificare':prices,'Documenti da associare':documents}
