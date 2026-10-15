-- Explicit operator-confirmed OCR archive only; does not move stock.
-- Apply in staging first. OrthoFlow authenticates in its trusted Python server.
BEGIN;
CREATE OR REPLACE FUNCTION public.ocr_review_physical_count(p_rows jsonb)
RETURNS integer LANGUAGE sql IMMUTABLE STRICT SECURITY INVOKER SET search_path=pg_catalog AS $$
 SELECT count(*)::integer FROM jsonb_array_elements(p_rows) r
 WHERE nullif(trim(r->>'duplicate_of'),'') IS NULL;
$$;
REVOKE ALL ON FUNCTION public.ocr_review_physical_count(jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ocr_review_physical_count(jsonb) TO service_role;
CREATE TABLE IF NOT EXISTS public.ocr_review_sessions (
 id uuid PRIMARY KEY,
 actor text NOT NULL CHECK (length(trim(actor))>0),
 created_at timestamptz NOT NULL DEFAULT now(),
 confirmed_at timestamptz NOT NULL,
 pipeline_version text NOT NULL,
 payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
 documents jsonb NOT NULL CHECK (jsonb_typeof(documents)='array' AND jsonb_array_length(documents) BETWEEN 1 AND 20),
 extracted jsonb NOT NULL CHECK (jsonb_typeof(extracted)='object'),
 confirmed jsonb NOT NULL CHECK (jsonb_typeof(confirmed)='array'),
 aggregate_rows jsonb NOT NULL CHECK (jsonb_typeof(aggregate_rows)='array'),
 physical_count integer NOT NULL CHECK (physical_count>0),
 count_verified boolean NOT NULL CHECK (count_verified),
 CONSTRAINT ocr_review_physical_count_matches CHECK (public.ocr_review_physical_count(confirmed)=physical_count)
);
-- Upgrade the prior observation-count constraint without repairing existing rows.
DO $$ DECLARE c record; BEGIN
 FOR c IN SELECT conname FROM pg_constraint WHERE conrelid='public.ocr_review_sessions'::regclass
  AND contype='c' AND pg_get_constraintdef(oid) LIKE '%jsonb_array_length(confirmed)%physical_count%'
 LOOP EXECUTE format('ALTER TABLE public.ocr_review_sessions DROP CONSTRAINT %I',c.conname); END LOOP;
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.ocr_review_sessions'::regclass AND conname='ocr_review_physical_count_matches') THEN
  ALTER TABLE public.ocr_review_sessions ADD CONSTRAINT ocr_review_physical_count_matches CHECK(public.ocr_review_physical_count(confirmed)=physical_count);
 END IF;
END $$;
CREATE INDEX IF NOT EXISTS ocr_review_actor_created_idx ON public.ocr_review_sessions(actor,created_at DESC);
ALTER TABLE public.ocr_review_sessions ENABLE ROW LEVEL SECURITY;
-- Browser/mobile clients never receive a service key or direct table privileges.
REVOKE ALL ON public.ocr_review_sessions FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT,INSERT ON public.ocr_review_sessions TO service_role;
-- No public policies: the server checks the existing app principal and permissions.
CREATE OR REPLACE FUNCTION public.reject_ocr_review_mutation()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'Archivio OCR immutabile: creare una nuova revisione'; END $$;
REVOKE ALL ON FUNCTION public.reject_ocr_review_mutation() FROM PUBLIC,anon,authenticated;
DROP TRIGGER IF EXISTS ocr_review_immutable ON public.ocr_review_sessions;
CREATE TRIGGER ocr_review_immutable BEFORE UPDATE OR DELETE ON public.ocr_review_sessions
 FOR EACH ROW EXECUTE FUNCTION public.reject_ocr_review_mutation();
-- Keep the SQL testable on ordinary Postgres; production Supabase has storage.buckets.
DO $$ BEGIN
 IF to_regclass('storage.buckets') IS NOT NULL THEN
  INSERT INTO storage.buckets(id,name,public) VALUES('scarico-ocr-originals','scarico-ocr-originals',false)
  ON CONFLICT(id) DO NOTHING;
  IF EXISTS(SELECT 1 FROM storage.buckets WHERE id='scarico-ocr-originals' AND public) THEN
   RAISE EXCEPTION 'Il bucket OCR deve essere privato';
  END IF;
 END IF;
END $$;
COMMIT;
