import json
import pytest
from scripts.check_deployment import check


class Response:
    status=200
    def __init__(self,data):self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,size):return self.data


@pytest.mark.parametrize('data,success',[(b'{"status":"ok","version":"new-commit"}',True),(b'{"status":"ok","version":"old-commit"}',False),(b'{"status":"error","version":"new-commit"}',False)])
def test_health_requires_expected_commit(monkeypatch,data,success):
    class Opener:
        def open(self,*args,**kwargs):return Response(data)
    monkeypatch.setattr('scripts.check_deployment.build_opener',lambda *args:Opener())
    if success:check('https://app.example','new-commit')
    else:
        with pytest.raises(ValueError):check('https://app.example','new-commit')


@pytest.mark.parametrize('url',['http://app.example','https://user:password@app.example','https://app.example/path','https://app.example?token=value'])
def test_health_rejects_unsafe_origin(url):
    with pytest.raises(ValueError):check(url,'commit')
