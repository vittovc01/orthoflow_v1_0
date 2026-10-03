"""Exercise the real Streamlit DOM, including the parent of the expand button."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

import pytest
from playwright.sync_api import sync_playwright, expect


@pytest.fixture(scope="module")
def server():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with open(os.devnull, "w") as output:
        process = subprocess.Popen([
            sys.executable, "-m", "streamlit", "run",
            "tests/fixtures/navigation_app.py",
            "--server.address=127.0.0.1",
            f"--server.port={port}", "--server.headless=true",
            "--browser.gatherUsageStats=false",
        ], stdout=output, stderr=output)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise AssertionError("Streamlit test server exited")
                try:
                    with urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                raise AssertionError("Streamlit test server did not become ready")
            yield f"http://127.0.0.1:{port}"
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


@pytest.mark.parametrize("width,height", [(390, 844), (1366, 900)])
def test_sidebar_can_open_navigate_and_reopen(server, width, height):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(server)
            expect(page.get_by_role("heading", name="OrthoFlow CI")).to_be_visible(timeout=30000)
            expand = page.get_by_test_id("stExpandSidebarButton")
            expect(expand).to_be_visible()
            expand.click()
            sidebar = page.get_by_test_id("stSidebar")
            expect(sidebar.get_by_role("link", name="Scarico Sala AI")).to_be_visible()
            sidebar.get_by_role("link", name="Scarico Sala AI").click()
            expect(page.get_by_role("heading", name="Scarico Sala AI CI")).to_be_visible()
            # Desktop may keep the sidebar open; narrow screens collapse on navigation.
            if not expand.is_visible():
                sidebar.get_by_test_id("stSidebarCollapseButton").get_by_role("button").click()
            expect(expand).to_be_visible()
            expand.click()
            expect(sidebar.get_by_role("link", name="Home")).to_be_visible()
            sidebar.get_by_role("link", name="Home").click()
            expect(page.get_by_role("heading", name="OrthoFlow CI")).to_be_visible()
        finally:
            browser.close()

