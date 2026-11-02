import pytest
from jj_reconciliation import clinical_reference,prepare_tab

HEADER='tipo;numero;cliente;articolo;lotto;descrizione;riferimento;data;quantità;serie;causale;scadenza;agente\n'

@pytest.mark.parametrize('reference,cc,event',[
 ('cc 275/1 del 03/02/2026','275/1','2026-02-03'),
 ('cc 007 del28/01/2026','007','2026-01-28'),
 ('cc 5750 del 17-07-2026','5750','2026-07-17'),
 ('CC 2809 DEL 17/07/26','2809','2026-07-17'),
 ('cc 2859 del 04/05/026','2859',''),
 ('cc R.A. del 18/06/2026','','2026-06-18'),
 ('cc del 26/10/2026','','2026-10-26'),
 ('unico DDT per ordine','','')])
def test_references_preserve_suffixes_and_never_invent_missing_identifiers(reference,cc,event):
 assert clinical_reference(reference)==(cc,event)

def sample(qty='1',agent='4',cause='AVVENUTO IMPIANTO'):
 return (HEADER+f'DDT;1;Clinica;150400207;L1;Componente femorale;cc 0007 del 08/11/2025;07/01/2026;{qty};A;{cause};31/12/2030;{agent}\n').encode()

def test_generic_agency_cause_requires_explicit_protesica_and_preserves_agent_code():
 rows=prepare_tab(sample(),'agenzia.csv','PROTESICA',customers=[{'codice_cliente':'00901','descrizione':'Clinica'}])
 p=rows[0]['payload']
 assert rows[0]['source_key']=='2026|DDT|A|1'
 assert p['event_date']=='2025-11-08' and p['encounter']=='0007'
 assert p['agent_code']=='4' and 'agent' not in p and p['customer_code']=='00901'
 assert prepare_tab(sample(),'again.csv','PROTESICA',customers=[{'codice_cliente':'00901','descrizione':'Clinica'}])==rows
 with pytest.raises(ValueError,match='causale diversa'):prepare_tab(sample(),'x.csv','TRAUMA')
 with pytest.raises(ValueError,match='causale diversa'):prepare_tab(sample(cause='AVVENUTO IMPIANTO TRAUMA'),'x.csv','PROTESICA')

def test_zero_quantity_is_identified_and_never_silently_discarded():
 with pytest.raises(ValueError,match='Riga 2, documento 2026.*REF 150400207'):
  prepare_tab(sample(qty='0'),'x.csv','PROTESICA')

def test_zero_agent_is_unassigned_and_does_not_become_a_person_name():
 p=prepare_tab(sample(agent='0'),'x.csv','PROTESICA')[0]['payload']
 assert 'agent' not in p and 'agent_code' not in p

def test_verified_cc_date_and_presidio_survive_cumulative_reload():
 rows=prepare_tab(sample(),'x.csv','PROTESICA')
 old={'id':1,'kind':'IMPIANTO','division':'PROTESICA',**rows[0]}
 old['payload'].update(encounter='VERIFICATA/1',event_date='2025-11-09',cac='100')
 result=prepare_tab(sample(),'updated.csv','PROTESICA',[old])[0]['payload']
 assert result['encounter']=='VERIFICATA/1' and result['event_date']=='2025-11-09' and result['cac']=='100'

