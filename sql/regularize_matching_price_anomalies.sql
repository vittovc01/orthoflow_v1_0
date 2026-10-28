-- One atomic update, callable only by the authorised Python server.
CREATE OR REPLACE FUNCTION public.regolarizza_anomalie_prezzo(
 p_riga_id bigint, p_prezzo numeric, p_sconto boolean, p_utente text
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
DECLARE
 v_cliente text; v_linea text; v_codice text; v_count integer; v_price numeric;
BEGIN
 IF nullif(trim(p_utente),'') IS NULL OR p_sconto IS NULL OR p_prezzo IS NULL
    OR p_prezzo::text IN ('NaN','Infinity','-Infinity')
    OR (p_sconto AND p_prezzo<>0) OR (NOT p_sconto AND p_prezzo<=0) THEN
   RAISE EXCEPTION 'Prezzo o utente non valido';
 END IF;
 SELECT trim(i.codice_cliente), upper(trim(i.linea)),
        regexp_replace(upper(r.codice),'[^A-Z0-9]','','g')
 INTO v_cliente,v_linea,v_codice
 FROM public.righe_intervento r JOIN public.interventi i ON i.id=r.intervento_id
 WHERE r.id=p_riga_id AND r.prezzo_source='DA_VERIFICARE_DIREZIONE';
 IF NOT FOUND THEN RAISE EXCEPTION 'Anomalia non disponibile: aggiorna la pagina'; END IF;
 IF coalesce(v_cliente,'')='' OR coalesce(v_linea,'')='' OR coalesce(v_codice,'')='' THEN
   RAISE EXCEPTION 'Codice cliente, linea o codice prodotto mancante: completa i dati intervento';
 END IF;
 v_price := p_prezzo;
 UPDATE public.righe_intervento r SET
   prezzo=v_price, totale=v_price*coalesce(r.quantita,0), valore=v_price*coalesce(r.quantita,0),
   prezzo_source=CASE WHEN p_sconto THEN 'SCONTO_MERCE' ELSE 'MANUALE_DIREZIONE' END,
   prezzo_verificato_da=trim(p_utente),prezzo_verificato_at=now()
 FROM public.interventi i
 WHERE i.id=r.intervento_id AND trim(i.codice_cliente)=v_cliente
   AND upper(trim(i.linea))=v_linea
   AND regexp_replace(upper(r.codice),'[^A-Z0-9]','','g')=v_codice
   AND r.prezzo_source='DA_VERIFICARE_DIREZIONE';
 GET DIAGNOSTICS v_count=ROW_COUNT;
 RETURN jsonb_build_object('righe_regolarizzate',v_count);
END;
$$;
REVOKE ALL ON FUNCTION public.regolarizza_anomalie_prezzo(bigint,numeric,boolean,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.regolarizza_anomalie_prezzo(bigint,numeric,boolean,text) TO service_role;
