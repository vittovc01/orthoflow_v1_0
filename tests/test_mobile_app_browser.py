import os
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import pytest
from playwright.sync_api import sync_playwright,expect


@pytest.fixture(scope='module')
def mobile_server():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    process=subprocess.Popen([sys.executable,'-m','uvicorn','tests.fixtures.mobile_server:app','--host','127.0.0.1','--port',str(port)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if process.poll() is not None:raise AssertionError('Mobile server exited')
            try:
                with urlopen(f'http://127.0.0.1:{port}/health',timeout=1) as response:
                    if response.status==200:break
            except OSError:time.sleep(.1)
        else:raise AssertionError('Mobile server failed to start')
        yield f'http://127.0.0.1:{port}'
    finally:
        process.terminate();process.wait(timeout=10)


def sign_in(page,url,name):
    page.goto(url)
    page.get_by_label('Nome utente',exact=True).fill(name)
    page.get_by_label('Password',exact=True).fill('test-password')
    page.get_by_role('button',name='Accedi',exact=True).click()
    expect(page.get_by_role('heading',name=f'Ciao, {name.title()}.')).to_be_visible()


def test_courier_navigation_and_role_filter(mobile_server):
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
        sign_in(page,mobile_server,'mario')
        nav=page.get_by_role('navigation',name='Funzioni principali')
        expect(nav).to_be_visible()
        expect(nav.get_by_role('link',name='Scarico')).to_have_count(0)
        nav.get_by_role('link',name='Missioni').click()
        expect(page.get_by_role('heading',name='Le mie missioni')).to_be_visible()
        expect(page.get_by_text('M-102',exact=True)).to_have_count(0)
        page.get_by_role('link',name='CONSEGNA').click()
        expect(page.get_by_role('heading',name='Ospedale Demo')).to_be_visible()
        expect(page.get_by_role('button',name='Acquisisci posizione e timbra')).to_be_visible()
        expect(page.locator('#photos')).to_have_attribute('multiple','')
        nav.get_by_role('link',name='Home').click()
        expect(page.get_by_role('heading',name='Ciao, Mario.')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        browser.close()


def test_agent_edits_delete_and_persistent_smarttrack(mobile_server):
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
        sign_in(page,mobile_server,'agente')
        page.get_by_role('navigation').get_by_role('link',name='Scarico').click()
        expect(page.get_by_role('heading',name='Scarico sala')).to_be_visible()
        page.get_by_label('Struttura',exact=True).select_option('9010013')
        page.get_by_role('button',name='Aggiungi riga manuale').click()
        page.get_by_label('Codice',exact=True).fill('1504-00-126')
        page.get_by_label('Lotto',exact=True).fill('B')
        page.get_by_label('Quantità',exact=True).fill('2')
        page.get_by_label('Conto deposito struttura · Smart Track').check()
        expect(page.get_by_label('Conto deposito struttura · Smart Track')).to_be_checked()
        page.get_by_label('Lotto',exact=True).fill('CORRETTO')
        expect(page.get_by_label('Conto deposito struttura · Smart Track')).to_be_checked()
        page.get_by_role('button',name='Verifica prezzi e riepilogo').click()
        expect(page.get_by_text('MANUALE_MEMORIZZATO · Materiale struttura')).to_be_visible()
        expect(page.get_by_role('button',name='Salva intervento e scarica materiale')).to_be_enabled()
        page.get_by_label('Codice',exact=True).fill('150400126')
        expect(page.get_by_role('button',name='Salva intervento e scarica materiale')).to_be_disabled()
        page.get_by_role('button',name='Elimina riga 1',exact=True).click()
        expect(page.locator('[data-item]')).to_have_count(0)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        browser.close()
