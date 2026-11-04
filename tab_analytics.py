"""Charts reuse the TAB management aggregates; quantities are not interventions."""
from collections import Counter
import re
import pandas as pd
import streamlit as st


def chart_tables(report):
    columns={'Interventi distinti':'Interventi'}
    tables={key:[{columns.get(k,k):v for k,v in r.items()} for r in report[key]]
      for key in ('Per struttura','Per agente','Per periodo')}
    duplicate_names=Counter((r['Divisione'],r['Struttura']) for r in tables['Per struttura'])
    for row in tables['Per struttura']:
        label=row['Struttura']
        if duplicate_names[(row['Divisione'],label)]>1:
            label+=' · '+str(row.get('CAC') or row.get('Codice struttura') or 'Presidio da verificare')
        row['Struttura grafico']=label
    tables['Per struttura'].sort(key=lambda r:(-r['Interventi'],r['Struttura'],r['Divisione']))
    tables['Per agente'].sort(key=lambda r:(-r['Interventi'],r['Agente'],r['Divisione']))
    tables['Per periodo'].sort(key=lambda r:(r['Periodo'],r['Divisione']))
    return tables


def bar(rows,dimension,measure,unit=False):
    data=[r for r in rows if r.get(measure) is not None]
    if not data:
        st.info('Valori non disponibili: completa i prezzi per visualizzare il grafico economico.');return
    tooltips=[{'field':dimension,'type':'nominal','title':'Struttura' if dimension=='Struttura grafico' else dimension},
      {'field':'Divisione','type':'nominal'}, {'field':'Interventi','type':'quantitative','format':'d'},
      {'field':'Pezzi','type':'quantitative','format':'d'}]
    if unit:tooltips.extend([{'field':measure,'type':'quantitative','format':',.2f'},
      {'field':'Righe senza prezzo','type':'quantitative','format':'d'}])
    st.vega_lite_chart(pd.DataFrame(data),{
      'mark':{'type':'bar'},'height':max(240,min(1000,28*len({r[dimension] for r in data}))),
      'encoding':{'y':{'field':dimension,'type':'nominal','sort':{'field':measure,'order':'descending','op':'sum'},
        'axis':{'title':None,'labelLimit':360}},
        'x':{'field':measure,'type':'quantitative','title':measure+(' (€)' if unit else ''),
          'axis':{'format':',.0f' if unit else 'd','tickMinStep':1}},
        'color':{'field':'Divisione','type':'nominal','scale':{'domain':['TRAUMA','PROTESICA'],'range':['#1769aa','#159d82']}},
        'tooltip':tooltips}},use_container_width=True)


def monthly(rows,measure):
    data=[{**r,'Mese':r['Periodo']+'-01'} for r in rows if re.fullmatch(r'\d{4}-\d{2}',r['Periodo']) and r.get(measure) is not None]
    if not data:
        st.info('Nessun valore mensile disponibile nei filtri selezionati.');return
    st.vega_lite_chart(pd.DataFrame(data),{'mark':{'type':'line','point':True},'height':300,
      'encoding':{'x':{'field':'Mese','type':'temporal','title':'Mese intervento','axis':{'format':'%m/%Y'}},
        'y':{'field':measure,'type':'quantitative','axis':{'format':'d' if measure=='Interventi' else ',.0f','tickMinStep':1}},
        'color':{'field':'Divisione','type':'nominal','scale':{'domain':['TRAUMA','PROTESICA'],'range':['#1769aa','#159d82']}},
        'tooltip':[{'field':'Mese','type':'temporal','format':'%m/%Y'},{'field':'Divisione','type':'nominal'},
          {'field':measure,'type':'quantitative','format':'d' if measure=='Interventi' else ',.2f'}]}},use_container_width=True)


def render_analytics(report):
    tables=chart_tables(report)
    structures=tables['Per struttura'];periods=tables['Per periodo'];agents=tables['Per agente']
    st.subheader('Interventi per struttura')
    st.caption('Numero di interventi distinti, anche senza prezzo: stessa struttura, cartella clinica e data contano una volta nella propria linea, anche con più prodotti o documenti TAB. Trauma e Protesica sono separate nel grafico.')
    if not structures:
        st.info('Nessun intervento nei filtri selezionati.');return
    all_structures=st.checkbox('Mostra tutte le strutture nei grafici',value=False,key='analytics_all_structures')
    names=list(dict.fromkeys(r['Struttura grafico'] for r in structures))
    ranked=sorted(names,key=lambda name:-sum(r['Interventi'] for r in structures if r['Struttura grafico']==name))
    chosen=set(ranked if all_structures else ranked[:20])
    chart_rows=[r for r in structures if r['Struttura grafico'] in chosen]
    if len(chosen)<len(names):st.caption(f'Grafico: prime {len(chosen)} strutture per numero di interventi. La tabella sotto contiene tutte le {len(names)} strutture.')
    bar(chart_rows,'Struttura grafico','Interventi')
    table=pd.DataFrame(structures)
    ordered=['Struttura','Divisione','Interventi','Pezzi','Valore atteso valorizzato','Valore fatturato associato','Righe senza prezzo','CAC','Codice struttura']
    st.dataframe(table[[c for c in ordered if c in table]],hide_index=True,use_container_width=True)
    st.subheader('Andamento mensile degli interventi')
    monthly(periods,'Interventi')
    undated=sum(r['Interventi'] for r in periods if r['Periodo']=='Data mancante')
    if undated:st.caption(f'{undated} interventi con data mancante restano nei totali e nelle strutture, ma non sono collocati nel grafico mensile.')
    left,right=st.columns(2)
    with left:
        st.subheader('Valore atteso per struttura')
        st.caption('Valore dei prodotti con prezzo disponibile, per data intervento. Se mancano prezzi, il valore è parziale; non rappresenta il fatturato effettivo.')
        bar(chart_rows,'Struttura grafico','Valore atteso valorizzato',unit=True)
    with right:
        st.subheader('Andamento mensile del valore atteso')
        monthly(periods,'Valore atteso valorizzato')
    st.subheader('Interventi per agente')
    st.caption('Gli agenti non assegnati restano visibili. Un intervento con più agenti può comparire in più gruppi: questi conteggi non vanno sommati per ottenere il totale generale.')
    if agents:bar(agents,'Agente','Interventi')
    for title in ('Per agente','Per periodo'):
        with st.expander(title):st.dataframe(pd.DataFrame(tables[title]),hide_index=True,use_container_width=True)
