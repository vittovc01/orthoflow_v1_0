BEGIN;
DO $$
DECLARE t record;
BEGIN
 FOR t IN SELECT c.oid,c.relname,c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='public' AND c.relkind IN ('r','p')
 LOOP
  IF NOT t.relrowsecurity THEN RAISE EXCEPTION 'RLS missing: %',t.relname; END IF;
  IF has_table_privilege('anon',t.oid,'SELECT') OR has_table_privilege('authenticated',t.oid,'INSERT')
  THEN RAISE EXCEPTION 'Public data access: %',t.relname; END IF;
  IF NOT has_table_privilege('service_role',t.oid,'SELECT') OR NOT has_table_privilege('service_role',t.oid,'INSERT')
  THEN RAISE EXCEPTION 'Server access broken: %',t.relname; END IF;
 END LOOP;
 IF has_function_privilege('anon','public.crea_intervento_scarico_ai_flessibile(jsonb,jsonb,text)','EXECUTE')
 OR has_function_privilege('authenticated','public.crea_intervento_scarico_ai_flessibile(jsonb,jsonb,text)','EXECUTE')
 THEN RAISE EXCEPTION 'Public stock RPC access'; END IF;
 IF NOT has_function_privilege('service_role','public.crea_intervento_scarico_ai_flessibile(jsonb,jsonb,text)','EXECUTE')
 THEN RAISE EXCEPTION 'Stock RPC not available to server'; END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_class WHERE oid='public.v_wms_scaffali'::regclass AND reloptions @> ARRAY['security_invoker=true']::text[])
 THEN RAISE EXCEPTION 'View bypasses RLS'; END IF;
END $$;
SET LOCAL ROLE service_role;
INSERT INTO corrieri(id,user_id,attivo) VALUES(98765,NULL,true);
UPDATE corrieri SET attivo=false WHERE id=98765;
DO $$ BEGIN
 IF (SELECT attivo FROM corrieri WHERE id=98765) IS DISTINCT FROM false
 THEN RAISE EXCEPTION 'Server CRUD broken'; END IF;
END $$;
RESET ROLE;
SET LOCAL ROLE anon;
DO $$ BEGIN
 BEGIN
  PERFORM id FROM corrieri;
  RAISE EXCEPTION 'Anonymous read succeeded';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
 BEGIN
  PERFORM crea_intervento_scarico_ai_flessibile('{}'::jsonb,'[]'::jsonb,'forged');
  RAISE EXCEPTION 'Anonymous RPC succeeded';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $$;
RESET ROLE;
ROLLBACK;
