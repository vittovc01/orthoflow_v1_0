BEGIN;
DO $$
DECLARE
 h jsonb := '{"request_id":"00000000-0000-4000-8000-000000000020","data_intervento":"2026-10-16","codice_cliente":"TEST","cartella_clinica":"TEST-SERVER","magazzino_scarico":"TEST-SERVER","review_contract_version":2,"count_verified":true,"physical_label_count":1,"included_label_ids":["manual:one"],"label_manifest":[{"label_id":"manual:one","codice":"TEST-A","lotto":"TEST-LOT","scadenza":"2035-01-01","quantita":2}]}';
 r jsonb := '[{"codice":"TEST-A","lotto":"TEST-LOT","scadenza":"2035-01-01","quantita":2,"label_ids":["manual:one"],"verificata":true}]';
 c jsonb; bad_rows jsonb; bad_header jsonb; failed boolean; before_count bigint;
BEGIN
 select count(*) into before_count from interventi;
 for c in select * from jsonb_array_elements('[
   {"field":"codice","value":""},{"field":"codice","value":"TEST?"},
   {"field":"lotto","value":""},{"field":"lotto","value":"123456789012345678901"},
   {"field":"scadenza","value":""},{"field":"scadenza","value":"2035-02-30"},
   {"field":"scadenza","value":"2035-13-01"},{"field":"scadenza","value":"tomorrow"},
   {"field":"quantita","value":0},{"field":"quantita","value":-1},
   {"field":"quantita","value":1.5},{"field":"quantita","value":null},
   {"field":"quantita","value":"NaN"},{"field":"quantita","value":true}
 ]'::jsonb) loop
   bad_rows:=jsonb_set(r,array['0',c->>'field'],c->'value');
   -- Tamper with BOTH payload and matching manifest: server still validates.
   bad_header:=jsonb_set(h,array['label_manifest','0',c->>'field'],c->'value');
   failed:=false;
   begin
     perform crea_intervento_scarico_ai_verificato(bad_header,bad_rows,'test-agent');
   exception when others then failed:=true;
   end;
   if not failed then raise exception 'server accepted invalid field: %',c; end if;
 end loop;
 if (select count(*) from interventi)<>before_count
   or exists(select 1 from scarico_ai_requests where request_id='00000000-0000-4000-8000-000000000020') then
   raise exception 'failed validation left partial records or consumed request key';
 end if;
 -- Same key succeeds after a fully rolled-back invalid attempt.
 perform crea_intervento_scarico_ai_verificato(h,r,'test-agent');
END $$;
ROLLBACK;
