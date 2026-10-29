import {PGlite} from '@electric-sql/pglite';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const db=new PGlite();
try {
 await db.exec('create role anon;create role authenticated;create role service_role;');
 await db.exec(await fs.readFile(new URL('../../sql/jj_guided_reconciliation.sql',import.meta.url),'utf8'));
 const line={key:'L',ref:'413.016S',quantity:2,cac:'100',po:'PO1',invoice:'F1',price:'10',total:'20',lot:''};
 async function imp(kind,key,lines=[line],extra={}){
  return (await db.query('select jj_import_records($1,$2,$3,$4,$5) as r',[kind,'TRAUMA','file.xlsx',JSON.stringify([{source_key:key,payload:{lines,...(kind==='CHIUSURA'?{month:key}:{}),...extra}}]),'test-user'])).rows[0].r;
 }
 async function id(kind,key){return (await db.query('select id from jj_recon_records where kind=$1 and source_key=$2',[kind,key])).rows[0].id;}
 assert.equal((await imp('CHIUSURA','2026-10')).nuovi,1);
 assert.equal((await imp('ORDINE','PO1',[{...line,invoice:''}])).nuovi,1);
 assert.equal((await imp('IMPIANTO','DDT1',[{...line,lot:'LOT1'}],{event_date:'2026-09-01',customer:'ASL SALERNO'})).nuovi,1);
 assert.equal((await imp('ORDINE','PO1',[{...line,invoice:''}])).invariati,1);
 const c=await id('CHIUSURA','2026-10'),o=await id('ORDINE','PO1'),i=await id('IMPIANTO','DDT1');
 const link={closure_id:c,closure_line:'L',order_id:o,order_line:'L',implant_id:i,implant_line:'L',quantity:1};
 async function confirm(links=[link]){return (await db.query('select jj_confirm_links($1,$2) as n',[JSON.stringify(links),'reviewer'])).rows[0].n;}
 async function review(action,id=c,payload=null){return db.query('select jj_review_record($1,$2,$3,$4,$5)',[id,action,payload&&JSON.stringify(payload),'Documenti verificati', 'reviewer']);}
 assert.equal(await confirm(),1);assert.equal(await confirm(),0);
 await assert.rejects(()=>review('CLOSE'),/Restano righe/);
 // A second month can use the remaining quantity, not consume the same implant twice.
 await imp('CHIUSURA','2026-11',[{...line,key:'N',quantity:1,total:'10',invoice:'F2'}]);
 const nov=await id('CHIUSURA','2026-11');
 await assert.rejects(()=>confirm([{...link,closure_id:nov,closure_line:'N',quantity:2}]),/già utilizzata|discordante/);
 assert.equal(await confirm([{...link,closure_id:nov,closure_line:'N',quantity:1}]),1);
 await imp('CHIUSURA','2026-12',[{...line,key:'D',quantity:1,total:'10',invoice:'F3'}]);
 const dec=await id('CHIUSURA','2026-12');
 await assert.rejects(()=>confirm([{...link,closure_id:dec,closure_line:'D',quantity:1}]),/già utilizzata/);
 // Null invoice in orders permits a separately verified invoice, but is never fabricated.
 await review('EDIT',o,{lines:[{...line,invoice:''}]});
 assert.equal((await db.query('select count(*)::int as n from jj_recon_links where revoked_at is null')).rows[0].n,0);
 await assert.rejects(()=>confirm([link,{...link,implant_line:'MISSING'}]),/discordanti/);
 assert.equal((await db.query('select count(*)::int as n from jj_recon_links where revoked_at is null')).rows[0].n,0);
 assert.equal(await confirm([{...link,quantity:2}]),1);
 await review('CLOSE');
 assert.ok((await db.query('select closed_at from jj_recon_records where id=$1',[c])).rows[0].closed_at);
 // Changed linked imports are staged; they reopen the month but retain old allocations until reviewed.
 const changed=await imp('IMPIANTO','DDT1',[{...line,quantity:3,total:'30',lot:'LOT1'}],{event_date:'2026-09-01',customer:'ASL SALERNO'});
 assert.equal(changed.revisioni_da_verificare,1);
 assert.equal((await db.query('select closed_at from jj_recon_records where id=$1',[c])).rows[0].closed_at,null);
 await assert.rejects(()=>review('CLOSE'),/revisioni pendenti/);
 await review('ACCEPT_REVISION',i);
 assert.equal((await db.query('select count(*)::int as n from jj_recon_links where revoked_at is null')).rows[0].n,0);
 assert.equal((await db.query('select count(*)::int as n from jj_recon_links')).rows[0].n,3);
 // No global mapping of a multi-presidio customer.
 await assert.rejects(()=>db.query('select jj_map_customer($1,$2,$3,$4)',['ASL SALERNO','100','TRAUMA','reviewer']),/singolo documento/);
 for(const quantity of [0,-1,1.5,'NaN'])await assert.rejects(()=>imp('ORDINE','BAD'+quantity,[{...line,quantity}]));
 await assert.rejects(()=>confirm([{...link,quantity:0}]));
 // A mismatched client is rejected even if a modified page submits the request.
 await review('EDIT',i,{lines:[{...line,cac:'200',lot:'LOT1'}]});
 await assert.rejects(()=>confirm(),/presidio/);
 assert.equal((await db.query("select has_function_privilege('anon','public.jj_confirm_links(jsonb,text)','EXECUTE') as p")).rows[0].p,false);
 const audit=await db.query("select count(*)::int as n from jj_recon_audit where actor='reviewer' and created_at is not null");assert.ok(audit.rows[0].n>=5);
 await imp('IMPIANTO','DDT2',[{...line,cac:''}],{customer:'Clinica A'});
 await db.query('select jj_map_customer($1,$2,$3,$4)',['Clinica A','100','TRAUMA','reviewer']);
 const mapped=(await db.query("select payload from jj_recon_records where source_key='DDT2'")).rows[0].payload;
 assert.equal(mapped.cac,'100');assert.equal(mapped.lines[0].cac,'100');
 console.log('Guided reconciliation: replay, partials, cross-month caps, revisions, server validation and audit: PASS');
}finally{await db.close();}
