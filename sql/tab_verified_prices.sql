-- Client/presidio-specific TAB prices. No changes to shared offers or warehouse.
CREATE TABLE IF NOT EXISTS public.tab_prezzi_verificati (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 codice_cliente text NOT NULL, cac text NOT NULL, linea text NOT NULL CHECK(linea IN ('TRAUMA','PROTESICA')),
 ref text NOT NULL, prezzo numeric NOT NULL CHECK(prezzo>=0 AND prezzo::text NOT IN ('NaN','Infinity','-Infinity')),
 dal date NOT NULL, al date NOT NULL CHECK(al>=dal), sconto boolean NOT NULL DEFAULT false,
 utente text NOT NULL, nota text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(codice_cliente,cac,linea,ref,dal,al)
);
ALTER TABLE public.tab_prezzi_verificati ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tab_prezzi_verificati FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.tab_prezzi_verificati TO service_role;
GRANT USAGE,SELECT ON SEQUENCE public.tab_prezzi_verificati_id_seq TO service_role;
CREATE OR REPLACE FUNCTION public.tab_salva_prezzo_verificato(
 p_cliente text,p_cac text,p_linea text,p_ref text,p_prezzo numeric,p_dal date,p_al date,
 p_utente text,p_nota text,p_sconto boolean DEFAULT false
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE old_row public.tab_prezzi_verificati; new_row public.tab_prezzi_verificati;
BEGIN
 IF nullif(btrim(p_cliente),'') IS NULL OR nullif(btrim(p_cac),'') IS NULL
 OR p_linea IS NULL OR p_linea NOT IN ('TRAUMA','PROTESICA')
 OR nullif(btrim(p_ref),'') IS NULL OR p_ref<>upper(btrim(p_ref))
 OR p_prezzo IS NULL OR p_prezzo::text IN ('NaN','Infinity','-Infinity')
 OR p_sconto IS NULL OR (p_sconto AND p_prezzo<>0) OR (NOT p_sconto AND p_prezzo<=0)
 OR p_dal IS NULL OR p_al IS NULL OR p_al<p_dal
 OR nullif(btrim(p_utente),'') IS NULL OR nullif(btrim(p_nota),'') IS NULL THEN
 RAISE EXCEPTION 'Prezzo, periodo, struttura o motivazione non validi'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.clienti WHERE btrim(codice_cliente)=p_cliente) THEN
 RAISE EXCEPTION 'Struttura non presente in anagrafica'; END IF;
 -- Serialize concurrent edits including overlapping intervals.
 PERFORM pg_advisory_xact_lock(hashtextextended(p_cliente||'|'||p_cac||'|'||p_linea||'|'||p_ref,0));
 SELECT * INTO old_row FROM public.tab_prezzi_verificati
 WHERE codice_cliente=p_cliente AND cac=p_cac AND linea=p_linea AND ref=p_ref AND dal=p_dal AND al=p_al FOR UPDATE;
 IF EXISTS(SELECT 1 FROM public.tab_prezzi_verificati WHERE codice_cliente=p_cliente AND cac=p_cac
 AND linea=p_linea AND ref=p_ref AND dal<=p_al AND al>=p_dal AND id IS DISTINCT FROM old_row.id) THEN
 RAISE EXCEPTION 'Esiste un prezzo verificato per un periodo sovrapposto: usa le stesse date o un periodo distinto'; END IF;
 INSERT INTO public.tab_prezzi_verificati(codice_cliente,cac,linea,ref,prezzo,dal,al,utente,nota,sconto)
 VALUES(p_cliente,p_cac,p_linea,p_ref,p_prezzo,p_dal,p_al,p_utente,p_nota,p_sconto)
 ON CONFLICT(codice_cliente,cac,linea,ref,dal,al) DO UPDATE SET prezzo=excluded.prezzo,
 utente=excluded.utente,nota=excluded.nota,sconto=excluded.sconto,updated_at=now() RETURNING * INTO new_row;
 INSERT INTO public.audit_log(utente,azione,tabella,riferimento,dettagli)
 VALUES(p_utente,'PREZZO_TAB_VERIFICATO','tab_prezzi_verificati',new_row.id::text,
 jsonb_build_object('originale',CASE WHEN old_row.id IS NOT NULL THEN to_jsonb(old_row) ELSE NULL END,
 'corretto',to_jsonb(new_row),'metodo','manuale','timestamp',statement_timestamp())::text);
 RETURN jsonb_build_object('id',new_row.id,'prezzo',new_row.prezzo);
END $$;
REVOKE ALL ON FUNCTION public.tab_salva_prezzo_verificato(text,text,text,text,numeric,date,date,text,text,boolean) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.tab_salva_prezzo_verificato(text,text,text,text,numeric,date,date,text,text,boolean) TO service_role;
