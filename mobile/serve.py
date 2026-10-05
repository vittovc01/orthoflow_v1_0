"""Supervise both app processes; fail the deployment if either exits."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def main():
    data = Path(os.getenv('MOBILE_DATA_DIR', '/data'))
    data.mkdir(parents=True, exist_ok=True)
    secrets = data / 'office-secrets.toml'
    names = ('SUPABASE_URL', 'SUPABASE_SERVICE_KEY', 'OPENAI_API_KEY', 'ENABLE_AI_OCR')
    with secrets.open('w') as f:
        os.chmod(secrets, 0o600)
        f.write('\n'.join(f'{name} = {json.dumps(os.environ[name])}' for name in names if os.environ.get(name)))
    env = dict(os.environ, ORTHOFLOW_OFFICE_RUNTIME='true')
    origin = os.getenv('MOBILE_PUBLIC_ORIGIN') or os.getenv('RENDER_EXTERNAL_URL', '')
    commands = [
        [sys.executable, '-m', 'streamlit', 'run', 'office_entry.py',
         '--server.address', '127.0.0.1', '--server.port', '8501',
         '--server.baseUrlPath', 'office', '--server.headless', 'true',
         '--server.maxUploadSize', '40', '--server.fileWatcherType', 'none',
         '--browser.gatherUsageStats', 'false', '--secrets.files', str(secrets),
         '--server.corsAllowedOrigins', origin],
        [sys.executable, '-m', 'uvicorn', 'mobile.app:app', '--host', '0.0.0.0',
         '--port', os.getenv('PORT', '8000'), '--workers', '1']
    ]
    children = []
    def stop(*_):
        for child in children:
            if child.poll() is None:
                child.terminate()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        children.extend(subprocess.Popen(command, env=env) for command in commands)
        while all(child.poll() is None for child in children):
            time.sleep(.5)
    finally:
        stop()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
