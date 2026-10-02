CREATE OR REPLACE FUNCTION public.chiudi_anomalia_materiale_struttura()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=public AS $fn$
BEGIN
 IF NEW.origine='CONTO DEPOSITO STRUTTURA'
 AND EXISTS(SELECT 1 FROM interventi WHERE id=NEW.intervento_id AND codice_cliente='9010013')
 AND NOT EXISTS(SELECT 1 FROM righe_intervento r WHERE r.intervento_id=NEW.intervento_id
  AND regexp_replace(upper(r.codice),'[^A-Z0-9]','','g')=regexp_replace(upper(NEW.codice),'[^A-Z0-9]','','g')
  AND upper(trim(coalesce(r.lotto,'')))=upper(trim(coalesce(NEW.lotto,'')))
  AND r.origine IS DISTINCT FROM 'CONTO DEPOSITO STRUTTURA') THEN
 UPDATE anomalie_giacenza a SET stato='RISOLTA',
 motivo=concat_ws(' · ',a.motivo,'Conto deposito struttura confermato: disponibilità del nostro magazzino non richiesta'),
 risolto_da='AUTO_CONTO_DEPOSITO_STRUTTURA',risolto_at=now()
 WHERE a.intervento_id=NEW.intervento_id AND a.stato='DA_VERIFICARE'
 AND regexp_replace(upper(a.codice),'[^A-Z0-9]','','g')=regexp_replace(upper(NEW.codice),'[^A-Z0-9]','','g')
 AND upper(trim(coalesce(a.lotto,'')))=upper(trim(coalesce(NEW.lotto,'')));
 END IF;
 RETURN NEW;
END $fn$;
CREATE OR REPLACE TRIGGER trg_chiudi_anomalia_materiale_struttura
AFTER INSERT OR UPDATE OF origine,codice,lotto,intervento_id ON public.righe_intervento
FOR EACH ROW EXECUTE FUNCTION public.chiudi_anomalia_materiale_struttura();
