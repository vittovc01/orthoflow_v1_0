begin;
do $test$
declare iid bigint; rid bigint; result jsonb; stock_before numeric; stock_after numeric; log_count bigint;
begin
 select coalesce(sum(quantita),0) into stock_before from giacenze;
 insert into interventi(data_intervento,codice_cliente,cliente,linea,cartella_clinica)
 values(current_date,'TEST_DELETE','TEST DELETE','PROTESICA','TEST_DELETE') returning id into iid;
 insert into righe_intervento(intervento_id,codice,lotto,quantita,prezzo,totale,origine)
 values(iid,'TEST_DELETE','TEST',1,25,25,'CONTO DEPOSITO STRUTTURA') returning id into rid;
 insert into documenti_impianto(intervento_id,nome_file) values(iid::text,'TEST_DELETE.pdf');
 insert into anomalie_giacenza(intervento_id,codice,lotto,stato) values(iid,'TEST_DELETE','TEST','DA_VERIFICARE');
 result:=elimina_intervento_completo(iid,'TEST_DELETE');
 if exists(select 1 from interventi where id=iid) or exists(select 1 from righe_intervento where intervento_id=iid)
 or exists(select 1 from documenti_impianto where intervento_id=iid::text)
 or exists(select 1 from anomalie_giacenza where intervento_id=iid) then raise exception 'Incomplete cleanup'; end if;
 if (result->>'righe')::integer<>1 or jsonb_array_length(result->'documenti')<>1 then raise exception 'Missing result details'; end if;
 if not exists(select 1 from audit_log where riferimento=iid::text and azione='ELIMINAZIONE_COMPLETA'
 and dettagli::jsonb->'intervento'->>'cartella_clinica'='TEST_DELETE') then raise exception 'Missing audit'; end if;
 select coalesce(sum(quantita),0) into stock_after from giacenze;
 if stock_after is distinct from stock_before then raise exception 'Stock changed'; end if;
 select count(*) into log_count from audit_log;
 begin
  perform elimina_intervento_completo(iid,'TEST_DELETE');
  raise exception 'Second deletion unexpectedly succeeded';
 exception when raise_exception then
  if sqlerrm<>'INTERVENTO_NON_PRESENTE' then raise; end if;
 end;
 if (select count(*) from audit_log)<>log_count then raise exception 'Duplicate audit'; end if;
 if has_function_privilege('anon','public.elimina_intervento_completo(bigint,text)','EXECUTE')
 or has_function_privilege('authenticated','public.elimina_intervento_completo(bigint,text)','EXECUTE')
 then raise exception 'Client role has destructive RPC access'; end if;
end $test$;
rollback;
