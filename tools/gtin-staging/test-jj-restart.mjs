import {PGlite} from '@electric-sql/pglite';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const script=await fs.readFile(new URL('../../sql/jj_reconciliation_restart_20261030.sql',import.meta.url),'utf8');
const administrative=['jj_recon_links','jj_recon_audit','jj_recon_records','esiti_chiusura_johnson','righe_chiusura_johnson','chiusure_mensili_johnson','riconciliazioni_reintegro_jj','riconciliazioni_johnson','righe_ddt_johnson','ddt_johnson','fatture_johnson','righe_ordini_johnson','ordini_johnson'];
const operational=['interventi','righe_intervento','movimenti_magazzino','giacenze'];
const db=new PGlite();
try {
 await db.exec('create role anon;create role authenticated;create role service_role;');
 for (const table of [...administrative,...operational]) {
  await db.exec(`create table ${table}(id bigint generated always as identity primary key, payload jsonb not null);`);
  await db.query(`insert into ${table}(payload) values($1)`,[JSON.stringify({ref:'413.016S',lot:'original',quantity:2})]);
 }
 await db.exec('alter table jj_recon_links add constraint closure_fk foreign key(id) references jj_recon_records(id);');
 await db.exec('alter table righe_ordini_johnson add constraint order_fk foreign key(id) references ordini_johnson(id);');
 const before={};for(const t of [...administrative,...operational])before[t]=(await db.query(`select * from ${t}`)).rows;
 // A trigger modifying operational data must abort the entire reset and snapshot.
 await db.exec(`create function unexpected_write() returns trigger language plpgsql as $$begin update interventi set payload='{}';return old;end$$;
 create trigger unexpected_write before delete on jj_recon_records for each row execute function unexpected_write();`);
 await assert.rejects(()=>db.exec(script),/Dati operativi modificati/);
 assert.equal((await db.query('select count(*)::int n from jj_recon_records')).rows[0].n,1);
 assert.deepEqual((await db.query('select * from interventi')).rows,before.interventi);
 await db.exec('drop trigger unexpected_write on jj_recon_records');
 await db.exec(script);
 const snapshot=(await db.query('select snapshot from orthoflow_maintenance.reconciliation_resets')).rows[0].snapshot;
 for(const t of administrative){
  assert.equal((await db.query(`select count(*)::int n from ${t}`)).rows[0].n,0);
  assert.deepEqual(snapshot[t],before[t]);
 }
 for(const t of operational)assert.deepEqual((await db.query(`select * from ${t}`)).rows,before[t]);
 // Later user imports survive a repeated application of the one-off script.
 await db.query('insert into jj_recon_records(payload) values($1)',[JSON.stringify({ref:'NEW'})]);
 await db.exec(script);
 assert.equal((await db.query('select count(*)::int n from jj_recon_records')).rows[0].n,1);
 assert.equal((await db.query('select count(*)::int n from orthoflow_maintenance.reconciliation_resets')).rows[0].n,1);
 assert.equal((await db.query("select has_schema_privilege('anon','orthoflow_maintenance','USAGE') p")).rows[0].p,false);
 assert.equal((await db.query("select has_table_privilege('service_role','orthoflow_maintenance.reconciliation_resets','SELECT') p")).rows[0].p,false);
 console.log('Reconciliation restart: full snapshots, empty ledgers, unchanged operations, rollback, replay and private access: PASS');
}finally{await db.close();}
