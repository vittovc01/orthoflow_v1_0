-- Server-only aggregate metrics. No clinical rows or document paths are returned.
CREATE OR REPLACE FUNCTION public.orthoflow_cloud_capacity()
RETURNS jsonb LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = pg_catalog, public, storage AS $$
  SELECT jsonb_build_object(
    'database_bytes', pg_database_size(current_database()),
    'file_bytes', COALESCE((SELECT sum(CASE WHEN metadata->>'size' ~ '^[0-9]+$'
      THEN (metadata->>'size')::bigint ELSE 0 END) FROM storage.objects), 0),
    'file_count', (SELECT count(*) FROM storage.objects),
    'measured_at', now());
$$;
REVOKE ALL ON FUNCTION public.orthoflow_cloud_capacity() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.orthoflow_cloud_capacity() TO service_role;
