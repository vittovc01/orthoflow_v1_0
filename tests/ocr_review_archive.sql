BEGIN;
DO $$ BEGIN
 IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid='public.ocr_review_sessions'::regclass) THEN
  RAISE EXCEPTION 'OCR archive requires RLS'; END IF;
 IF has_table_privilege('anon','public.ocr_review_sessions','SELECT') OR
    has_table_privilege('authenticated','public.ocr_review_sessions','INSERT') OR
    has_table_privilege('service_role','public.ocr_review_sessions','UPDATE') OR
    has_table_privilege('service_role','public.ocr_review_sessions','DELETE') THEN
  RAISE EXCEPTION 'OCR archive access too broad'; END IF;
END $$;
INSERT INTO public.ocr_review_sessions(id,actor,confirmed_at,pipeline_version,payload_sha256,documents,extracted,confirmed,aggregate_rows,physical_count,count_verified)
VALUES('00000000-0000-0000-0000-000000000111','ci_operator',now(),'test',repeat('a',64),'[{"path":"test"}]','{}','[{"label_id":"one"}]','[]',1,true);
DO $$ BEGIN
 BEGIN UPDATE public.ocr_review_sessions SET actor='changed';
  RAISE EXCEPTION 'mutation accepted';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='mutation accepted' THEN RAISE; END IF; END;
 BEGIN DELETE FROM public.ocr_review_sessions;
  RAISE EXCEPTION 'delete accepted';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='delete accepted' THEN RAISE; END IF; END;
 BEGIN
  INSERT INTO public.ocr_review_sessions(id,actor,confirmed_at,pipeline_version,payload_sha256,documents,extracted,confirmed,aggregate_rows,physical_count,count_verified)
  VALUES('00000000-0000-0000-0000-000000000112','ci_operator',now(),'test',repeat('b',64),'[{}]','{}','[]','[]',1,false);
  RAISE EXCEPTION 'unconfirmed accepted';
 EXCEPTION WHEN check_violation THEN NULL; END;
END $$;
ROLLBACK;
