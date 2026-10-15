-- Isolated test database only; transaction rolls back all test records.
BEGIN;
SET LOCAL ROLE service_role;
DO $$
DECLARE r jsonb; payload jsonb='[{"gtin":"07611819268623","ref":"413.040S","descrizione":"Vite","categoria":"Trauma","fonte":"test.xls;2024"}]';
BEGIN
 r=public.import_articoli_gtin_v2(payload);
 IF (r->>'nuove')::int<>1 THEN RAISE EXCEPTION 'new count'; END IF;
 r=public.import_articoli_gtin_v2(payload);
 IF (r->>'invariate')::int<>1 OR (r->>'aggiornate')::int<>0 THEN RAISE EXCEPTION 'idempotency'; END IF;
 payload=jsonb_set(payload,'{0,descrizione}','"Descrizione aggiornata"');
 r=public.import_articoli_gtin_v2(payload);
 IF (r->>'aggiornate')::int<>1 THEN RAISE EXCEPTION 'updated count'; END IF;
 BEGIN
  PERFORM public.import_articoli_gtin_v2(jsonb_set(payload,'{0,ref}','"ALTRO"'));
  RAISE EXCEPTION 'conflict not rejected';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM='conflict not rejected' THEN RAISE; END IF;
 END;
 IF (SELECT ref FROM public.articoli_gtin WHERE gtin='07611819268623')<>'413.040S' THEN RAISE EXCEPTION 'REF changed'; END IF;
 BEGIN
  PERFORM public.import_articoli_gtin_v2(payload || jsonb_set(payload,'{0,ref}','"CONFLICT"'));
  RAISE EXCEPTION 'internal conflict not rejected';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM='internal conflict not rejected' THEN RAISE; END IF;
 END;
 BEGIN
  PERFORM public.import_articoli_gtin_v2(jsonb_set(payload,'{0,gtin}','"07611819268548"') || jsonb_set(payload,'{0,ref}','"CONFLICT"'));
  RAISE EXCEPTION 'batch conflict not rejected';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM='batch conflict not rejected' THEN RAISE; END IF;
 END;
 IF EXISTS(SELECT 1 FROM public.articoli_gtin WHERE gtin='07611819268548') THEN RAISE EXCEPTION 'partial batch import'; END IF;
 r=public.import_articoli_gtin_v2(jsonb_set(payload,'{0,gtin}','"07611819268548"'));
 IF (r->>'nuove')::int<>1 THEN RAISE EXCEPTION 'multiple GTIN same REF'; END IF;

END $$;
RESET ROLE;
SET LOCAL ROLE authenticated;
DO $$ BEGIN
 BEGIN
  PERFORM * FROM public.articoli_gtin;
  RAISE EXCEPTION 'unauthorized read';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN
  PERFORM public.import_articoli_gtin_v2('[]');
  RAISE EXCEPTION 'unauthorized write';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
SET LOCAL ROLE anon;
DO $$ BEGIN
 BEGIN
  PERFORM * FROM public.articoli_gtin;
  RAISE EXCEPTION 'anonymous read';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN
  PERFORM public.import_articoli_gtin_v2('[]');
  RAISE EXCEPTION 'anonymous write';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
ROLLBACK;
