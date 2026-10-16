-- Disposable database only; real review/catalogue records are never used.
BEGIN;
DO $$
DECLARE
 header jsonb := '{"data_intervento":"2026-10-16","codice_cliente":"TEST","cliente":"TEST","magazzino_scarico":"SIMPLE_TEST","review_contract_version":2,"count_verified":true,"physical_label_count":1,"reported_label_count":3,"count_difference":2,"included_label_ids":["one"],"label_manifest":[{"label_id":"one","codice":"TEST-A","lotto":"LOT-A","scadenza":"2035-01-01","quantita":2}],"correction_log":[{"label_id":"one","field":"quantita","original":1,"corrected":2,"method":"manuale","user":"agent","timestamp":"2026-10-16T10:00:00Z"}]}';
 rows jsonb := '[{"codice":"TEST-A","lotto":"LOT-A","scadenza":"2035-01-01","quantita":2,"label_ids":["one"],"verificata":true,"gtin":"nan","prezzo":1}]';
 result jsonb; failed boolean;
BEGIN
 result:=crea_intervento_scarico_ai_verificato(header,rows,'agent');
 IF (SELECT quantita FROM righe_intervento WHERE intervento_id=(result->>'intervento_id')::bigint)<>2 THEN
   RAISE EXCEPTION 'manual quantity was not respected';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM audit_log WHERE riferimento=result->>'intervento_id'
   AND dettagli::jsonb->'correction_log'->0->>'method'='manuale'
   AND dettagli::jsonb->>'count_difference'='2') THEN
   RAISE EXCEPTION 'correction or count discrepancy audit lost';
 END IF;
 failed:=false;
 BEGIN
   PERFORM crea_intervento_scarico_ai_verificato(header,jsonb_set(rows,'{0,quantita}','3'),'agent');
 EXCEPTION WHEN OTHERS THEN
   IF SQLERRM NOT LIKE '%TEST-A, lotto LOT-A: quantità o dati diversi%' THEN RAISE; END IF;
   failed:=true;
 END;
 IF NOT failed THEN RAISE EXCEPTION 'quantity different from confirmed review accepted'; END IF;
 failed:=false;
 BEGIN
   PERFORM crea_intervento_scarico_ai_verificato(header,jsonb_set(rows,'{0,quantita}','null'),'agent');
 EXCEPTION WHEN OTHERS THEN
   IF SQLERRM NOT LIKE '%TEST-A, lotto LOT-A: quantità non valida%' THEN RAISE; END IF;
   failed:=true;
 END;
 IF NOT failed THEN RAISE EXCEPTION 'null quantity accepted'; END IF;
END $$;
ROLLBACK;
