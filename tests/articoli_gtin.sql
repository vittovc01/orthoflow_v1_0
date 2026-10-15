BEGIN;
DO $$ BEGIN
 IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid='public.articoli_gtin'::regclass) OR
 has_table_privilege('authenticated','public.articoli_gtin','SELECT') OR
 has_function_privilege('anon','public.import_articoli_gtin(jsonb)','EXECUTE') THEN RAISE EXCEPTION 'GTIN permissions too broad'; END IF;
END $$;
SET LOCAL ROLE service_role;
SELECT public.import_articoli_gtin('[{"gtin":"07611819268623","ref":"413.040S","descrizione":"Vite"}]');
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.articoli_gtin WHERE gtin='07611819268623' AND ref='413.040S') THEN RAISE EXCEPTION 'Mapping lost'; END IF;
 IF public.import_articoli_gtin('[{"gtin":"07611819268623","ref":"413.040S","descrizione":"Vite"}]')!=0 THEN RAISE EXCEPTION 'Not idempotent'; END IF;
 BEGIN
 PERFORM public.import_articoli_gtin('[{"gtin":"07611819268623","ref":"WRONG","descrizione":"Vite"}]');
 RAISE EXCEPTION 'Conflict allowed';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='Conflict allowed' THEN RAISE; END IF; END;
 IF NOT EXISTS(SELECT 1 FROM public.articoli_gtin WHERE ref='413.040S') THEN RAISE EXCEPTION 'Original mapping overwritten'; END IF;
 BEGIN
 INSERT INTO public.articoli_gtin VALUES('07611819268624','REF','Invalid');
 RAISE EXCEPTION 'Bad checksum allowed';
 EXCEPTION WHEN check_violation THEN NULL; END;
END $$;
RESET ROLE;
SET LOCAL ROLE authenticated;
DO $$ BEGIN
 BEGIN PERFORM * FROM public.articoli_gtin; RAISE EXCEPTION 'Read allowed'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN PERFORM public.import_articoli_gtin('[]'); RAISE EXCEPTION 'Import allowed'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
ROLLBACK;
