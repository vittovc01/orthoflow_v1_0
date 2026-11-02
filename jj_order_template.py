"""Order templates generated from the current OrthoFlow customer registry."""
from io import BytesIO
from collections import Counter
from jj_reconciliation import DIVISIONS, normalized, resolve_cac, text

HEADERS=['PO cliente','Numero fattura','REF','Descrizione','Totale riga','Quantità','Prezzo unitario','Numero ordine J&J','Presidio','Codice struttura','CAC','Riferimento intervento']

def structure_catalog(customers,records=()):
    result={}
    names=Counter(normalized(text(c.get('descrizione')) or text(c.get('descrizione_cliente')) or text(c.get('codice_cliente'))) for c in customers)
    for customer in customers:
        code=text(customer.get('codice_cliente'))
        name=text(customer.get('descrizione')) or text(customer.get('descrizione_cliente')) or code
        if not code:continue
        city=text(customer.get('citta'));province=text(customer.get('provincia'))
        label=' · '.join(v for v in (name,city,code) if v)
        explicit={text(l.get('cac') or r['payload'].get('cac')) for r in records for l in r['payload'].get('lines',[])
                  if text(l.get('customer_code') or r['payload'].get('customer_code'))==code and text(l.get('cac') or r['payload'].get('cac'))}
        cac=next(iter(explicit)) if len(explicit)==1 else (resolve_cac('',name,'',records) if not explicit and names[normalized(name)]==1 else '')
        row={'Scelta struttura':label,'Struttura':name,'Codice struttura':code,'Città':city,'Provincia':province,'CAC J&J':cac}
        if code in result and result[code]!=row:raise ValueError('Anagrafica discordante per il codice struttura '+code)
        result[code]=row
    return sorted(result.values(),key=lambda r:(normalized(r['Struttura']),r['Codice struttura']))

def order_template(customers,records,division):
    import xlsxwriter
    if division not in DIVISIONS:raise ValueError('Divisione non valida')
    catalog=structure_catalog(customers,records)
    if not catalog:raise ValueError('Anagrafica strutture vuota: impossibile creare un modello completo')
    output=BytesIO()
    wb=xlsxwriter.Workbook(output,{'in_memory':True,'strings_to_formulas':False,'strings_to_urls':False})
    head=wb.add_format({'bold':True,'bg_color':'#234768','font_color':'white','text_wrap':True,'valign':'vcenter'})
    note=wb.add_format({'text_wrap':True,'valign':'top'})
    money=wb.add_format({'num_format':'#,##0.00','bg_color':'#FFF5DC'})
    unit=wb.add_format({'num_format':'#,##0.0000','bg_color':'#EDF3F7'})
    auto=wb.add_format({'num_format':'@','bg_color':'#EDF3F7'})
    entry=wb.add_format({'num_format':'@'})
    orders=wb.add_worksheet('Ordini');registry=wb.add_worksheet('Anagrafica strutture');settings=wb.add_worksheet('Impostazioni')
    for sh in (orders,registry,settings):sh.hide_gridlines(2)
    orders.freeze_panes(1,3);orders.set_row(0,36)
    orders.write_row(0,0,HEADERS,head)
    orders.set_column('A:C',20,entry);orders.set_column('D:D',42,entry);orders.set_column('E:E',18,money)
    orders.set_column('F:F',14);orders.set_column('G:G',20,unit);orders.set_column('H:H',24,entry)
    orders.set_column('I:I',64,entry);orders.set_column('J:K',22,auto);orders.set_column('L:L',36,entry)
    registry.write_row(0,0,list(catalog[0]),head);registry.set_row(0,32);registry.freeze_panes(1,0)
    for index,row in enumerate(catalog,1):registry.write_row(index,0,list(row.values()),entry)
    registry.set_column('A:A',82);registry.set_column('B:B',58);registry.set_column('C:C',22)
    registry.set_column('D:D',32);registry.set_column('E:F',18)
    registry.autofilter(0,0,len(catalog),5)
    wb.define_name('ElencoStrutture',f"='Anagrafica strutture'!$A$2:$A${len(catalog)+1}")
    lookup=f"'Anagrafica strutture'!$A$2:$F${len(catalog)+1}"
    for index in range(1,1001):
        row=index+1
        orders.write_formula(index,6,f'=IF(OR(E{row}="",F{row}="",F{row}<=0),"",E{row}/F{row})',unit,'')
        for column,lookup_column in ((9,3),(10,6)):
            expression=f'VLOOKUP(I{row},{lookup},{lookup_column},FALSE)'
            if column==10:expression=f'IF({expression}=0,"",{expression})'
            orders.write_formula(index,column,f'=IF(I{row}="","",IFERROR({expression},""))',auto,'')
    orders.data_validation('I2:I1001',{'validate':'list','source':'=ElencoStrutture','error_type':'stop','error_title':'Scegli una struttura','error_message':'Seleziona una struttura dall’elenco OrthoFlow.'})
    orders.data_validation('F2:F1001',{'validate':'integer','criteria':'>','value':0,'error_type':'stop','error_message':'Inserisci una quantità intera maggiore di zero.'})
    orders.autofilter('A1:L1001')
    settings.write_row(0,0,['Campo','Valore'],head)
    instructions=[('Divisione',division),('Compilazione','Compila una riga per REF e ordine. Incolla Totale riga e Quantità: il prezzo unitario si calcola automaticamente.'),
      ('Strutture','Presidio: scegli dal menu. Codice struttura e CAC sono formule. Tutte le anagrafiche di OrthoFlow sono incluse.'),
      ('Codici','Codice struttura = codice cliente interno. CAC = codice J&J, compilato solo se già associato in OrthoFlow.'),
      ('CAC mancante','Non inserire il codice cliente nel CAC. Se manca, verifica la corrispondenza cliente/presidio nella Chiusura guidata prima di importare gli ordini.'),
      ('Aggiornamento','Scarica un nuovo modello dall’app per ricevere le nuove anagrafiche. I file già scaricati mantengono il proprio elenco.'),
      ('File cumulativo','Puoi aggiungere gli ordini dei mesi successivi allo stesso file. Conserva tutte le righe di ogni ordine: l’import aggiorna la distinta completa, senza sommare le quantità già caricate.'),
      ('Formule','Celle azzurre: calcoli automatici. Non compilarle. Totale riga = importo complessivo dei pezzi della riga.'),
      ('Lotti','Il lotto non è obbligatorio negli ordini; gli abbinamenti restano distinti fra Trauma e Protesica.')]
    for i,row in enumerate(instructions,1):settings.write_row(i,0,row,note);settings.set_row(i,45)
    settings.set_column('A:A',24);settings.set_column('B:B',100)
    wb.close()
    return output.getvalue()
