// Isolated PostgreSQL; never connects to production.
import { PGlite } from '@electric-sql/pglite';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const db=new PGlite();
try {
 await db.exec(`create role anon; create role authenticated; create role service_role;
 create table chiusure_mensili_johnson(id bigint generated always as identity primary key,
 mese date,divisione text,nome_file text,importo_totale_jj numeric,nis_totale numeric,
 invoiced_sales_totale numeric,righe_totali integer,stato text);
 create table righe_chiusura_johnson(id bigint generated always as identity primary key,
 chiusura_id bigint references chiusure_mensili_johnson(id),codice text,numero_ordine text,
 riferimento_cliente text,lotto text,quantita numeric,prezzo_unitario numeric,totale_riga numeric,
 raw_data jsonb,regione text,provincia text,bill_to text,account_name text,famiglia_prodotto text,
 cac text,nis numeric,invoiced_sales numeric);`);
 await db.exec(await fs.readFile(new URL('../../sql/import_jj_closure.sql',import.meta.url),'utf8'));
 const rows=[{codice:'413.016S',quantita:1,totale_riga:10,nis:9,invoiced_sales:10,
 riferimento_cliente:'PO-2025',raw_data:{'Product[P. Bravo Franchise]':'Trauma'}}];
 async function run(div='TRAUMA',month='2026-10-01',fingerprint='a'.repeat(64),data=rows){
  return (await db.query('select importa_chiusura_jj($1,$2,$3,$4,$5) as result',[div,month,'file.xlsx',fingerprint,JSON.stringify(data)])).rows[0].result;
 }
 assert.equal((await run()).gia_presente,false);
 assert.equal((await run()).gia_presente,true);
 assert.equal((await db.query('select count(*)::int as n from righe_chiusura_johnson')).rows[0].n,1);
 await assert.rejects(()=>run('PROTESICA'),/divisione o mese/);
 await assert.rejects(()=>run('TRAUMA','2026-11-01'),/divisione o mese/);
 await assert.rejects(()=>run('PROTESICA','2026-10-01','b'.repeat(64)),/Divisione sorgente/);
 await assert.rejects(()=>run('TRAUMA','2026-10-01','c'.repeat(64),[...rows,{codice:'',raw_data:{}}]),/codice/);
 assert.equal((await db.query('select count(*)::int as n from chiusure_mensili_johnson')).rows[0].n,1);
 assert.equal((await db.query("select has_function_privilege('anon','public.importa_chiusura_jj(text,date,text,text,jsonb)','EXECUTE') as allowed")).rows[0].allowed,false);
 const pro=[{...rows[0],raw_data:{'Product[P. Bravo Franchise]':'Protesica'}}];
 await run('PROTESICA','2026-10-01','d'.repeat(64),pro);
 assert.deepEqual((await db.query('select divisione,sum(importo_totale_jj)::int as totale from chiusure_mensili_johnson group by divisione order by divisione')).rows,[{divisione:'PROTESICA',totale:10},{divisione:'TRAUMA',totale:10}]);
 console.log('J&J closures: atomicity, idempotency, division isolation, access: PASS');
} finally {await db.close();}
