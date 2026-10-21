-- Extend the existing, service-only stock RPCs and triggers without replacing
-- unrelated fixes or changing privileges. No rows or stock movements are written.
DO $migration$
DECLARE signature text; definition text; updated text;
BEGIN
 FOREACH signature IN ARRAY ARRAY[
  'public.crea_intervento_scarico_ai_flessibile(jsonb,jsonb,text)',
  'public.crea_intervento_scarico_ai_verificato(jsonb,jsonb,text)',
  'public.chiudi_anomalia_materiale_struttura()',
  'public.ricalcola_prezzi_cambio_struttura()'
 ] LOOP
  IF to_regprocedure(signature) IS NULL THEN
   RAISE EXCEPTION 'Funzione richiesta mancante: %',signature;
  END IF;
  definition := pg_get_functiondef(to_regprocedure(signature));
  updated := replace(definition,
   'coalesce(p_header->>''codice_cliente'','''') <> ''9010013''',
   'coalesce(p_header->>''codice_cliente'','''') NOT IN (''9010013'',''9010054'')');
  updated := replace(updated,'CONTO_DEPOSITO_STRUTTURA_SOLO_MALZONI',
   'CONTO_DEPOSITO_STRUTTURA_NON_ABILITATO');
  updated := replace(updated,'codice_cliente=''9010013''',
   'codice_cliente IN (''9010013'',''9010054'')');
  updated := replace(updated,'coalesce(NEW.codice_cliente,'''')<>''9010013''',
   '(coalesce(NEW.codice_cliente,'''') NOT IN (''9010013'',''9010054'') OR NEW.codice_cliente IS DISTINCT FROM OLD.codice_cliente)');
  updated := replace(updated,'Materiale della struttura Malzoni:', 'Materiale di proprietà della struttura:');
  IF position('9010054' IN updated)=0 THEN
   RAISE EXCEPTION 'Guardia struttura non riconosciuta: %',signature;
  END IF;
  IF updated IS DISTINCT FROM definition THEN EXECUTE updated; END IF;
 END LOOP;
END $migration$;
