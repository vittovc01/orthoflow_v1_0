import {PGlite} from '@electric-sql/pglite';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const db=new PGlite();
try{
 await db.exec(`create role anon;create role authenticated;create role service_role bypassrls;
 create table clienti(codice_cliente text);insert into clienti values('ASL');
 create table audit_log(id bigserial,utente text,azione text,tabella text,riferimento text,dettagli text);
 grant select on clienti to service_role;grant insert on audit_log to service_role;grant usage on sequence audit_log_id_seq to service_role;
 create table unchanged_ledger(id int,quantity int);insert into unchanged_ledger values(1,4);`);
 const migration=await fs.readFile(new URL('../../sql/tab_verified_prices.sql',import.meta.url),'utf8');
 await db.exec(migration);await db.exec(migration);
 const base=['ASL','100','TRAUMA','R1','10','2026-01-01','2026-12-31','user','Customer ordine 1',false];
 const save=(changes={})=>{const args=[...base];for(const [k,v] of Object.entries(changes))args[Number(k)]=v;return db.query('select tab_salva_prezzo_verificato($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) r',args)};
 for(const changes of [{4:'NaN'},{4:'Infinity'},{4:'-1'},{4:'0'},{4:null},{9:null},{5:null},{6:'2025-01-01'},{7:''},{8:''},{0:'UNKNOWN'},{1:null},{2:'OTHER'},{3:''}])await assert.rejects(()=>save(changes));
 assert.equal((await db.query('select count(*)::int n from tab_prezzi_verificati')).rows[0].n,0);
 await db.exec('set role service_role');
 await save();await save({4:'12'});await save({1:'200',4:'20'});await save({2:'PROTESICA',4:'30'});await save({5:'2027-01-01',6:'2027-12-31',4:'40'});
 await save({3:'FREE',4:'0',9:true});await save({1:'',4:'55'});
 await assert.rejects(()=>save({5:'2026-06-01',6:'2027-06-01'}),/sovrapposto/);
 await db.exec('reset role');
 const rows=(await db.query('select * from tab_prezzi_verificati')).rows;assert.equal(rows.length,6);
 assert.equal(rows.find(r=>r.cac==='100'&&r.linea==='TRAUMA'&&r.ref==='R1'&&new Date(r.dal).getUTCFullYear()===2026).prezzo,'12');
 const audit=(await db.query('select dettagli from audit_log order by id')).rows;
 assert.equal(audit.length,7);assert.equal(JSON.parse(audit[1].dettagli).originale.prezzo,10);assert.equal(JSON.parse(audit[1].dettagli).corretto.prezzo,12);
 assert.equal(JSON.parse(audit[1].dettagli).metodo,'manuale');assert.ok(JSON.parse(audit[1].dettagli).timestamp);
 assert.equal((await db.query('select quantity from unchanged_ledger')).rows[0].quantity,4);
 const signature='public.tab_salva_prezzo_verificato(text,text,text,text,numeric,date,date,text,text,boolean)';
 for(const role of ['anon','authenticated']){
  assert.equal((await db.query('select has_function_privilege($1,$2,\'EXECUTE\') ok',[role,signature])).rows[0].ok,false);
  assert.equal((await db.query('select has_table_privilege($1,\'public.tab_prezzi_verificati\',\'SELECT\') ok',[role])).rows[0].ok,false);
 }
 assert.equal((await db.query("select relrowsecurity from pg_class where oid='tab_prezzi_verificati'::regclass")).rows[0].relrowsecurity,true);
 console.log('TAB prices: validation, audit, upsert, CAC/division/period isolation and service-only permissions passed');
}finally{await db.close();}
