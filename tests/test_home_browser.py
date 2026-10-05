"""Verify the actual operational Home on phone and PC with synthetic data."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import tempfile
from urllib.request import urlopen
import pytest
from playwright.sync_api import sync_playwright, expect


@pytest.fixture(scope='module')
def home_server():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    entry=tempfile.NamedTemporaryFile(mode='w',suffix='.py',prefix='.home_preview_',dir=Path(__file__).resolve().parents[1],delete=False)
    entry.write("import runpy\nrunpy.run_path('tests/fixtures/home_preview_app.py', run_name='__main__')\n");entry.close()
    process=subprocess.Popen([sys.executable,'-m','streamlit','run',entry.name,
        '--server.address=127.0.0.1',f'--server.port={port}','--server.headless=true','--browser.gatherUsageStats=false'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if process.poll() is not None:raise AssertionError('Home test server exited')
            try:
                with urlopen(f'http://127.0.0.1:{port}/_stcore/health',timeout=1) as response:
                    if response.status==200:break
            except OSError:time.sleep(.1)
        else:raise AssertionError('Home test server failed to start')
        yield f'http://127.0.0.1:{port}'
    finally:
        process.terminate();process.wait(timeout=10)
        Path(entry.name).unlink(missing_ok=True)


@pytest.mark.parametrize('width,height',[(1440,1100),(390,844)])
def test_home_layout_operational_metrics_and_refresh(home_server,width,height):
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page(viewport={'width':width,'height':height})
        page.goto(home_server)
        expect(page.get_by_role('heading',name='Panoramica operativa')).to_be_visible(timeout=30000)
        expect(page.locator('.home-metric')).to_have_count(4)
        expect(page.get_by_text('Dati non disponibili:',exact=False)).to_have_count(0)
        expect(page.get_by_text('Fatturato',exact=False)).to_have_count(0)
        expect(page.get_by_text('Token AI',exact=False)).to_have_count(0)
        expect(page.get_by_role('link',name='Nuovo scarico sala')).to_be_visible()
        expect(page.get_by_role('link',name='Verifica le anomalie')).to_be_visible()
        expect(page.locator('.home-check').filter(has_text='Anomalie giacenza').get_by_text('1',exact=True)).to_be_visible()
        page.get_by_role('button',name='Aggiorna',exact=False).click()
        expect(page.locator('.home-activity')).to_have_count(6)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        expect(page.get_by_test_id('stException')).to_have_count(0)
        if os.getenv('MOBILE_PREVIEW_DIR'):
            target=Path(os.environ['MOBILE_PREVIEW_DIR']);target.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(target/f'home-{width}.png'),full_page=True)
        browser.close()
