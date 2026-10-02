-- One-time guarded repair applied on 2026-10-02. Re-execution aborts after repair.
BEGIN;
LOCK TABLE public.giacenze IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE public.movimenti_magazzino IN SHARE ROW EXCLUSIVE MODE;
CREATE OR REPLACE FUNCTION public.aggiorna_giacenza_da_movimento()
RETURNS trigger LANGUAGE plpgsql
AS $fn$
BEGIN
    -- This RPC has already debited the matched stock row under its original
    -- code/origin. Its movement is an audit record, not a second stock debit.
    IF NEW.tipo_movimento = 'SCARICO'
       AND NEW.origine = 'SCARICO SALA AI'
       AND NEW.riferimento_tipo = 'INTERVENTO'
       AND NEW.note = 'Scarico sala AI flessibile'
    THEN
        RETURN NEW;
    END IF;
    INSERT INTO public.giacenze(
        codice_magazzino, codice, lotto, scadenza, quantita, origine, updated_at)
    VALUES (
        NEW.codice_magazzino, NEW.codice, NEW.lotto, NEW.scadenza,
        NEW.quantita, NEW.origine, now())
    ON CONFLICT (codice_magazzino, codice, lotto, origine)
    DO UPDATE SET
        quantita = giacenze.quantita + excluded.quantita,
        scadenza = coalesce(excluded.scadenza, giacenze.scadenza),
        updated_at = now();
    RETURN NEW;
END;
$fn$;

DO $repair$
DECLARE snapshot jsonb; actual_count integer; total numeric; deleted_count integer; own_before numeric; own_after numeric; rec record;
BEGIN
 SELECT coalesce(sum(quantita),0) INTO own_before FROM public.giacenze WHERE origine IS DISTINCT FROM 'SCARICO SALA AI';
 SELECT jsonb_agg(to_jsonb(g)),count(*),sum(g.quantita) INTO snapshot,actual_count,total
 FROM public.giacenze g WHERE g.id IN (112390,112396,112397,112398,112399,112400,112404,112405,112406,112407,112408,112409,112410,112411,112412,112413)
 AND g.origine='SCARICO SALA AI';
 IF actual_count<>16 OR total IS DISTINCT FROM -17 THEN
 RAISE EXCEPTION 'REPAIR_SNAPSHOT_CHANGED: count %, total %',actual_count,total;
 END IF;
 FOR rec IN SELECT * FROM public.giacenze
 WHERE id IN (112390,112396,112397,112398,112399,112400,112404,112405,112406,112407,112408,112409,112410,112411,112412,112413) LOOP
  IF rec.quantita IS DISTINCT FROM (
   SELECT sum(m.quantita) FROM public.movimenti_magazzino m
   WHERE m.codice_magazzino=rec.codice_magazzino AND m.codice=rec.codice AND m.lotto=rec.lotto
   AND m.origine='SCARICO SALA AI' AND m.tipo_movimento='SCARICO'
   AND m.riferimento_tipo='INTERVENTO' AND m.note='Scarico sala AI flessibile')
  OR EXISTS(SELECT 1 FROM public.movimenti_magazzino m
   WHERE m.codice_magazzino=rec.codice_magazzino AND m.codice=rec.codice AND m.lotto=rec.lotto
   AND m.origine='SCARICO SALA AI'
   AND (m.tipo_movimento IS DISTINCT FROM 'SCARICO' OR m.riferimento_tipo IS DISTINCT FROM 'INTERVENTO'
        OR m.note IS DISTINCT FROM 'Scarico sala AI flessibile'))
  THEN RAISE EXCEPTION 'REPAIR_MOVEMENT_MISMATCH: stock row %',rec.id; END IF;
 END LOOP;
 INSERT INTO public.audit_log(utente,azione,tabella,riferimento,dettagli)
 VALUES('Codex - correzione autorizzata','CORREZIONE_DOPPIO_SCARICO_AI','giacenze','AI_DOUBLE_DEBIT_20261002',
 jsonb_build_object('righe_artificiali_rimosse',snapshot,'quantita_artificiale',total,'giacenze_reali','invariate','movimenti','conservati')::text);
 DELETE FROM public.giacenze WHERE id IN (112390,112396,112397,112398,112399,112400,112404,112405,112406,112407,112408,112409,112410,112411,112412,112413)
 AND origine='SCARICO SALA AI';
 GET DIAGNOSTICS deleted_count=ROW_COUNT;
 IF deleted_count<>16 THEN RAISE EXCEPTION 'Unexpected delete count %',deleted_count; END IF;
 SELECT coalesce(sum(quantita),0) INTO own_after FROM public.giacenze WHERE origine IS DISTINCT FROM 'SCARICO SALA AI';
 IF own_after IS DISTINCT FROM own_before THEN RAISE EXCEPTION 'Real stock unexpectedly changed'; END IF;
END $repair$;

COMMIT;
