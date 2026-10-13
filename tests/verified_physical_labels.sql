-- Disposable CI database only. All inserted fixtures rolled back.
BEGIN;
DO $$
DECLARE
 header jsonb := '{"data_intervento":"2026-10-13","codice_cliente":"TEST","cliente":"TEST","magazzino_scarico":"LABEL_TEST","count_verified":true,"physical_label_count":2,"included_label_ids":["one","two"]}';
 rows jsonb := '[{"codice":"292.720S","lotto":"LABELLOT","scadenza":"2036-03-01","quantita":2,"label_ids":["one","two"],"verificata":true,"prezzo":1}]';
 result jsonb; failed boolean; before_count bigint;
BEGIN
 INSERT INTO giacenze(codice_magazzino,codice,lotto,scadenza,quantita,origine)
 VALUES('LABEL_TEST','292720S','LABELLOT','2036-03-01',2,'CONTO DEPOSITO');
 result := crea_intervento_scarico_ai_verificato(header,rows,'TEST');
 IF (SELECT quantita FROM giacenze WHERE codice_magazzino='LABEL_TEST')<>0 THEN
   RAISE EXCEPTION 'duplicate physical pieces were not discharged as 2';
 END IF;
 IF EXISTS(SELECT 1 FROM giacenze WHERE codice_magazzino='LABEL_TEST' AND origine='SCARICO SALA AI') THEN
   RAISE EXCEPTION 'artificial stock created by movement trigger';
 END IF;
 IF (SELECT quantita FROM righe_intervento WHERE intervento_id=(result->>'intervento_id')::bigint)<>2 THEN
   RAISE EXCEPTION 'wrong aggregated quantity';
 END IF;
 SELECT count(*) INTO before_count FROM interventi;
 failed:=false;
 BEGIN
   PERFORM crea_intervento_scarico_ai_verificato(header,rows,'TEST');
 EXCEPTION WHEN OTHERS THEN
   IF SQLERRM NOT LIKE '%GIACENZA_INSUFFICIENTE%' THEN RAISE; END IF;
   failed:=true;
 END;
 IF NOT failed OR (SELECT count(*) FROM interventi)<>before_count THEN
   RAISE EXCEPTION 'shortage did not roll back intervention';
 END IF;
 failed:=false;
 BEGIN
   PERFORM crea_intervento_scarico_ai_verificato(header || '{"count_verified":false}',rows,'TEST');
 EXCEPTION WHEN OTHERS THEN
   IF SQLERRM NOT LIKE '%ETICHETTE_NON_VERIFICATE%' THEN RAISE; END IF;
   failed:=true;
 END;
 IF NOT failed THEN RAISE EXCEPTION 'unverified count accepted'; END IF;
 failed:=false;
 BEGIN
   PERFORM crea_intervento_scarico_ai_verificato(header,
      jsonb_set(rows,'{0,label_ids}','["one","one"]'),'TEST');
 EXCEPTION WHEN OTHERS THEN
   IF SQLERRM NOT LIKE '%IDENTITA_FISICHE_DUPLICATE%' THEN RAISE; END IF;
   failed:=true;
 END;
 IF NOT failed THEN RAISE EXCEPTION 'artificial duplicate accepted'; END IF;
 UPDATE giacenze SET quantita=2,scadenza='2036-04-01' WHERE codice_magazzino='LABEL_TEST';
 failed:=false;
 BEGIN
   PERFORM crea_intervento_scarico_ai_verificato(header,rows,'TEST');
 EXCEPTION WHEN OTHERS THEN
   IF SQLERRM NOT LIKE '%GIACENZA_INSUFFICIENTE_O_SCADENZA_DIVERSA%' THEN RAISE; END IF;
   failed:=true;
 END;
 IF NOT failed OR (SELECT quantita FROM giacenze WHERE codice_magazzino='LABEL_TEST')<>2 THEN
   RAISE EXCEPTION 'expiry mismatch changed stock';
 END IF;
 IF has_function_privilege('anon','crea_intervento_scarico_ai_verificato(jsonb,jsonb,text)','EXECUTE')
    OR has_function_privilege('authenticated','crea_intervento_scarico_ai_verificato(jsonb,jsonb,text)','EXECUTE') THEN
   RAISE EXCEPTION 'verified RPC publicly callable';
 END IF;
END $$;
ROLLBACK;
