-- Reprice only an explicit customer/line change; no backfill and no stock writes.
CREATE OR REPLACE FUNCTION public.anteprima_prezzi_cambio_struttura(
 p_intervento_id bigint, p_codice_cliente text, p_linea text, p_data date
) RETURNS TABLE (
 riga_id bigint, codice text, lotto text, prezzo_precedente numeric,
 prezzo_nuovo numeric, totale_nuovo numeric, offerta_id bigint, esito text
) LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
 SELECT r.id,r.codice,r.lotto,r.prezzo,
        CASE WHEN o.varianti=1 THEN o.prezzo END,
        CASE WHEN o.varianti=1 THEN r.quantita*o.prezzo END,
        CASE WHEN o.varianti=1 THEN o.offerta_id END,
        CASE WHEN o.varianti=1 THEN 'OFFERTA'
             WHEN o.varianti>1 THEN 'OFFERTE DISCORDANTI'
             ELSE 'PREZZO DA INSERIRE' END
 FROM public.righe_intervento r
 LEFT JOIN LATERAL (
   WITH candidati AS (
     SELECT p.prezzo,p.offerta_id,
       CASE WHEN upper(btrim(p.codice))=upper(btrim(r.codice)) THEN 0 ELSE 1 END AS priorita
     FROM public.offerte_prezzi p
     JOIN public.offerte_header h ON h.id=p.offerta_id
     WHERE EXISTS (SELECT 1 FROM public.offerte_clienti c
                   WHERE c.offerta_id=h.id AND c.codice_cliente=p_codice_cliente)
       AND upper(btrim(h.linea))=upper(btrim(p_linea))
       AND lower(coalesce(nullif(btrim(h.stato_record),''),'attivo'))='attivo'
       AND (h.data_inizio IS NULL OR h.data_inizio<=p_data)
       AND (h.data_fine IS NULL OR h.data_fine>=p_data)
       AND regexp_replace(upper(r.codice),'[^A-Z0-9]','','g')<>''
       AND regexp_replace(upper(p.codice),'[^A-Z0-9]','','g')=regexp_replace(upper(r.codice),'[^A-Z0-9]','','g')
       AND p.prezzo>=0 AND p.prezzo::text NOT IN ('NaN','Infinity','-Infinity')
   )
   SELECT count(DISTINCT prezzo) AS varianti,min(prezzo) AS prezzo,min(offerta_id) AS offerta_id
   FROM candidati WHERE priorita=(SELECT min(priorita) FROM candidati)
 ) o ON true
 WHERE r.intervento_id=p_intervento_id ORDER BY r.id;
$$;
REVOKE ALL ON FUNCTION public.anteprima_prezzi_cambio_struttura(bigint,text,text,date) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.anteprima_prezzi_cambio_struttura(bigint,text,text,date) TO service_role;

CREATE OR REPLACE FUNCTION public.ricalcola_prezzi_cambio_struttura()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE r record;
BEGIN
 IF btrim(coalesce(NEW.codice_cliente,''))=btrim(coalesce(OLD.codice_cliente,''))
    AND upper(btrim(coalesce(NEW.linea,'')))=upper(btrim(coalesce(OLD.linea,''))) THEN
   RETURN NEW;
 END IF;
 IF coalesce(NEW.codice_cliente,'')<>'9010013' AND EXISTS (
   SELECT 1 FROM public.righe_intervento WHERE intervento_id=NEW.id AND origine='CONTO DEPOSITO STRUTTURA'
 ) THEN RAISE EXCEPTION 'Materiale della struttura Malzoni: correggere prima la proprietà delle righe'; END IF;
 -- Serialise the row price updates with concurrent material edits.
 PERFORM id FROM public.righe_intervento WHERE intervento_id=NEW.id ORDER BY id FOR UPDATE;
 FOR r IN SELECT * FROM public.anteprima_prezzi_cambio_struttura(
   NEW.id,NEW.codice_cliente,NEW.linea,coalesce(NEW.data_intervento,current_date))
 LOOP
   UPDATE public.righe_intervento SET prezzo=r.prezzo_nuovo,
     totale=r.totale_nuovo,valore=r.totale_nuovo,
     prezzo_source=CASE WHEN r.esito='OFFERTA' THEN 'OFFERTA' ELSE 'RICALCOLO_SENZA_OFFERTA' END,
     prezzo_verificato_da=NULL,prezzo_verificato_at=NULL
   WHERE id=r.riga_id AND intervento_id=NEW.id;
   INSERT INTO public.audit_log(utente,azione,tabella,riferimento,dettagli)
   VALUES(current_user,'RICALCOLO_PREZZO_STRUTTURA','righe_intervento',r.riga_id::text,
     jsonb_build_object('intervento_id',NEW.id,'cliente_precedente',OLD.codice_cliente,
       'cliente_nuovo',NEW.codice_cliente,'linea',NEW.linea,'ref',r.codice,'lotto',r.lotto,
       'prezzo_precedente',r.prezzo_precedente,'prezzo_nuovo',r.prezzo_nuovo,
       'offerta_id',r.offerta_id,'esito',r.esito,'timestamp',statement_timestamp())::text);
 END LOOP;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.ricalcola_prezzi_cambio_struttura() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ricalcola_prezzi_cambio_struttura() TO service_role;
DROP TRIGGER IF EXISTS trg_ricalcola_prezzi_cambio_struttura ON public.interventi;
CREATE TRIGGER trg_ricalcola_prezzi_cambio_struttura
 AFTER UPDATE OF codice_cliente,linea ON public.interventi
 FOR EACH ROW EXECUTE FUNCTION public.ricalcola_prezzi_cambio_struttura();
