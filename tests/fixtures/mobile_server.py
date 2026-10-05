"""HTTP server with synthetic data for isolated browser CI tests."""
import os
import tempfile
from mobile.app import create_app
from tests.fixtures.mobile_backend import Backend, user
os.environ['MOBILE_LOCAL_DEV']='true'
backend=Backend()
backend.tables['utenti_app'].append(user(4,'direzione',['DIREZIONE']))
app=create_app(lambda:backend,os.path.join(os.getenv('MOBILE_DATA_DIR') or tempfile.mkdtemp(),'sessions.sqlite'))
