"""Verified TAB prices are scoped to a customer, CAC, division, REF and period."""
from decimal import Decimal,InvalidOperation
from datetime import date
import streamlit as st


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


def submit_price(client,item,start,end,refresh,price_key,discount_key,saved):
    permissions=set(st.session_state.get('permessi',[]) or [])
    role=str(st.session_state.get('ruolo','')).strip().lower()
    user=st.session_state.get('user')
    if not user or not (role in ('admin','amministrazione') or permissions & {'DIREZIONE','AMMINISTRAZIONE'}):
        st.session_state['tab_price_error']='Accesso non autorizzato.';return
    actor=(user.get('email') or user.get('username') or user.get('id')) if isinstance(user,dict) else user
    if work_key(item) in saved:return
    discount=bool(st.session_state.get(discount_key,False))
    try:
        save_verified_price(client,item,0 if discount else st.session_state.get(price_key),start,end,actor,
          'Prezzo verificato manualmente dalla pagina Anomalie',discount)
    except ValueError as exc:st.session_state['tab_price_error']=str(exc);return
    except Exception as exc:
        message=str(getattr(exc,'message',''))
        st.session_state['tab_price_error']=message if 'periodo sovrapposto' in message else 'Prezzo non salvato. Aggiorna la pagina e riprova; nessuna anomalia è stata chiusa.'
        return
    saved.add(work_key(item))
    st.session_state.pop('tab_price_workitem',None)
    refresh()
    st.session_state['tab_price_saved']=f"Prezzo salvato per {item['Struttura']} · {item['REF']}."


def work_key(item):
    return tuple(str(item.get(k) or '') for k in ('Divisione','Codice struttura','CAC','REF'))


def render_price_editor(client,rows,refresh,verified=None):
    # A new snapshot is built when the outer filters or report are refreshed.
    _render_entry(client,worklist(rows),refresh,verified or [],set())


@st.fragment
def _render_entry(client,items,refresh,verified,saved):
    notice=st.session_state.pop('tab_price_saved',None)
    error=st.session_state.pop('tab_price_error',None)
    if not items and not notice and not error:return
    st.subheader('Inserimento rapido prezzi')
    if notice:st.success(notice)
    if error:st.error(error)
    def structure_key(item):
        return item['Struttura'], item['Codice struttura']

    structures=sorted({structure_key(item) for item in items},key=lambda key:(key[0].casefold(),key[1]))
    selected=None
    if structures:
        selected=st.selectbox('Cerca struttura per nome o codice',[None,*structures],
            format_func=lambda key:f'{key[0]} · {key[1]}' if key else 'Tutte le strutture',
            key='tab_price_entry_structure',
            on_change=lambda:st.session_state.pop('tab_price_workitem',None),
            help='Digita il nome o il codice e scegli una struttura. Per cercare in tutte le strutture, imposta il filtro Struttura anomalie TAB su Tutte.')
    remaining={work_key(item):item for item in items
        if (selected is None or structure_key(item)==selected) and work_key(item) not in saved}
    st.caption(f'{len(remaining)} REF da lavorare nella selezione · {len(saved)} prezzi salvati in questa serie. Il riepilogo delle anomalie si aggiorna al ricalcolo.')
    if saved and st.button('Ricalcola anomalie',key='reconcile_saved_prices'):
        st.rerun()
    if not remaining:
        if selected:st.info('Nessun altro REF da lavorare per questa struttura. Puoi sceglierne un’altra.')
        return
    pick=st.selectbox('REF da completare',list(remaining),format_func=lambda key:
        f"{remaining[key]['Struttura']} · {key[0]} · {key[3]} · {len(remaining[key]['Documenti'])} documenti",
        key='tab_price_workitem')
    item=remaining[pick]
    st.write(f"**{item['Struttura']} · {item['REF']}** — {item['Descrizione']}")
    try:start,end=daily_period(item,verified)
    except ValueError as exc:st.info(str(exc));return
    form_key='tab_price_'+str(pick)
    price_key=form_key+'_amount';discount_key=form_key+'_discount'
    with st.form(form_key):
        st.number_input('Prezzo unitario verificato (€)',min_value=0.0,value=None,step=0.01,format='%.4f',key=price_key)
        st.checkbox('Sconto merce: prezzo verificato €0',key=discount_key)
        st.form_submit_button('Salva e passa al prossimo REF',type='primary',on_click=submit_price,
          args=(client,item,start,end,refresh,price_key,discount_key,saved))
