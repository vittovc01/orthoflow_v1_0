CREATE OR REPLACE FUNCTION public.prezzi_manuali_struttura(p_codice_cliente text, p_linea text)
RETURNS TABLE(codice_normalizzato text, prezzo numeric)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = public
AS $fn$
 SELECT DISTINCT ON (regexp_replace(upper(r.codice),'[^A-Z0-9]','','g'))
        regexp_replace(upper(r.codice),'[^A-Z0-9]','','g'), r.prezzo
 FROM public.righe_intervento r
 JOIN public.interventi i ON i.id = r.intervento_id
 WHERE trim(i.codice_cliente)=trim(p_codice_cliente)
   AND upper(trim(i.linea))=upper(trim(p_linea))
   AND (r.prezzo_source IN ('MANUALE', 'MANUALE_DIREZIONE', 'MANUALE_MEMORIZZATO') AND r.prezzo>0
        OR r.prezzo_source='SCONTO_MERCE' AND r.prezzo=0)
   AND regexp_replace(upper(r.codice),'[^A-Z0-9]','','g')<>''
 ORDER BY regexp_replace(upper(r.codice),'[^A-Z0-9]','','g'), r.id DESC
$fn$;
REVOKE ALL ON FUNCTION public.prezzi_manuali_struttura(text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.prezzi_manuali_struttura(text,text) TO anon,authenticated,service_role;