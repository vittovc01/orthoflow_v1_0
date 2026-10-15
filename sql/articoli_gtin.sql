-- Server-only supplier catalogue. Never infer mappings from evaluation truth.
BEGIN;
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
CREATE OR REPLACE FUNCTION public.import_articoli_gtin(p_rows jsonb)
RETURNS integer LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$
DECLARE n integer;
BEGIN
 IF jsonb_typeof(p_rows)!='array' OR jsonb_array_length(p_rows) NOT BETWEEN 1 AND 50000 THEN RAISE EXCEPTION 'Invalid catalogue size'; END IF;
 PERFORM pg_advisory_xact_lock(771504109);
 IF EXISTS(SELECT 1 FROM jsonb_to_recordset(p_rows) AS r(gtin text,ref text,descrizione text)
   WHERE gtin IS NULL OR ref IS NULL OR descrizione IS NULL OR NOT public.valid_gtin14(gtin)) THEN RAISE EXCEPTION 'Invalid catalogue row'; END IF;
 IF EXISTS(SELECT gtin FROM jsonb_to_recordset(p_rows) AS r(gtin text,ref text,descrizione text)
   GROUP BY gtin HAVING count(DISTINCT (ref,descrizione))>1) THEN RAISE EXCEPTION 'Conflicting GTIN in import'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_to_recordset(p_rows) AS r(gtin text,ref text,descrizione text)
   JOIN public.articoli_gtin a USING(gtin) WHERE a.ref!=r.ref OR a.descrizione!=r.descrizione) THEN RAISE EXCEPTION 'Existing catalogue mapping differs: manual review required'; END IF;
 INSERT INTO public.articoli_gtin SELECT DISTINCT gtin,ref,descrizione
 FROM jsonb_to_recordset(p_rows) AS r(gtin text,ref text,descrizione text) ON CONFLICT(gtin) DO NOTHING;
 GET DIAGNOSTICS n=ROW_COUNT;
 IF EXISTS(SELECT 1 FROM jsonb_to_recordset(p_rows) AS r(gtin text,ref text,descrizione text)
   JOIN public.articoli_gtin a USING(gtin) WHERE a.ref!=r.ref OR a.descrizione!=r.descrizione) THEN RAISE EXCEPTION 'Concurrent catalogue conflict'; END IF;
 RETURN n;
END $$;
REVOKE ALL ON FUNCTION public.import_articoli_gtin(jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.import_articoli_gtin(jsonb) TO service_role;
COMMIT;
