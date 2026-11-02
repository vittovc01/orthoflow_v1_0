"""Complete reconciliation reporting; no writes and no inferred unbilled status."""
from collections import defaultdict
from decimal import Decimal
from io import BytesIO
from jj_reconciliation import allocated, confirmed_associations, decimal, line_rows, proposals, text


def unit_price(line):
    if line.get('price') is not None and text(line.get('price')):
        return decimal(line['price'])
    if line.get('total') is not None and line.get('quantity'):
        return decimal(line['total']) / int(line['quantity'])
    return None


def order_matches(a,b):
    return (a.get('cac')==b.get('cac') and a.get('ref')==b.get('ref')
      and text(a.get('po')).upper()==text(b.get('po')).upper()
      and bool(text(a.get('po')))
      and (not a.get('invoice') or not b.get('invoice') or a['invoice'].split('-')[0]==b['invoice'].split('-')[0]))


def build_report(records,links,closure_id):
    closing=next(r for r in records if r['id']==closure_id and r['kind']=='CHIUSURA')
    records=[r for r in records if r['division']==closing['division']]
    by_id={r['id']:r for r in records}
    active=[l for l in links if not l.get('revoked_at') and l['closure_id']==closure_id]
    used=defaultdict(int)
    for l in active:used[l['closure_line']]+=int(l['quantity'])
    candidate_cc=defaultdict(set)
    candidates=proposals(records,links,closure_id)
    for row in candidates:candidate_cc[row['closure_line']].add(row['implant_id'])
    orders=list(line_rows([r for r in records if r['kind']=='ORDINE']))
    bills=[];prices=[];adjustments=[];unmatched=[]
    for a in closing['payload']['lines']:
        q=int(a['quantity']);linked=used[a['key']];left=q-linked
        price=unit_price(a)
        matches=[(o,b) for o,b in orders if order_matches(a,b)]
        if q<0:
            adjustments.append({'Tipo':'Reso prodotto','Presidio':a.get('customer'),'CAC':a.get('cac'),'PO':a.get('po'),'Fattura':a.get('invoice'),'REF':a['ref'],'Quantità':q,'Fatturato':float(decimal(a.get('total'))),'Verifica':'Da verificare nei documenti di reso'})
            continue
        reason=''
        if left>0:
            if closing.get('pending_payload'):reason='Revisione della chiusura da verificare'
            elif any(o.get('pending_payload') for o,b in matches):reason='Revisione della distinta ordine da verificare'
            elif not matches:
                same_po=any(b.get('cac')==a.get('cac') and text(b.get('po')).upper()==text(a.get('po')).upper() for o,b in orders)
                reason='REF o fattura non presente nella distinta ordine' if same_po else 'Distinta ordine mancante: caricare le righe di questo PO'
            elif candidate_cc[a['key']]:reason=f"Associazione da confermare: {len(candidate_cc[a['key']])} documenti CC compatibili"
            elif all(b['quantity']<=allocated(links,o['id'],b['key'],'ORDINE') for o,b in matches):reason='Quantità delle righe ordine già utilizzata'
            else:
                source=[(r,l) for r,l in line_rows(records) if r['kind']=='IMPIANTO' and l.get('cac')==a.get('cac') and l.get('ref')==a.get('ref')]
                available=[(r,l) for r,l in source if l['quantity']>allocated(links,r['id'],l['key'],'IMPIANTO')]
                if not source:reason='REF assente nelle CC assegnate al presidio: verificare il TAB o assegnare i presidi in Strumenti avanzati'
                elif not available:reason='Quantità delle CC già utilizzata da altre associazioni: verificare TAB e ordini'
                elif all(r.get('pending_payload') for r,l in available):reason='Revisione delle CC da verificare in Strumenti avanzati'
                elif a.get('date') and all(r['payload'].get('event_date') and r['payload']['event_date']>a['date'] for r,l in available):reason='Date delle CC successive alla fattura: verificare le date nel TAB'
                else:reason='Nessuna combinazione compatibile: verificare lotto, data e quantità della distinta ordine'
        linked_cc=sorted({text(by_id[l['implant_id']]['payload'].get('encounter')) or by_id[l['implant_id']]['source_key'] for l in active if l['closure_line']==a['key']})
        row={'Stato':'ASSOCIATA' if left==0 else ('PARZIALE' if linked else 'NON ASSOCIATA'),
          'Presidio':a.get('customer') or a.get('cac'),'CAC':a.get('cac'),'PO':a.get('po'),'Fattura':a.get('invoice'),
          'REF':a['ref'],'Descrizione':a.get('description') or next((b.get('description','') for o,b in matches if b.get('description')),''),
          'Quantità fatturata':q,'Quantità associata':linked,'Quantità residua':left,
          'Prezzo chiusura':float(price) if price is not None else None,'Totale riga':float(decimal(a.get('total'))),
          'Valore associato':float(price*linked) if price is not None else None,'Valore residuo':float(price*left) if price is not None else None,
          'CC associate':', '.join(linked_cc),'Motivo / azione':reason}
        bills.append(row)
        if left>0:unmatched.append({'Fonte':'CHIUSURA','Documento':closing['source_key'],**row,'Quantità da riscontrare':left})
        if not matches:
            prices.append({'Esito':'NON CONFRONTABILE','Presidio':row['Presidio'],'PO':a.get('po'),'Fattura':a.get('invoice'),'REF':a['ref'],
              'Prezzo ordine':None,'Prezzo chiusura':float(price) if price is not None else None,'Motivo / azione':'Caricare la distinta ordine con il prezzo o il totale riga'})
        for o,b in matches:
            order_price=unit_price(b)
            linked_q=sum(int(l['quantity']) for l in active if l['closure_line']==a['key'] and l['order_id']==o['id'] and l['order_line']==b['key'])
            compare_q=linked_q or min(q,int(b['quantity']))
            delta=price-order_price if price is not None and order_price is not None else None
            if delta is not None and abs(delta)<Decimal('.005') and abs(delta*compare_q)<Decimal('.01'):continue
            prices.append({'Esito':'DIFFERENZA PREZZO' if delta is not None else 'PREZZO MANCANTE',
              'Presidio':row['Presidio'],'CAC':a.get('cac'),'PO':a.get('po'),'Ordine':o['payload'].get('number') or o['payload'].get('po'),
              'Fattura':a.get('invoice'),'REF':a['ref'],'Descrizione':b.get('description',''),
              'Prezzo ordine':float(order_price) if order_price is not None else None,'Prezzo chiusura':float(price) if price is not None else None,
              'Differenza unit.':float(delta) if delta is not None else None,'Quantità confrontata':compare_q,
              'Scostamento sulla quantità':float(delta*compare_q) if delta is not None else None,
              'Base confronto':'Quantità associata' if linked_q else 'Quantità da associare: confronto da verificare',
              'Motivo / azione':'Verificare il prezzo applicato; lo scostamento è chiusura meno ordine' if delta is not None else 'Integrare il prezzo o il totale della distinta ordine'})
    for record,line in line_rows([r for r in records if r['kind']!='CHIUSURA']):
        left=int(line['quantity'])-allocated(links,record['id'],line['key'],record['kind'])
        if left<=0:continue
        unmatched.append({'Fonte':record['kind'],'Documento':record['source_key'],'Presidio':line.get('customer') or record['payload'].get('customer'),
          'CAC':line.get('cac') or record['payload'].get('cac'),'PO':line.get('po') or record['payload'].get('po'),'Fattura':line.get('invoice'),
          'REF':line['ref'],'Descrizione':line.get('description',''),'Cartella clinica':record['payload'].get('encounter',''),
          'Riferimento intervento':record['payload'].get('reference',''),'Data intervento':record['payload'].get('event_date',''),
          'Lotto':line.get('lot',''),'Quantità da riscontrare':left,
          'Motivo / azione':'Revisione del documento da verificare' if record.get('pending_payload') else ('Presidio da assegnare' if not line.get('cac') else 'Non riscontrato con le fonti caricate; può riferirsi ad altri mesi')})
    for row in closing['payload'].get('economic_rows',[]):
        raw=row.get('raw_data',{})
        adjustments.append({'Tipo':raw.get('Order Type[O. Sub Type]') or 'Rettifica economica','Presidio':row.get('account_name'),'CAC':row.get('cac'),
          'PO':row.get('riferimento_cliente'),'Fattura':raw.get('Order Transactions[O. Invoice Number]'),'REF':row.get('codice'),
          'NIS':float(decimal(row.get('nis'))),'Fatturato':float(decimal(row.get('invoiced_sales',row.get('totale_riga')))),
          'Verifica':'Verificare con la chiusura ufficiale; non è una quantità impiantata'})
    source_ids={closure_id}|{l[side+'_id'] for l in active for side in ('order','implant')}
    pending=[r for r in records if r['id'] in source_ids and r.get('pending_payload')]
    open_rows=[r for r in bills if r['Quantità residua']>0]
    open_qty=sum(r['Quantità residua'] for r in open_rows)
    open_value=sum((decimal(r['Valore residuo']) for r in open_rows),Decimal(0))
    blockers=[]
    if open_rows:blockers.append({'Motivo':f"{len(open_rows)} righe fatturate ancora da associare ({open_qty} pezzi)",'Azione':'Apri Da risolvere: carica le distinte mancanti o conferma le associazioni disponibili'})
    if pending:blockers.append({'Motivo':f'{len(pending)} documenti collegati con revisione pendente','Azione':'Apri Strumenti avanzati e verifica le revisioni'})
    status={'can_close':not blockers,'open_rows':len(open_rows),'open_quantity':open_qty,'open_value':float(open_value),
      'associated_quantity':sum(r['Quantità associata'] for r in bills),'price_differences':sum(r['Esito']=='DIFFERENZA PREZZO' for r in prices),
      'price_unverified':sum(r['Esito']!='DIFFERENZA PREZZO' for r in prices),'pending_revisions':len(pending),'blockers':blockers,'candidates':candidates}
    summary=[{'Voce':'Divisione','Valore':closing['division']},{'Voce':'Mese','Valore':closing['source_key']},
      {'Voce':'Esito','Valore':'CHIUSO' if closing.get('closed_at') else ('PRONTO ALLA CONFERMA' if not blockers else 'VERIFICA PARZIALE')},
      {'Voce':'Fatturato ufficiale della chiusura','Valore':float(decimal(closing['payload'].get('invoiced_sales')))},
      {'Voce':'Pezzi associati','Valore':status['associated_quantity']},{'Voce':'Righe chiusura da associare','Valore':len(open_rows)},
      {'Voce':'Pezzi chiusura da associare','Valore':open_qty},{'Voce':'Valore prodotti da associare','Valore':float(open_value)},
      {'Voce':'Confronti con differenze prezzo','Valore':status['price_differences']},{'Voce':'Confronti prezzo non verificabili','Valore':status['price_unverified']},
      {'Voce':'Ambito Non associati','Valore':'TAB e ordini: residui su tutte le fonti caricate, anche di altri mesi. Non equivalgono a materiale non fatturato.'},
      {'Voce':'Prezzi','Valore':'Confronto fra chiusura e distinta ordine. Prezzi ricavati dal totale / quantità quando necessario. Le differenze sono avvisi da verificare.'},
      {'Voce':'Regole di chiusura','Valore':'Tutte le quantità positive della chiusura associate; nessuna revisione pendente su fonti collegate; conferma finale di prezzi, resi e rettifiche.'}]
    associations=confirmed_associations(records,links,closure_id)
    link_by_id={l['id']:l for l in active}
    for row in associations:
        link=link_by_id[row['Collegamento']]
        o=next(l for l in by_id[link['order_id']]['payload']['lines'] if l['key']==link['order_line'])
        c=next(l for l in closing['payload']['lines'] if l['key']==link['closure_line'])
        op,cp=unit_price(o),unit_price(c)
        row.update({'Prezzo ordine':float(op) if op is not None else None,'Prezzo chiusura':float(cp) if cp is not None else None,
                    'Differenza unit.':float(cp-op) if op is not None and cp is not None else None})
    return {'status':status,'Riepilogo':summary,'Righe chiusura':bills,'Associazioni':associations,
      'Non associati':unmatched,'Prezzi da verificare':prices,'Resi e rettifiche':adjustments,'Blocchi chiusura':blockers}


def excel_report(report):
    """Serialize the application report in memory; text never becomes a formula."""
    import xlsxwriter
    output=BytesIO()
    workbook=xlsxwriter.Workbook(output,{'in_memory':True,'strings_to_formulas':False,'strings_to_urls':False})
    header=workbook.add_format({'bold':True,'bg_color':'#234768','font_color':'white','text_wrap':True,'valign':'vcenter'})
    currency=workbook.add_format({'num_format':'#,##0.00'})
    unit_format=workbook.add_format({'num_format':'#,##0.0000'})
    for name,rows in report.items():
        if name=='status':continue
        sheet=workbook.add_worksheet(name);sheet.hide_gridlines(2);sheet.freeze_panes(1,0)
        if not rows:rows=[{'Esito':'Nessuna riga per questa sezione'}]
        columns=list(dict.fromkeys(k for row in rows for k in row))
        for col,key in enumerate(columns):
            sheet.write(0,col,key,header)
            width=48 if key in ('Motivo / azione','Azione','Valore','Riferimento intervento') else (34 if key in ('Descrizione','Presidio') else 20)
            sheet.set_column(col,col,width)
        sheet.set_row(0,32)
        for index,row in enumerate(rows,1):
            for col,key in enumerate(columns):
                value=row.get(key)
                if value is None:continue
                fmt=(unit_format if key in ('Prezzo ordine','Prezzo chiusura','Differenza unit.') else currency) if isinstance(value,(float,Decimal)) else None
                sheet.write(index,col,float(value) if isinstance(value,Decimal) else value,fmt)
        sheet.autofilter(0,0,len(rows),len(columns)-1)
    workbook.close()
    return output.getvalue()
