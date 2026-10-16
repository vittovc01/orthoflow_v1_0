BEGIN;
DO $$
DECLARE
 h jsonb := '{"request_id":"00000000-0000-4000-8000-000000000010","data_intervento":"2026-10-16","codice_cliente":"TEST-IDEMP","cartella_clinica":"TEST-CC-1","magazzino_scarico":"TEST-IDEMP","review_contract_version":2,"count_verified":true,"physical_label_count":1,"included_label_ids":["one"],"label_manifest":[{"label_id":"one","codice":"TEST-A","lotto":"TEST-LOT","scadenza":"2035-01-01","quantita":2}]}';
 r jsonb := '[{"codice":"TEST-A","lotto":"TEST-LOT","scadenza":"2035-01-01","quantita":2,"label_ids":["one"],"verificata":true}]';
 first_result jsonb; retry_result jsonb; failed boolean;
BEGIN
 insert into giacenze(codice_magazzino,codice,lotto,scadenza,quantita,origine)
 values('TEST-IDEMP','TEST-A','TEST-LOT','2035-01-01',10,'CONTO DEPOSITO');
 first_result:=crea_intervento_scarico_ai_verificato(h,r,'test-agent');
 -- Double click and retry after lost response use the same request ID.
 retry_result:=crea_intervento_scarico_ai_verificato(h,r,'test-agent');
 if retry_result->>'intervento_id'<>first_result->>'intervento_id' or retry_result->>'replayed'<>'true'
    or (select quantita from giacenze where codice_magazzino='TEST-IDEMP')<>8
    or (select count(*) from movimenti_magazzino where riferimento_id=first_result->>'intervento_id')<>1
    or (select count(*) from audit_log where riferimento=first_result->>'intervento_id')<>1 then
   raise exception 'retry created a second stock discharge or audit';
 end if;
 -- Reload/reanalysis with a NEW request UUID, same clinic/record/day: reject.
 failed:=false;
 begin
   perform crea_intervento_scarico_ai_verificato(h||'{"request_id":"00000000-0000-4000-8000-000000000011"}',r,'test-agent');
 exception when others then
   if SQLERRM not like 'Scarico già registrato:%' then raise; end if; failed:=true;
 end;
 if not failed then raise exception 'same clinical record was discharged twice'; end if;
 -- A different clinical record is a separate operation.
 perform crea_intervento_scarico_ai_verificato(h||'{"request_id":"00000000-0000-4000-8000-000000000012","cartella_clinica":"TEST-CC-2"}',r,'test-agent');
 -- A reused UUID with different payload must not be silently accepted.
 failed:=false;
 begin
   perform crea_intervento_scarico_ai_verificato(h||'{"chirurgo":"different"}',r,'test-agent');
 exception when others then
   if SQLERRM not like 'Richiesta già usata con dati diversi%' then raise; end if; failed:=true;
 end;
 if not failed then raise exception 'request key accepted changed payload'; end if;
 -- Existing historical records also guard a repeated clinical record.
 insert into interventi(data_intervento,codice_cliente,cartella_clinica)
 values('2026-10-16','TEST-IDEMP','TEST-HISTORIC');
 failed:=false;
 begin
   perform crea_intervento_scarico_ai_verificato(h||'{"request_id":"00000000-0000-4000-8000-000000000015","cartella_clinica":"TEST-HISTORIC"}',r,'test-agent');
 exception when others then
   if SQLERRM not like 'Scarico già registrato:%' then raise; end if; failed:=true;
 end;
 if not failed then raise exception 'historical clinical record accepted again'; end if;
 -- When no clinical record is provided, exact original document identity guards reloads.
 h:=h||'{"request_id":"00000000-0000-4000-8000-000000000013","cartella_clinica":"","label_manifest":[{"label_id":"one","codice":"TEST-A","lotto":"TEST-LOT","scadenza":"2035-01-01","quantita":2,"source_document":"synthetic-document"}]}';
 perform crea_intervento_scarico_ai_verificato(h,r,'test-agent');
 failed:=false;
 begin
   perform crea_intervento_scarico_ai_verificato(h||'{"request_id":"00000000-0000-4000-8000-000000000014"}',r,'test-agent');
 exception when others then
   if SQLERRM not like 'Scarico già registrato:%' then raise; end if; failed:=true;
 end;
 if not failed then raise exception 'same source document accepted after reload'; end if;
END $$;
ROLLBACK;
