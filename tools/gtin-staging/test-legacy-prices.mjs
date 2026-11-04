import {PGlite} from '@electric-sql/pglite';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const db=new PGlite();
try{
 await db.exec(`create role anon;create role authenticated;create role service_role bypassrls;
 create table clienti(codice_cliente text,descrizione text,descrizione_cliente text);
 insert into clienti values('C1','Clinic 1',null),('C2','Clinic 2',null),('C3','ASL',null);
 create table interventi(id bigserial primary key,codice_cliente text,linea text,data_intervento date,stato_record text default 'Attivo');
 create table righe_intervento(id bigserial primary key,intervento_id bigint,codice text,prezzo numeric,prezzo_source text,prezzo_verificato_at timestamptz,prezzo_verificato_da text,stato_record text default 'Attivo');
 create table jj_recon_records(kind text,division text,payload jsonb);
 insert into jj_recon_records values('IMPIANTO','TRAUMA','{"customer_code":"C1","customer":"Clinic 1","cac":"100","lines":[{"ref":"R51"},{"ref":"A12"},{"ref":"A-12"}]}'),
 ('IMPIANTO','TRAUMA','{"customer_code":"C3","cac":"300","lines":[]}'),('IMPIANTO','TRAUMA','{"customer_code":"C3","cac":"301","lines":[]}');
 create table offerte_header(id bigint,linea text,stato_record text,data_inizio date,data_fine date);
 create table offerte_clienti(offerta_id bigint,codice_cliente text);
 create table offerte_prezzi(offerta_id bigint,codice text,prezzo numeric);
 insert into offerte_header values(1,'TRAUMA','Attivo','2026-01-01','2026-12-31');
 insert into offerte_clienti values(1,'C1');insert into offerte_prezzi values(1,'R3',9),(1,'EQUAL',10);
 create table audit_log(id bigserial,utente text,azione text,tabella text,riferimento text,dettagli text);
 grant select,update on clienti,interventi,righe_intervento,jj_recon_records,offerte_header,offerte_clienti,offerte_prezzi to service_role;
 grant select,insert on audit_log to service_role;grant usage on sequence audit_log_id_seq to service_role;`);
 await db.exec(await fs.readFile(new URL('../../sql/tab_verified_prices.sql',import.meta.url),'utf8'));
 const dir=new URL('../../supabase/migrations/',import.meta.url);
 const files=(await fs.readdir(dir)).filter(f=>f.endsWith('_recover_legacy_manual_prices.sql'));assert.equal(files.length,1);
 await db.exec(await fs.readFile(new URL(files[0],dir),'utf8'));
 async function legacy(ref,price,source='MANUALE_DIREZIONE',code='C1',day='2026-10-01',state='Attivo'){
  const id=(await db.query('insert into interventi(codice_cliente,linea,data_intervento) values($1,\'TRAUMA\',$2) returning id',[code,day])).rows[0].id;
  await db.query('insert into righe_intervento(intervento_id,codice,prezzo,prezzo_source,prezzo_verificato_da,prezzo_verificato_at,stato_record) values($1,$2,$3,$4,\'original-user\',\'2026-10-10\',$5)',[id,ref,price,source,state]);
 }
 await legacy('R1',10);await legacy('R1',10,'MANUALE_MEMORIZZATO');await legacy('R2',8);
 await legacy('R3',8);await legacy('R4',10);await legacy('R4',11);await legacy('R5.1',8);
 await legacy('FREE',0,'SCONTO_MERCE');await legacy('FREE',0,'MANUALE_MEMORIZZATO');await legacy('A.12',8);await legacy('INVALID',0);await legacy('INVALID2','NaN');
 await legacy('R1',19,'MANUALE','C2');await legacy('AMBIG',20,'MANUALE','C3');await legacy('ORPHAN',1,'MANUALE','UNKNOWN');
 await legacy('NODATE',1,'MANUALE','C1',null);await legacy('INACTIVE',1,'MANUALE','C1','2026-10-01','Inattivo');await legacy('EQUAL',10);
 await db.query('select tab_salva_prezzo_verificato($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)',['C1','100','TRAUMA','R2',77,'2026-03-01','2026-12-31','new-user','keep-me',false]);
 const before=(await db.query('select * from righe_intervento order by id')).rows;
 const original=(await db.query('select * from tab_prezzi_verificati order by id')).rows;
 const recover=async apply=>(await db.query('select tab_recupera_prezzi_storici($1,$2) result',[apply,'migration-user'])).rows[0].result;
 await db.exec('set role service_role');
 const preview=await recover(false);
 const state=(ref,code='C1')=>preview.dettaglio.filter(r=>r.ref===ref&&r.codice_cliente===code).map(r=>r.stato);
 assert.deepEqual(state('R1'),['RECUPERABILE']);assert.deepEqual(state('R2'),['GIA_PRESENTE']);
 assert.deepEqual(state('R3'),['DA_VERIFICARE_OFFERTA']);assert.deepEqual(state('R4'),['DA_VERIFICARE_PREZZI_STORICI']);
 assert.deepEqual(state('R51'),['RECUPERABILE']);assert.deepEqual(state('A.12'),['DA_VERIFICARE_REF']);assert.deepEqual(state('FREE'),['RECUPERABILE']);
 assert.deepEqual(state('INVALID'),['DA_VERIFICARE_DATI']);assert.deepEqual(state('INVALID2'),['DA_VERIFICARE_DATI']);
 assert.deepEqual(state('AMBIG','C3'),['DA_VERIFICARE_PRESIDIO','DA_VERIFICARE_PRESIDIO']);
 assert.deepEqual(state('ORPHAN','UNKNOWN'),['DA_VERIFICARE_DATI']);assert.deepEqual(state('NODATE'),['DA_VERIFICARE_DATI']);assert.deepEqual(state('INACTIVE'),[]);
 assert.equal((await db.query('select count(*)::int n from tab_prezzi_verificati')).rows[0].n,1);
 await db.exec('reset role');
 await db.exec(`alter table audit_log add constraint fail_test check(not (utente='rollback-test' and dettagli like '%FREE%'));set role service_role;`);
 const auditBefore=(await db.query('select count(*)::int n from audit_log')).rows[0].n;
 await assert.rejects(()=>db.query('select tab_recupera_prezzi_storici(true,$1)',['rollback-test']));
 assert.equal((await db.query('select count(*)::int n from tab_prezzi_verificati')).rows[0].n,1);
 assert.equal((await db.query('select count(*)::int n from audit_log')).rows[0].n,auditBefore);
 await db.exec('reset role;alter table audit_log drop constraint fail_test;set role service_role;');
 const result=await recover(true);assert.equal(result.prezzi_recuperati,5);
 const values=(await db.query('select * from tab_prezzi_verificati order by id')).rows;
 assert.deepEqual(values[0],original[0]);assert.equal(values.find(r=>r.ref==='R1'&&r.codice_cliente==='C1').prezzo,'10');
 assert.equal(values.find(r=>r.ref==='R1'&&r.codice_cliente==='C2').prezzo,'19');assert.equal(values.find(r=>r.ref==='FREE').prezzo,'0');
 assert.equal(values.some(r=>['R3','R4','A.12','AMBIG','INVALID'].includes(r.ref)),false);
 assert.equal(values.find(r=>r.ref==='R1'&&r.codice_cliente==='C1').cac,'100');
 const evidence=result.dettaglio.find(r=>r.ref==='R1'&&r.codice_cliente==='C1');assert.equal(evidence.provenienza.length,2);
 assert.equal(evidence.provenienza[0].verificato_da,'original-user');assert.ok(evidence.provenienza[0].verificato_il);
 const audit=(await db.query('select * from audit_log order by id')).rows;
 assert.ok(audit.some(r=>r.azione==='RECUPERO_PREZZI_STORICI'&&JSON.parse(r.dettagli).prezzi_recuperati===5));
 const second=await recover(true);assert.equal(second.prezzi_recuperati,0);
 assert.equal((await db.query('select count(*)::int n from audit_log')).rows[0].n,audit.length);
 assert.deepEqual((await db.query('select * from righe_intervento order by id')).rows,before);
 await db.exec('reset role');
 for(const role of ['anon','authenticated'])for(const signature of ['public.tab_anteprima_prezzi_storici()','public.tab_recupera_prezzi_storici(boolean,text)']){
  assert.equal((await db.query('select has_function_privilege($1,$2,\'EXECUTE\') ok',[role,signature])).rows[0].ok,false);
 }
 console.log('Legacy recovery: preview, conflicts, existing-price protection, CAC isolation, zero prices, provenance and idempotency passed');
}finally{await db.close();}
