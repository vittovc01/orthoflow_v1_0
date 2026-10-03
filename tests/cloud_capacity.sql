BEGIN;
INSERT INTO storage.objects(bucket_id,name,metadata) VALUES ('test','file', '{"size":1200}');
DO $$
BEGIN
 IF has_function_privilege('anon','public.orthoflow_cloud_capacity()','EXECUTE')
 OR has_function_privilege('authenticated','public.orthoflow_cloud_capacity()','EXECUTE')
 THEN RAISE EXCEPTION 'Cloud metrics exposed to public roles'; END IF;
END $$;
SET LOCAL ROLE service_role;
DO $$
DECLARE m jsonb;
BEGIN
 m=public.orthoflow_cloud_capacity();
 IF (m->>'file_bytes')::bigint <> 1200 OR (m->>'file_count')::bigint <> 1
 THEN RAISE EXCEPTION 'Incorrect cloud capacity'; END IF;
END $$;
ROLLBACK;
