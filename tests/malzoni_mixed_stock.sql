begin;
-- Eseguire dopo sql/malzoni_structure_stock.sql. Tutti i dati di prova vengono annullati.
do $test$
declare v jsonb; v_id bigint; q numeric; n bigint; v_code text:='TEST_MALZONI_'||replace(gen_random_uuid()::text,'-',''); v_before bigint;
begin
 insert into giacenze(codice_magazzino,codice,lotto,quantita,origine) values('MAG1',v_code,'TEST',10,'CONTO DEPOSITO');
 v:=crea_intervento_scarico_ai_flessibile(
 jsonb_build_object('data_intervento','2026-10-01','codice_cliente','9010013','cliente','TEST MALZONI','struttura','TEST MALZONI','linea','TRAUMA','magazzino_scarico','MAG1'),
 jsonb_build_array(
 jsonb_build_object('codice',v_code,'lotto','TEST','quantita',2,'prezzo',100,'conto_deposito_struttura',false),
 jsonb_build_object('codice',v_code,'lotto','TEST','quantita',3,'prezzo',100,'conto_deposito_struttura',true),
 jsonb_build_object('codice',v_code||'ASSENTE','lotto','TEST','quantita',1,'prezzo',50,'conto_deposito_struttura',true)), 'TEST_ROLLBACK');
 v_id:=(v->>'intervento_id')::bigint;
 if (v->>'totale')::numeric <> 550 or (v->>'righe')::int <> 3 then raise exception 'wrong revenue'; end if;
 select quantita into q from giacenze where codice=v_code;
 if q <> 8 then raise exception 'wrong stock %',q; end if;
 select count(*) into n from movimenti_magazzino where riferimento_id=v_id::text and riferimento_tipo='INTERVENTO';
 if n <> 1 then raise exception 'wrong movement count %',n; end if;
 select count(*) into n from anomalie_giacenza where intervento_id=v_id;
 if n <> 0 then raise exception 'structure generated stock anomaly'; end if;
 select count(*) into n from righe_intervento where intervento_id=v_id and origine='CONTO DEPOSITO STRUTTURA';
 if n <> 2 then raise exception 'wrong ownership persistence'; end if;
 select count(*) into v_before from interventi;
 begin
  perform crea_intervento_scarico_ai_flessibile(jsonb_build_object('data_intervento','2026-10-01','codice_cliente','OTHER','cliente','TEST','magazzino_scarico','MAG1'),
  jsonb_build_array(jsonb_build_object('codice',v_code,'lotto','TEST','quantita',1,'prezzo',100,'conto_deposito_struttura',true)), 'TEST_ROLLBACK');
  raise exception 'Expected Malzoni restriction';
 exception when others then
  if sqlerrm <> 'CONTO_DEPOSITO_STRUTTURA_SOLO_MALZONI' then raise; end if;
 end;
 select count(*) into n from interventi;
 if n <> v_before then raise exception 'non-Malzoni left partial intervention'; end if;
end $test$;
rollback;