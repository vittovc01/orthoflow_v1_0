// Isolated PostgreSQL/WASM staging only: no database URLs, keys or network client.
import { PGlite } from '@electric-sql/pglite';
import fs from 'node:fs/promises';
const [payloadPath,dataDir,reportPath]=process.argv.slice(2);
if(!payloadPath||!dataDir||!reportPath)throw Error('Usage: run.mjs payload.json local-data-directory report.json');
if(dataDir.includes('://'))throw Error('Local staging directory required');
const payload=JSON.parse(await fs.readFile(payloadPath,'utf8'));
const db=new PGlite(dataDir);
try {
 await db.exec("SET orthoflow.environment='staging'; DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon; END IF; IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated; END IF; IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role BYPASSRLS; END IF; END $$;");
 await db.exec(await fs.readFile(new URL('../../sql/staging_gtin_catalog.sql',import.meta.url),'utf8'));
 const args=[JSON.stringify(payload.rows),payload.source_file,payload.source_version,payload.source_sha256,payload.discarded.length];
 const invoke=async values=>(await db.query('select public.import_articoli_gtin_staging($1::jsonb,$2,$3,$4,$5) as report',values)).rows[0].report;
 const first=await invoke(args),repeat=await invoke(args);
 const before=await db.query('select count(*)::int as n from public.articoli_gtin');
 const conflict=[{...payload.rows[0],ref:'CONFLICT-TEST'}];let conflictBlocked=false;
 try {await invoke([JSON.stringify(conflict),...args.slice(1)]);} catch(e){if(String(e.message).includes('GTIN_REF_CONFLICT'))conflictBlocked=true;else throw e;}
 const after=await db.query('select count(*)::int as n from public.articoli_gtin');
 if(!conflictBlocked||before.rows[0].n!==after.rows[0].n||repeat.nuove||repeat.aggiornate)throw Error('Import safety regression');
 // Validate the update branch without altering the imported catalogue.
 await db.exec('begin');
 const updateRows=[{...payload.rows[0],descrizione:'UPDATE-PATH-TEST',categoria:'TEST'}];
 const updateReport=await invoke([JSON.stringify(updateRows),...args.slice(1)]);
 await db.exec('rollback');
 if(updateReport.aggiornate!==1||updateReport.nuove!==0)throw Error('Update count regression');
 await db.exec('set role anon');let anonDenied=false;
 try{await db.query('select * from public.articoli_gtin limit 1');}catch(e){anonDenied=String(e.message).includes('permission denied');}
 await db.exec('reset role');
 if(!anonDenied)throw Error('Anonymous catalogue access must be denied');

 const report={environment:'isolated-local-staging-pglite',server_version:(await db.query('select version() as version')).rows[0].version,
   source_file:payload.source_file,source_version:payload.source_version,source_sha256:payload.source_sha256,
   input_rows:payload.input_rows,missing_categories:payload.missing_categories,
   first_import:first,idempotent_repeat:repeat,conflicting_ref_blocked:conflictBlocked,
   rows_after_conflict:after.rows[0].n,update_path_test:updateReport,update_test_rolled_back:true,anonymous_access_denied:anonDenied};
 await fs.writeFile(reportPath,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
} finally {await db.close();}
