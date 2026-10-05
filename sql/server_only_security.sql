-- OrthoFlow authenticates/authorises in its Python server, not directly in PostgREST.
-- Existing app clients already use a privileged server key (verified on protected reads).
-- Keep table/function owners and service_role access; deny direct public API access.
BEGIN;
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relkind IN ('r','p')
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',r.relname);
  END LOOP;
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, anon, authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;
DO $$
DECLARE f record;
BEGIN
  FOR f IN SELECT p.proname,pg_get_function_identity_arguments(p.oid) AS args
    FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
    WHERE n.nspname='public' AND p.prosecdef AND p.prokind='f'
  LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION public.%I(%s) FROM PUBLIC, anon, authenticated',f.proname,f.args);
    EXECUTE format('GRANT EXECUTE ON FUNCTION public.%I(%s) TO service_role',f.proname,f.args);
  END LOOP;
  IF to_regprocedure('public.aggiorna_giacenza_da_movimento()') IS NOT NULL THEN
    ALTER FUNCTION public.aggiorna_giacenza_da_movimento() SET search_path TO pg_catalog, public, pg_temp;
  END IF;
  IF to_regclass('public.v_wms_scaffali') IS NOT NULL THEN
    ALTER VIEW public.v_wms_scaffali SET (security_invoker=true);
  END IF;
END $$;
-- Functions newly created by the migration owner are server-only by default too.
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO service_role;
COMMIT;
