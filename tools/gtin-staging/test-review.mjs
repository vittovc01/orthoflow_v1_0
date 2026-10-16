// Isolated PostgreSQL 17 only; no production URL or database credentials.
import { PGlite } from '@electric-sql/pglite';
import fs from 'node:fs/promises';
const db=new PGlite();
try {
 for(const path of ['tests/fixtures/database.sql','sql/malzoni_structure_stock.sql',
   'sql/verified_physical_label_discharge.sql','sql/fix_ai_stock_double_debit.sql']) {
  await db.exec(await fs.readFile(new URL('../../'+path,import.meta.url),'utf8'));
 }
 await db.exec('CREATE TRIGGER trg_movimenti_giacenza AFTER INSERT ON movimenti_magazzino FOR EACH ROW EXECUTE FUNCTION aggiorna_giacenza_da_movimento();');
 for(const path of ['tests/verified_physical_labels.sql','tests/simple_review.sql','tests/discharge_idempotency.sql','tests/server_review_validation.sql']) {
  await db.exec(await fs.readFile(new URL('../../'+path,import.meta.url),'utf8'));
  console.log(path+': PASS');
 }
} finally { await db.close(); }
