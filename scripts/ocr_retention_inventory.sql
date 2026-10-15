-- Read-only inventory. Set an APPROVED cutoff date in psql, never a universal
-- invented retention period: psql ... -v cutoff='2025-01-01T00:00:00Z' -f ...
\set ON_ERROR_STOP on
BEGIN READ ONLY;
SELECT count(*) AS sessions_before_cutoff,
       coalesce(sum(jsonb_array_length(documents)),0) AS original_documents
FROM public.ocr_review_sessions WHERE created_at < :'cutoff'::timestamptz;
-- Private report only: object paths/session IDs are sensitive metadata.
SELECT id,created_at,documents
FROM public.ocr_review_sessions WHERE created_at < :'cutoff'::timestamptz
ORDER BY created_at;
ROLLBACK;
