"""One structure price registry; original offers and verified prices stay distinct."""
from datetime import date,datetime
from zoneinfo import ZoneInfo
from decimal import Decimal
import pandas as pd
import streamlit as st
from jj_reconciliation import text,accounts
from tab_management import price_index,offered_price,customer_code
from tab_management_ui import tab_backend,base_catalogs,verified_catalog,tab_records,refresh,refresh_prices
from tab_verified_prices import add_verified_prices,save_verified_price


def catalog_rows(catalogs,verified,code,division,cac,at,descriptions=None):
    customers,headers,connections,prices=catalogs
    ids={c['offerta_id'] for c in connections if text(c.get('codice_cliente'))==code}
    heads={h['id']:h for h in headers if h['id'] in ids and text(h.get('linea')).upper()==division}
    original=[{'REF':text(p.get('codice')).upper(),'Descrizione':text(p.get('descrizione')),
      'Prezzo offerta':p.get('prezzo'),'Offerta':heads[p['offerta_id']].get('nome_offerta') or str(p['offerta_id']),
      'ID offerta':p['offerta_id'],'Riferimento offerta':heads[p['offerta_id']].get('note') or '', 'Valido dal':heads[p['offerta_id']].get('data_inizio'),
      'Valido al':heads[p['offerta_id']].get('data_fine'),'Stato':heads[p['offerta_id']].get('stato_record') or 'Attivo'}
      for p in prices if p.get('offerta_id') in heads]
    manual=[r for r in verified if r['codice_cliente']==code and r['linea']==division and str(r.get('cac') or '')==cac]
    combined=add_verified_prices([list(customers),list(headers),list(connections),list(prices)],manual)
    index=price_index(*combined[1:]);refs=sorted({r['REF'] for r in original}|{r['ref'] for r in manual})
    descriptions={**(descriptions or {}),**{r['REF']:r['Descrizione'] for r in original if r['Descrizione']}}
    effective=[]
    for ref in refs:
        value,offers,reason=offered_price(index,code,division,ref,at.isoformat(),cac)
        effective.append({'REF':ref,'Descrizione':descriptions.get(ref,''),
          'Prezzo applicato':float(value) if value is not None else None,
          'Fonte':'Manuale' if any(str(x).startswith('verified:') for x in offers) else 'Offerta' if value is not None else 'Da verificare',
          'Esito':reason or 'Applicabile','Offerta / verifica':', '.join('Prezzo manuale' if str(x).startswith('verified:') else str(heads.get(x,{}).get('nome_offerta') or x) for x in offers)})
    return effective,original,manual


def registry_presidi(records,customers,code,division):
    names=accounts(records);found={}
    for r in records:
        if r['kind']!='IMPIANTO' or r['division']!=division:continue
        if customer_code(r['payload'],customers)[0]!=code:continue
        cac=text(r['payload'].get('cac'));found[cac]=names.get(cac) or text(r['payload'].get('customer')) or 'Struttura'
    if not found:found['']='Struttura'
    return found


def render_registry():
    st.title('Anagrafica prezzi')
    st.caption('Consulta offerte e prezzi manuali della struttura. Le modifiche manuali valgono solo per la struttura e il presidio selezionati; l’offerta originale resta consultabile.')
    if st.button('Aggiorna anagrafica prezzi'):
        from legacy_price_recovery import recovery_audit
        recovery_audit.clear();refresh()
    if st.session_state.get('registry_saved'):st.success(st.session_state.pop('registry_saved'))
    try:
        client=tab_backend();catalogs=base_catalogs(client);verified=verified_catalog(client);records,_=tab_records(client)
    except Exception:
        st.error('Anagrafica prezzi non disponibile. Premi Aggiorna anagrafica prezzi per riprovare.');return
    customers=catalogs[0]
    options={text(c.get('codice_cliente')):text(c.get('descrizione')) or text(c.get('descrizione_cliente')) or text(c.get('codice_cliente')) for c in customers if text(c.get('codice_cliente'))}
    if not options:st.info('Nessuna struttura registrata.');return
    code=st.selectbox('Struttura prezzi',sorted(options,key=lambda k:(options[k],k)),format_func=lambda k:options[k]+' · '+k)
    division=st.radio('Linea prezzi',['TRAUMA','PROTESICA'],horizontal=True)
    presidi=registry_presidi(records,customers,code,division)
    # Retain saved manual scopes even if no corresponding TAB is currently loaded.
    names=accounts(records)
    for r in verified:
        if r['codice_cliente']==code and r['linea']==division:
            cac=str(r.get('cac') or '');presidi.setdefault(cac,names.get(cac) or ('TAB senza presidio Customer' if not cac else 'Presidio '+cac))
    cac=st.selectbox('Presidio prezzi',list(presidi),format_func=lambda c:presidi[c])
    at=st.date_input('Consulta prezzi alla data',value=datetime.now(ZoneInfo('Europe/Rome')).date())
    descriptions={text(l.get('ref')).upper():text(l.get('description')) for r in records if r['kind']=='IMPIANTO' and r['division']==division and customer_code(r['payload'],customers)[0]==code for l in r['payload']['lines'] if text(l.get('description'))}
    rows,offers,manual=catalog_rows(catalogs,verified,code,division,cac,at,descriptions)
    search=st.text_input('Cerca codice o descrizione in anagrafica').strip().casefold()
    visible=[r for r in rows if not search or search in (r['REF']+' '+r['Descrizione']).casefold()]
    st.subheader('Prezzi applicati alla struttura')
    if visible:st.dataframe(pd.DataFrame(visible),hide_index=True,use_container_width=True)
    else:st.info('Nessun prezzo nei filtri selezionati. Puoi aggiungere un REF manualmente qui sotto.')
    from jj_report_runtime import current_reports
    st.download_button('Scarica prezzi struttura',lambda:current_reports().excel_report({'Prezzi applicati':visible,'Offerte originali':offers,'Prezzi manuali':manual}),
      'Prezzi_'+code+'_'+division+'.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',on_click='ignore')
    with st.expander('Offerte originali e validità'):
        if offers:st.dataframe(pd.DataFrame(offers),hide_index=True,use_container_width=True)
        else:st.caption('Nessuna offerta associata a questa struttura e linea.')
    with st.expander('Prezzi manuali, validità e verifiche'):
        if manual:st.dataframe(pd.DataFrame(manual).rename(columns={'ref':'REF','prezzo':'Prezzo','dal':'Valido dal','al':'Valido al','utente':'Modificato da','nota':'Riferimento','updated_at':'Ultima modifica'}),hide_index=True,use_container_width=True)
        else:st.caption('Nessun prezzo manuale per questo ambito.')
    from legacy_price_recovery import render_recovery_history
    render_recovery_history(client,verified,code,division)
    st.subheader('Modifica o aggiungi prezzo della struttura')
    chosen=st.selectbox('REF anagrafica',['Nuovo REF']+[r['REF'] for r in visible])
    ref=st.text_input('Codice REF da aggiungere') if chosen=='Nuovo REF' else chosen
    if not text(ref):return
    own=[r for r in manual if r['ref']==text(ref).upper()]
    periods={str(r['id']):r for r in own}
    active=next((str(r['id']) for r in own if r['dal']<=at.isoformat()<=r['al']),None)
    choices=['Nuovo periodo']+list(periods)
    selected=st.selectbox('Validità da gestire',choices,index=choices.index(active) if active else 0,
      format_func=lambda k:k if k=='Nuovo periodo' else periods[k]['dal']+' → '+periods[k]['al'])
    existing=periods.get(selected)
    start=date.fromisoformat(existing['dal']) if existing else at.replace(month=1,day=1)
    end=date.fromisoformat(existing['al']) if existing else at.replace(month=12,day=31)
    applied=next((r['Prezzo applicato'] for r in rows if r['REF']==text(ref).upper()),None)
    key=str((code,division,cac,ref,selected))
    with st.form('registry_'+key):
        amount=st.number_input('Prezzo unitario anagrafica (€)',min_value=0.0,value=float(existing['prezzo']) if existing else applied,step=.01,format='%.4f')
        discount=st.checkbox('Sconto merce anagrafica €0',value=bool(existing and existing.get('sconto')))
        left,right=st.columns(2)
        start=left.date_input('Validità prezzo dal',value=start,disabled=bool(existing))
        end=right.date_input('Validità prezzo al',value=end,disabled=bool(existing))
        note=st.text_input('Riferimento o nota (facoltativo)',value='')
        st.caption('Correggi il prezzo del periodo selezionato oppure aggiungi un periodo distinto. Ogni modifica è tracciata; ordini e fatture originali restano invariati.')
        save=st.form_submit_button('Salva prezzo in anagrafica',type='primary')
    if save:
        user=st.session_state.get('user');actor=(user.get('email') or user.get('username') or user.get('id')) if isinstance(user,dict) else user
        try:
            save_verified_price(client,{'Codice struttura':code,'CAC':cac,'Divisione':division,'REF':ref},0 if discount else amount,start,end,actor,note or 'Modifica manuale da Anagrafica prezzi',discount)
        except ValueError as exc:st.error(str(exc));return
        except Exception as exc:
            message=str(getattr(exc,'message',''))
            st.error(message if 'periodo sovrapposto' in message else 'Prezzo non salvato. Aggiorna l’anagrafica e riprova.');return
        refresh_prices();st.session_state['registry_saved']='Prezzo salvato per '+options[code]+' · '+text(ref).upper()+'. Anomalie e valorizzazione TAB vengono ricalcolate.';st.rerun()
