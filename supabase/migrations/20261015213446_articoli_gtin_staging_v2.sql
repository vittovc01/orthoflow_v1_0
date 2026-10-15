-- STAGING ONLY. Supports a fresh database or the previous three-column table.
-- Execute in a transaction/session with:
-- SET orthoflow.environment = 'staging';
BEGIN;
DO $$ BEGIN
 IF current_setting('orthoflow.environment',true) IS DISTINCT FROM 'staging' THEN
 RAISE EXCEPTION 'Staging environment must be explicitly selected'; END IF;
END $$;
CREATE OR REPLACE FUNCTION public.valid_gtin14(p_gtin text)
RETURNS boolean LANGUAGE sql IMMUTABLE STRICT SECURITY INVOKER SET search_path=pg_catalog AS $$
 SELECT CASE WHEN p_gtin ~ '^[0-9]{14}$' THEN
 (SELECT sum(substring(p_gtin,i,1)::int * CASE WHEN i%2=1 THEN 3 ELSE 1 END)%10=0 FROM generate_series(1,14) i)
 ELSE false END;
$$;
REVOKE ALL ON FUNCTION public.valid_gtin14(text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.valid_gtin14(text) TO service_role;
CREATE TABLE IF NOT EXISTS public.articoli_gtin (
 gtin text PRIMARY KEY CHECK(public.valid_gtin14(gtin)),
 ref text NOT NULL CHECK(length(trim(ref)) BETWEEN 1 AND 100 AND ref ~ '^[A-Za-z0-9][A-Za-z0-9. /-]*$'),
 descrizione text NOT NULL DEFAULT ''
);
ALTER TABLE public.articoli_gtin ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.articoli_gtin FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT,INSERT ON public.articoli_gtin TO service_role;
ALTER TABLE public.articoli_gtin ADD COLUMN IF NOT EXISTS categoria text NOT NULL DEFAULT '';
ALTER TABLE public.articoli_gtin ADD COLUMN IF NOT EXISTS fonte text NOT NULL DEFAULT '';
ALTER TABLE public.articoli_gtin ADD COLUMN IF NOT EXISTS data_import timestamptz NOT NULL DEFAULT now();
CREATE SCHEMA IF NOT EXISTS ocr_private;
REVOKE ALL ON SCHEMA ocr_private FROM PUBLIC,anon,authenticated;
CREATE TABLE IF NOT EXISTS ocr_private.environment (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), name text NOT NULL CHECK(name='staging'));
INSERT INTO ocr_private.environment VALUES(true,'staging') ON CONFLICT DO NOTHING;
GRANT USAGE ON SCHEMA ocr_private TO service_role;
GRANT SELECT ON ocr_private.environment TO service_role;
ALTER TABLE ocr_private.environment ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE ON public.articoli_gtin TO service_role;
-- Remove the legacy endpoint so it cannot bypass the staging import contract.
DO $$ BEGIN
 IF to_regprocedure('public.import_articoli_gtin(jsonb)') IS NOT NULL THEN
 EXECUTE 'REVOKE EXECUTE ON FUNCTION public.import_articoli_gtin(jsonb) FROM service_role';
 END IF; END $$;
CREATE OR REPLACE FUNCTION public.import_articoli_gtin_v2(p_rows jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
DECLARE n_new integer; n_updated integer; n_same integer;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM ocr_private.environment WHERE singleton AND name='staging') THEN RAISE EXCEPTION 'Staging only'; END IF;
 IF jsonb_typeof(p_rows) IS DISTINCT FROM 'array' OR jsonb_array_length(p_rows) NOT BETWEEN 1 AND 100000 THEN RAISE EXCEPTION 'Invalid input size'; END IF;
 -- Serialize competing importers AND direct writes until commit.
 LOCK TABLE public.articoli_gtin IN SHARE ROW EXCLUSIVE MODE;
 IF EXISTS(SELECT 1 FROM jsonb_to_recordset(p_rows) AS r(gtin text,ref text,descrizione text,categoria text,fonte text)
 WHERE gtin IS NULL OR NOT public.valid_gtin14(gtin) OR ref IS NULL OR ref !~ '^[A-Za-z0-9][A-Za-z0-9. /-]{0,99}$'
 OR descrizione IS NULL OR nullif(trim(categoria),'') IS NULL OR nullif(trim(fonte),'') IS NULL) THEN RAISE EXCEPTION 'Invalid catalogue row'; END IF;
 IF EXISTS(SELECT gtin FROM jsonb_to_recordset(p_rows) AS r(gtin text,ref text,descrizione text,categoria text,fonte text)
 GROUP BY gtin HAVING count(DISTINCT (ref,descrizione,categoria,fonte))>1) THEN RAISE EXCEPTION 'Conflicting duplicate GTIN'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_to_recordset(p_rows) AS r(gtin text,ref text)
 JOIN public.articoli_gtin a USING(gtin) WHERE a.ref<>r.ref) THEN
 RAISE EXCEPTION 'GTIN already mapped to a different REF; entire import rolled back'; END IF;
 SELECT count(*) INTO n_same FROM (SELECT DISTINCT * FROM jsonb_to_recordset(p_rows) AS r(gtin text,ref text,descrizione text,categoria text,fonte text)) r
 JOIN public.articoli_gtin a USING(gtin) WHERE (a.ref,a.descrizione,a.categoria,a.fonte)=(r.ref,r.descrizione,r.categoria,r.fonte);
 UPDATE public.articoli_gtin a SET descrizione=r.descrizione,categoria=r.categoria,fonte=r.fonte,data_import=now()
 FROM (SELECT DISTINCT * FROM jsonb_to_recordset(p_rows) AS r(gtin text,ref text,descrizione text,categoria text,fonte text)) r
 WHERE a.gtin=r.gtin AND (a.descrizione,a.categoria,a.fonte) IS DISTINCT FROM (r.descrizione,r.categoria,r.fonte);
 GET DIAGNOSTICS n_updated=ROW_COUNT;
 INSERT INTO public.articoli_gtin(gtin,ref,descrizione,categoria,fonte)
 SELECT DISTINCT gtin,ref,descrizione,categoria,fonte FROM jsonb_to_recordset(p_rows) AS r(gtin text,ref text,descrizione text,categoria text,fonte text)
 ON CONFLICT(gtin) DO NOTHING;
 GET DIAGNOSTICS n_new=ROW_COUNT;
 RETURN jsonb_build_object('nuove',n_new,'aggiornate',n_updated,'invariate',n_same);
END $$;
REVOKE ALL ON FUNCTION public.import_articoli_gtin_v2(jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.import_articoli_gtin_v2(jsonb) TO service_role;
COMMIT;
