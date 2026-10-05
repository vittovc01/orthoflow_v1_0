"""Verify real office modules through the app's HTTP and WebSocket gateway."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import pytest
from playwright.sync_api import sync_playwright, expect


@pytest.fixture(scope='module')
def unified_server(tmp_path_factory):
    directory=tmp_path_factory.mktemp('unified')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    env=dict(os.environ,MOBILE_DATA_DIR=str(directory),MOBILE_LOCAL_DEV='true')
    env.pop('MOBILE_PUBLIC_ORIGIN',None)
    env.pop('RENDER_EXTERNAL_URL',None)
    entry=Path(f'test_office_{port}.py')
    entry.write_text("import runpy\nrunpy.run_path('tests/fixtures/unified_office.py',run_name='__main__')\n")
    secrets=directory/'secrets.toml'
    secrets.write_text('SUPABASE_URL="http://127.0.0.1:1"\nSUPABASE_SERVICE_KEY="ci-dummy-key"\n')
    processes=[]
    try:
        for args in ([sys.executable,'-m','streamlit','run',str(entry),'--server.address','127.0.0.1','--server.port','8501','--server.baseUrlPath','office','--server.headless','true','--browser.gatherUsageStats','false','--secrets.files',str(secrets),'--server.corsAllowedOrigins',f'http://127.0.0.1:{port}'],
                     [sys.executable,'-m','uvicorn','tests.fixtures.mobile_server:app','--host','127.0.0.1','--port',str(port)]):
            processes.append(subprocess.Popen(args,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
        for url in (f'http://127.0.0.1:{port}/health','http://127.0.0.1:8501/office/_stcore/health'):
            for _ in range(100):
                assert all(p.poll() is None for p in processes)
                try:
                    with urlopen(url,timeout=1) as response:
                        if response.status==200:break
                except OSError:time.sleep(.1)
            else:raise AssertionError('Unified server failed to start')
        yield f'http://127.0.0.1:{port}'
    finally:
        for p in processes:p.terminate()
        for p in processes:p.wait(timeout=10)
        entry.unlink(missing_ok=True)


@pytest.mark.parametrize('width',[390,1440])
def test_director_opens_real_users_and_ddt_without_second_login(unified_server,width):
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page(viewport={'width':width,'height':900})
        page.goto(unified_server)
        page.get_by_label('Nome utente',exact=True).fill('direzione')
        page.get_by_label('Password',exact=True).fill('test-password')
        page.get_by_role('button',name='Accedi',exact=True).click()
        expect(page.get_by_role('heading',name='Ciao, Direzione.')).to_be_visible()
        page.get_by_role('navigation').get_by_role('link',name='Funzioni').click()
        expect(page.get_by_role('link',name='Utenti e permessi',exact=False)).to_be_visible()
        page.get_by_role('link',name='Utenti e permessi',exact=False).click()
        frame=page.frame_locator('#office-frame')
        expect(frame.get_by_role('heading',name='👥 Utenti & Permessi')).to_be_visible(timeout=30000)
        expect(frame.get_by_text('Accesso scaduto',exact=False)).to_have_count(0)
        expect(frame.get_by_test_id('stException')).to_have_count(0)
        if os.getenv('MOBILE_PREVIEW_DIR'):
            directory=Path(os.environ['MOBILE_PREVIEW_DIR']);directory.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(directory/f'unified-users-{width}.png'),full_page=True)
        page.get_by_role('link',name='Torna alle funzioni').click()
        page.get_by_role('link',name='DDT e carichi',exact=False).click()
        expect(frame.get_by_role('heading',name='DDT',exact=False).first).to_be_visible(timeout=30000)
        expect(frame.get_by_test_id('stException')).to_have_count(0)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        browser.close()
