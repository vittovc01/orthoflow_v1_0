"""Real browser: save updates only the price workspace, even with expired caches."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import pytest
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def price_preview(tmp_path_factory):
    directory=tmp_path_factory.mktemp('price-save')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    secrets=directory/'secrets.toml'
    secrets.write_text('SUPABASE_URL="http://127.0.0.1:1"\nSUPABASE_SERVICE_KEY="ci-only"\n')
    process=subprocess.Popen([sys.executable,'-m','streamlit','run','tests/fixtures/price_save_preview.py',
      '--server.address','127.0.0.1','--server.port',str(port),'--server.headless','true',
      '--browser.gatherUsageStats','false','--secrets.files',str(secrets)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            assert process.poll() is None
            try:
                with urlopen(f'http://127.0.0.1:{port}/_stcore/health',timeout=1) as response:
                    if response.status==200:break
            except OSError:time.sleep(.1)
        else:raise AssertionError('Price preview did not start')
        yield f'http://127.0.0.1:{port}'
    finally:
        process.terminate();process.wait(timeout=10)


def test_save_refreshes_only_workspace_and_never_rereads_expired_clinical_snapshot(price_preview):
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page()
        page.goto(price_preview)
        field=page.get_by_label('Prezzo unitario verificato (€)',exact=True)
        expect(field).to_be_visible(timeout=30000)
        stats=page.get_by_label('Statistiche test',exact=True)
        expect(stats).to_be_visible(timeout=30000)
        before=json.loads(stats.input_value())
        field.fill('10')
        started=time.perf_counter()
        page.get_by_role('button',name='Salva prezzo e ricalcola anomalie',exact=True).click()
        expect(page.get_by_text('Prezzo salvato per',exact=False)).to_be_visible(timeout=15000)
        expect(page.get_by_text('Nessuna anomalia prezzo TAB nei filtri selezionati.',exact=True)).to_be_visible()
        elapsed=time.perf_counter()-started
        page.get_by_role('button',name='Leggi statistiche test',exact=True).click()
        expect(stats).not_to_have_value(json.dumps(before))
        after=json.loads(stats.input_value())
        assert after['writes']==1 and after['full_runs']==before['full_runs']
        for table in ('jj_recon_records','jj_recon_links','clienti','offerte_header','offerte_clienti','offerte_prezzi','righe_intervento','anomalie_giacenza'):
            assert after['reads'].get(table,0)==before['reads'].get(table,0),table
        assert after['reads']['tab_prezzi_verificati']==before['reads']['tab_prezzi_verificati']+1
        expect(page.get_by_test_id('stException')).to_have_count(0)
        # Explicit refresh must acquire new source/catalog data.
        page.get_by_role('button',name='Aggiorna anomalie TAB',exact=True).click()
        expect(stats).not_to_have_value(json.dumps(after),timeout=15000)
        refreshed=json.loads(stats.input_value())
        assert refreshed['full_runs']>after['full_runs']
        assert refreshed['reads']['jj_recon_records']>after['reads']['jj_recon_records']
        print(f'Price save browser: {elapsed:.3f}s; 1 write, 1 price read, no whole-page rerun or clinical/catalog rereads')
        browser.close()
