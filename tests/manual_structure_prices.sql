begin;
do $test$
declare a bigint; b bigint; code text:='TESTMEM'||upper(replace(gen_random_uuid()::text,'-','')); p numeric;
begin
 insert into interventi(data_intervento,codice_cliente,cliente,linea) values(current_date,'TEST_CUSTOMER_MEMORY','TEST','TRAUMA') returning id into a;
 insert into interventi(data_intervento,codice_cliente,cliente,linea) values(current_date,'TEST_OTHER_MEMORY','TEST','TRAUMA') returning id into b;
 insert into righe_intervento(intervento_id,codice,lotto,quantita,prezzo,prezzo_source) values
 (a,code||'-01','TEST',1,120,'MANUALE'),(b,code||'-01','TEST',1,999,'MANUALE');
 select prezzo into p from prezzi_manuali_struttura('TEST_CUSTOMER_MEMORY','trauma') where codice_normalizzato=code||'01';
 if p is distinct from 120 then raise exception 'Customer or normalization mismatch'; end if;
 insert into righe_intervento(intervento_id,codice,lotto,quantita,prezzo,prezzo_source) values(a,code||'01','TEST',1,0,'DA_VERIFICARE_DIREZIONE');
 select prezzo into p from prezzi_manuali_struttura('TEST_CUSTOMER_MEMORY','TRAUMA') where codice_normalizzato=code||'01';
 if p<>120 then raise exception 'Provisional zero overwrote price'; end if;
 insert into righe_intervento(intervento_id,codice,lotto,quantita,prezzo,prezzo_source) values(a,code||'01','TEST',1,130,'MANUALE');
 select prezzo into p from prezzi_manuali_struttura('TEST_CUSTOMER_MEMORY','TRAUMA') where codice_normalizzato=code||'01';
 if p is distinct from 130 then raise exception 'Latest manual price not used'; end if;
 if exists(select 1 from prezzi_manuali_struttura('TEST_CUSTOMER_MEMORY','PROTESICA') where codice_normalizzato=code||'01') then raise exception 'Division leak'; end if;
 insert into righe_intervento(intervento_id,codice,lotto,quantita,prezzo,prezzo_source) values(a,code||'-02','TEST',1,0,'SCONTO_MERCE');
 select prezzo into p from prezzi_manuali_struttura('TEST_CUSTOMER_MEMORY','TRAUMA') where codice_normalizzato=code||'02';
 if p is distinct from 0 then raise exception 'Explicit free goods missing'; end if;
end $test$;
rollback;