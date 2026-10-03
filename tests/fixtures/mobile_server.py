"""HTTP server with synthetic data for isolated browser CI tests."""
import os
import tempfile
from mobile.app import create_app
from tests.fixtures.mobile_backend import Backend
os.environ['MOBILE_LOCAL_DEV']='true'
backend=Backend()
app=create_app(lambda:backend,os.path.join(tempfile.mkdtemp(),'sessions.sqlite'))
