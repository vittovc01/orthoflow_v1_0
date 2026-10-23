-- Disposable database only: no production records.
BEGIN;
DO $$
DECLARE
 h jsonb := '{"request_id":"00000000-0000-4000-8000-000000000099","data_intervento":"2026-10-23","codice_cliente":"TEST","cartella_clinica":"TEST-NONSTERILE","magazzino_scarico":"NONSTERILE-TEST","count_verified":true,"physical_label_count":1,"included_label_ids":["one"],"label_manifest":[{"label_id":"one","codice":"440.037","lotto":"","scadenza":"","quantita":2,"senza_lotto":true}]}';
 r jsonb := '[{"codice":"440.037","lotto":"","scadenza":null,"quantita":2,"label_ids":["one"],"verificata":true,"senza_lotto":true,"prezzo":1}]';
 result jsonb; failed boolean; bad jsonb;
BEGIN
 INSERT INTO giacenze(codice_magazzino,codice,lotto,quantita) VALUES('NONSTERILE-TEST','440.037','',5);
 result:=crea_intervento_scarico_ai_verificato_v2(h,r,'test-agent');
 IF (SELECT quantita FROM giacenze WHERE codice_magazzino='NONSTERILE-TEST')<>3 THEN
   RAISE EXCEPTION 'nonsterile stock was not debited exactly once';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM righe_intervento WHERE intervento_id=(result->>'intervento_id')::bigint AND lotto='' AND scadenza IS NULL AND quantita=2) THEN
   RAISE EXCEPTION 'nonsterile row not saved';
 END IF;
 PERFORM crea_intervento_scarico_ai_verificato_v2(h,r,'test-agent');
 IF (SELECT quantita FROM giacenze WHERE codice_magazzino='NONSTERILE-TEST')<>3 THEN RAISE EXCEPTION 'retry debited stock twice'; END IF;
 FOR bad IN SELECT * FROM jsonb_array_elements('[{"is_sterile":true},{"codice":"440.037S"},{"senza_lotto":false},{"scadenza":"2035-02-31"},{"lotto":"LOT"}]'::jsonb) LOOP
   failed:=false;
   BEGIN
     PERFORM crea_intervento_scarico_ai_verificato_v2(h,jsonb_build_array(r->0||bad),'test-agent');
   EXCEPTION WHEN OTHERS THEN failed:=true;
   END;
   IF NOT failed THEN RAISE EXCEPTION 'invalid nonsterile confirmation accepted: %',bad; END IF;
 END LOOP;
END $$;
ROLLBACK;
