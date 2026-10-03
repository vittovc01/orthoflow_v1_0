import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from cloud_capacity import capacity
from scripts.cloud_backup import build_archive,verify_archive,encrypt_file,decrypt_file,database_env


def test_backup_includes_documents_and_exact_original_paths(tmp_path):
    content=b'document with original signature'
    inventory={'buckets':[{'id':'private','public':False}],'files':[{'bucket':'private','path':'../untrusted/name.pdf','metadata':{'size':len(content)}}]}
    source=tmp_path/'source.zip'
    build_archive(source,b'database archive',inventory,lambda b,p:content)
    m=verify_archive(source)
    assert m['files'][0]['path']=='../untrusted/name.pdf'
    assert m['files'][0]['entry']=='objects/000000000'
    encrypted=tmp_path/'archive.enc'; restored=tmp_path/'restored.zip'
    key=b'k'*32
    encrypt_file(source,encrypted,key)
    assert content not in encrypted.read_bytes()
    decrypt_file(encrypted,restored,key)
    assert verify_archive(restored)==m
    assert encrypted.stat().st_mode & 0o777==0o600


def test_wrong_key_and_corruption_do_not_publish_plaintext(tmp_path):
    source=tmp_path/'source.zip'
    build_archive(source,b'dump',{'buckets':[],'files':[]},lambda b,p:b'')
    enc=tmp_path/'archive.enc';encrypt_file(source,enc,b'a'*32)
    for key in [b'b'*32,b'a'*32]:
        if key==b'a'*32:
            data=bytearray(enc.read_bytes());data[-30]^=1;enc.write_bytes(data)
        destination=tmp_path/'unsafe.zip'
        with pytest.raises(Exception): decrypt_file(enc,destination,key)
        assert not destination.exists()


def test_missing_or_changed_document_fails_the_backup(tmp_path):
    with pytest.raises(RuntimeError):
        build_archive(tmp_path/'backup.zip',b'dump',{'buckets':[],'files':[{'bucket':'b','path':'x','metadata':{'size':99}}]},lambda b,p:b'short')


def test_archive_never_overwrites_existing_output(tmp_path):
    source=tmp_path/'source';source.write_bytes(b'anything')
    destination=tmp_path/'existing';destination.write_bytes(b'previous backup')
    with pytest.raises(FileExistsError):encrypt_file(source,destination,b'k'*32)
    assert destination.read_bytes()==b'previous backup'


def test_database_password_never_in_command_arguments():
    env=database_env('postgresql://postgres:secret%40test@db.example:5432/postgres?sslmode=require')
    assert env['PGPASSWORD']=='secret@test' and env['PGSSLMODE']=='require'
    with pytest.raises(ValueError):database_env('postgresql://user:pw@host/db?sslmode=disable')


def test_quota_thresholds_and_failure_not_hidden():
    class SB:
        def rpc(self,*args):
            return SimpleNamespace(execute=lambda:SimpleNamespace(data={'database_bytes':80,'file_bytes':1,'file_count':1}))
    data=capacity(SB(),100,100)
    assert data['warning'] and not data['critical']
    assert capacity(SB(),84,100)['critical']
    with pytest.raises(ValueError):capacity(SB(),0,100)
