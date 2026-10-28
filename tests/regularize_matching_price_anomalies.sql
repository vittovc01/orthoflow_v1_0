BEGIN;
DO $$
DECLARE a bigint; b bigint; c bigint; d bigint; first_id bigint; res jsonb;
BEGIN
 INSERT INTO interventi(codice_cliente,linea) VALUES('BULK-A','TRAUMA') RETURNING id INTO a;
 INSERT INTO interventi(codice_cliente,linea) VALUES('BULK-A','trauma') RETURNING id INTO b;
 INSERT INTO interventi(codice_cliente,linea) VALUES('BULK-B','TRAUMA') RETURNING id INTO c;
 INSERT INTO interventi(codice_cliente,linea) VALUES('BULK-A','PROTESICA') RETURNING id INTO d;
 INSERT INTO righe_intervento(intervento_id,codice,lotto,quantita,prezzo_source)
 VALUES(a,'1504-00-126','LOT-A',1,'DA_VERIFICARE_DIREZIONE') RETURNING id INTO first_id;
 INSERT INTO righe_intervento(intervento_id,codice,lotto,quantita,prezzo,prezzo_source) VALUES
 (b,'150400126','LOT-B',3,0,'DA_VERIFICARE_DIREZIONE'),
 (c,'1504-00-126','LOT-C',2,0,'DA_VERIFICARE_DIREZIONE'),
 (d,'1504-00-126','LOT-D',2,0,'DA_VERIFICARE_DIREZIONE'),
 (a,'OTHER','LOT-E',2,0,'DA_VERIFICARE_DIREZIONE'),
 (a,'150400126','ALREADY',2,99,'MANUALE_DIREZIONE');
 res:=regolarizza_anomalie_prezzo(first_id,12.50,false,'test-direction');
 IF (res->>'righe_regolarizzate')::int<>2 THEN RAISE EXCEPTION 'Wrong batch size: %',res; END IF;
 IF NOT EXISTS(SELECT 1 FROM righe_intervento WHERE intervento_id=b AND lotto='LOT-B'
   AND prezzo=12.5 AND totale=37.5 AND valore=37.5 AND prezzo_verificato_da='test-direction'
   AND prezzo_verificato_at IS NOT NULL AND prezzo_source='MANUALE_DIREZIONE') THEN
   RAISE EXCEPTION 'Quantity-specific total or audit missing'; END IF;
 IF (SELECT count(*) FROM righe_intervento WHERE intervento_id IN(a,b,c,d) AND prezzo_source='DA_VERIFICARE_DIREZIONE')<>3
   OR NOT EXISTS(SELECT 1 FROM righe_intervento WHERE intervento_id=a AND lotto='ALREADY' AND prezzo=99) THEN
   RAISE EXCEPTION 'Unrelated rows changed'; END IF;
 -- Zero price requires the explicit free-goods mode and propagates too.
 UPDATE righe_intervento SET prezzo_source='DA_VERIFICARE_DIREZIONE' WHERE intervento_id IN(a,b) AND lotto IN('LOT-A','LOT-B');
 BEGIN
   PERFORM regolarizza_anomalie_prezzo(first_id,0,false,'test-direction');
   RAISE EXCEPTION 'Accepted invalid price';
 EXCEPTION WHEN raise_exception THEN
   IF SQLERRM='Accepted invalid price' THEN RAISE; END IF;
 END;
 res:=regolarizza_anomalie_prezzo(first_id,0,true,'test-direction');
 IF (res->>'righe_regolarizzate')::int<>2 OR
    (SELECT count(*) FROM righe_intervento WHERE intervento_id IN(a,b) AND lotto IN('LOT-A','LOT-B') AND prezzo=0 AND totale=0 AND valore=0 AND prezzo_source='SCONTO_MERCE')<>2 THEN
   RAISE EXCEPTION 'Free goods not propagated'; END IF;
 IF has_function_privilege('anon','public.regolarizza_anomalie_prezzo(bigint,numeric,boolean,text)','EXECUTE')
   OR has_function_privilege('authenticated','public.regolarizza_anomalie_prezzo(bigint,numeric,boolean,text)','EXECUTE') THEN
   RAISE EXCEPTION 'Public access to server-only operation'; END IF;
END $$;
ROLLBACK;
