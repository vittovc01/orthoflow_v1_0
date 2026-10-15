-- Run only against explicitly selected STAGING. Synthetic rows, rolled back.
\set ON_ERROR_STOP on
BEGIN;
DO $$ DECLARE role_name text; action text; BEGIN
 IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid='public.ocr_review_sessions'::regclass) THEN RAISE EXCEPTION 'RLS disabled'; END IF;
 FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
  FOREACH action IN ARRAY ARRAY['SELECT','INSERT','UPDATE','DELETE'] LOOP
   IF has_table_privilege(role_name,'public.ocr_review_sessions',action) THEN RAISE EXCEPTION 'Unexpected grant: % %',role_name,action; END IF;
  END LOOP;
 END LOOP;
 IF EXISTS(SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='ocr_review_sessions') THEN RAISE EXCEPTION 'Unexpected archive policy'; END IF;
 IF EXISTS(SELECT 1 FROM storage.buckets WHERE id='scarico-ocr-originals' AND public) OR NOT EXISTS(SELECT 1 FROM storage.buckets WHERE id='scarico-ocr-originals') THEN RAISE EXCEPTION 'Private bucket missing'; END IF;
END $$;
INSERT INTO public.ocr_review_sessions(id,actor,confirmed_at,pipeline_version,payload_sha256,documents,extracted,confirmed,aggregate_rows,physical_count,count_verified)
VALUES(gen_random_uuid(),'staging_user_A',now(),'synthetic-test',repeat('a',64),'[{}]','{}','[{"label_id":"a"},{"label_id":"b","duplicate_of":"a"}]','[]',1,true);
SET LOCAL ROLE authenticated;
DO $$ BEGIN
 BEGIN PERFORM * FROM public.ocr_review_sessions; RAISE EXCEPTION 'READ WAS ALLOWED'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN INSERT INTO public.ocr_review_sessions DEFAULT VALUES; RAISE EXCEPTION 'WRITE WAS ALLOWED'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
SET LOCAL ROLE anon;
DO $$ BEGIN
 BEGIN PERFORM * FROM public.ocr_review_sessions; RAISE EXCEPTION 'ANON READ WAS ALLOWED'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN INSERT INTO public.ocr_review_sessions DEFAULT VALUES; RAISE EXCEPTION 'ANON WRITE WAS ALLOWED'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
ROLLBACK;
\echo 'PASS: archive RLS/grants and bucket; synthetic data rolled back'
