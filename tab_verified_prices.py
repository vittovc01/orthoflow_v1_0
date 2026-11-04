"""Verified TAB prices are scoped to a customer, CAC, division, REF and period."""
from decimal import Decimal,InvalidOperation
from datetime import date


def add_verified_prices(catalogs,verified):
    customers,headers,connections,prices=catalogs
    for row in verified:
        identifier='verified:'+str(row['id'])
        headers.append({'id':identifier,'linea':row['linea'],'stato_record':'Attivo',
          'data_inizio':row['dal'],'data_fine':row['al'],'tab_verified':True,'cac':row['cac']})
        connections.append({'offerta_id':identifier,'codice_cliente':row['codice_cliente']})
        prices.append({'offerta_id':identifier,'codice':row['ref'],'prezzo':row['prezzo']})
    return customers,headers,connections,prices


def save_verified_price(client,scope,price,start,end,actor,note,discount=False):
    try:
        value=Decimal(str(price))
        if not value.is_finite() or (discount and value!=0) or (not discount and value<=0):raise ValueError
        if not isinstance(start,date) or not isinstance(end,date) or start>end:raise ValueError
        if not all(str(scope.get(k) or '').strip() for k in ('Codice struttura','Divisione','REF')):raise ValueError
        if scope['Divisione'] not in ('TRAUMA','PROTESICA') or not actor or not str(note).strip():raise ValueError
    except (ValueError,InvalidOperation):raise ValueError('Inserisci struttura, REF, prezzo, periodo e riferimento della verifica validi.') from None
    return client.rpc('tab_salva_prezzo_verificato',{'p_cliente':scope['Codice struttura'],
      'p_cac':str(scope.get('CAC') or ''),'p_linea':scope['Divisione'],'p_ref':scope['REF'].strip().upper(),
      'p_prezzo':str(value),'p_dal':start.isoformat(),'p_al':end.isoformat(),
      'p_utente':str(actor),'p_nota':str(note).strip(),'p_sconto':discount}).execute().data


def worklist(rows):
    groups={}
    for row in rows:
        if not row.get('Codice struttura') or not row.get('Data intervento'):continue
        key=tuple(row.get(k) for k in ('Divisione','Codice struttura','CAC','REF'))
        g=groups.setdefault(key,{**{k:row.get(k,'') for k in ('Divisione','Codice struttura','CAC','REF','Struttura','Descrizione')},'Documenti':set(),'Date':set(),'Motivi':set()})
        g['Documenti'].add(row.get('Documento TAB'));g['Date'].add(row['Data intervento']);g['Motivi'].add(row['Categoria'])
    return sorted(groups.values(),key=lambda r:(r['Struttura'],r['Divisione'],r['REF']))


def daily_period(item,verified):
    dates=sorted(item['Date']);first=date.fromisoformat(dates[0]);last=date.fromisoformat(dates[-1])
    start=first.replace(month=1,day=1);end=last.replace(month=12,day=31)
    own=[r for r in verified if all(str(r.get(k) or '')==str(item.get(v) or '') for k,v in
      [('codice_cliente','Codice struttura'),('cac','CAC'),('linea','Divisione'),('ref','REF')])]
    overlaps=[r for r in own if date.fromisoformat(r['dal'])<=end and date.fromisoformat(r['al'])>=start]
    if not overlaps:return start,end
    if len(overlaps)==1 and overlaps[0]['dal']<=dates[0] and overlaps[0]['al']>=dates[-1]:
        return date.fromisoformat(overlaps[0]['dal']),date.fromisoformat(overlaps[0]['al'])
    raise ValueError('Questo REF ha più periodi di prezzo: gestisci la variazione in Anagrafica prezzi.')


def render_price_editor(client,rows,refresh,verified=None):
    import streamlit as st
    items=worklist(rows)
    if not items:return
    st.subheader('Inserisci prezzo e risolvi per struttura')
    st.caption('Inserisci il prezzo una sola volta per lo stesso REF e struttura. Offerte, validità e variazioni sono consultabili in Anagrafica prezzi.')
    keys=list(range(len(items)))
    pick=st.selectbox('REF da completare',keys,format_func=lambda i:f"{items[i]['Struttura']} · {items[i]['Divisione']} · {items[i]['REF']} · {len(items[i]['Documenti'])} documenti",key='tab_price_workitem')
    item=items[pick]
    st.write(f"**{item['Struttura']} · {item['REF']}** — {item['Descrizione']}")
    try:start,end=daily_period(item,verified or [])
    except ValueError as exc:st.info(str(exc));return
    form_key='tab_price_'+str(tuple(item[k] for k in ('Divisione','Codice struttura','CAC','REF')))
    with st.form(form_key):
        price=st.number_input('Prezzo unitario verificato (€)',min_value=0.0,value=None,step=0.01,format='%.4f')
        discount=st.checkbox('Sconto merce: prezzo verificato €0')
        note='Prezzo verificato manualmente dalla pagina Anomalie'
        st.caption('Salva e ricalcola tutte le righe corrispondenti. Le eventuali differenze con la fattura restano segnalate.')
        submitted=st.form_submit_button('Salva prezzo e ricalcola anomalie',type='primary')
    if submitted:
        user=st.session_state.get('user')
        actor=(user.get('email') or user.get('username') or user.get('id')) if isinstance(user,dict) else user
        try:
            save_verified_price(client,item,0 if discount else price,start,end,actor,note,discount)
        except ValueError as exc:st.error(str(exc));return
        except Exception as exc:
            message=str(getattr(exc,'message',''))
            st.error(message if 'periodo sovrapposto' in message else 'Prezzo non salvato. Aggiorna la pagina e riprova; nessuna anomalia è stata chiusa.');return
        st.session_state['tab_price_saved']=f"Prezzo salvato per {item['Struttura']} · {item['REF']}. Tutte le righe corrispondenti sono state ricalcolate; il filtro struttura rimane selezionato."
        refresh();st.rerun()
