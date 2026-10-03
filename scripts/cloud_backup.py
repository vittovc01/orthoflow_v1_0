"""Application backup: public schema + all Storage objects, encrypted off-site.
No passwords, customer data or paths are written to logs. Never restores production.
Use pg_dump >= the server major version. The archive is independently verifiable.
"""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlsplit, unquote, parse_qs
import zipfile
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b'ORTHOFLOW-BACKUP-1\n'
CHUNK = 1024 * 1024
INVENTORY = """SELECT jsonb_build_object('buckets',coalesce((SELECT jsonb_agg(to_jsonb(b) ORDER BY id) FROM storage.buckets b),'[]'::jsonb),
'files',coalesce((SELECT jsonb_agg(jsonb_build_object('bucket',bucket_id,'path',name,'metadata',metadata,'updated_at',updated_at) ORDER BY bucket_id,name) FROM storage.objects),'[]'::jsonb));"""


def backup_key():
    key=base64.b64decode(os.environ['BACKUP_ENCRYPTION_KEY'],validate=True)
    if len(key)!=32: raise ValueError('Backup key must contain 32 random bytes.')
    return key


def database_env(url):
    u=urlsplit(url)
    if u.scheme not in ('postgres','postgresql') or not u.hostname or not u.username:
        raise ValueError('Invalid database connection.')
    query=parse_qs(u.query)
    ssl=query.get('sslmode',['require'])[0]
    if ssl not in ('require','verify-ca','verify-full'):
        raise ValueError('Encrypted database connection is required.')
    # Credentials via process environment, never argv/logs. Ignore unknown URI options.
    return {**os.environ,'PGHOST':u.hostname,'PGPORT':str(u.port or 5432),
        'PGUSER':unquote(u.username),'PGPASSWORD':unquote(u.password or ''),
        'PGDATABASE':unquote(u.path.lstrip('/') or 'postgres'),'PGSSLMODE':ssl,'PGCONNECT_TIMEOUT':'20'}


def command(args, env, timeout=900):
    r=subprocess.run(args,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    if r.returncode: raise RuntimeError('Database export failed; no backup published.')
    return r.stdout


def digest(data): return hashlib.sha256(data).hexdigest()


def build_archive(destination, database_dump, inventory, download):
    """No source paths become local paths or ZIP entry names."""
    records=[]
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        z.writestr('database.dump',database_dump)
        for index,item in enumerate(inventory['files']):
            content=download(item['bucket'],item['path'])
            size=item.get('metadata',{}).get('size')
            if size is not None and len(content)!=int(size):
                raise RuntimeError('Storage object changed during backup.')
            entry=f'objects/{index:09d}'
            z.writestr(entry,content)
            records.append({**item,'entry':entry,'size':len(content),'sha256':digest(content)})
        manifest={'format':1,'created_at':datetime.now(timezone.utc).isoformat(),
            'scope':'public schema and storage files; provider configuration and auth schema excluded',
            'database_sha256':digest(database_dump),'buckets':inventory['buckets'],'files':records}
        z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
    return manifest


def verify_archive(path):
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None: raise ValueError('Archive integrity failure.')
        m=json.loads(z.read('manifest.json'))
        if digest(z.read('database.dump'))!=m['database_sha256']: raise ValueError('Database hash mismatch.')
        for f in m['files']:
            if not f['entry'].startswith('objects/') or '..' in f['entry'].split('/'):
                raise ValueError('Unsafe archive entry.')
            content=z.read(f['entry'])
            if len(content)!=f['size'] or digest(content)!=f['sha256']:
                raise ValueError('Document hash mismatch.')
    return m


def encrypt_file(source,destination,key):
    nonce=os.urandom(12)
    encryptor=Cipher(algorithms.AES(key),modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(MAGIC)
    # Never overwrite an existing archive. Output is owner-readable only.
    fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with open(source,'rb') as src,os.fdopen(fd,'wb') as dst:
        dst.write(MAGIC+nonce)
        while data:=src.read(CHUNK): dst.write(encryptor.update(data))
        dst.write(encryptor.finalize());dst.write(encryptor.tag)


def decrypt_file(source,destination,key):
    # Do not expose unauthenticated plaintext at the requested destination.
    with open(source,'rb') as src:
        if src.read(len(MAGIC))!=MAGIC: raise ValueError('Unknown backup format.')
        nonce=src.read(12);src.seek(-16,2);tag=src.read(16)
        remaining=src.tell()-16-len(MAGIC)-12
        src.seek(len(MAGIC)+12)
        dec=Cipher(algorithms.AES(key),modes.GCM(nonce,tag)).decryptor()
        dec.authenticate_additional_data(MAGIC)
        with tempfile.TemporaryDirectory() as temp:
            partial=Path(temp)/'verified.zip'
            with partial.open('wb') as dst:
                while remaining:
                    data=src.read(min(CHUNK,remaining))
                    if not data: raise ValueError('Truncated backup.')
                    dst.write(dec.update(data));remaining-=len(data)
                dst.write(dec.finalize())
            verify_archive(partial)
            fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with partial.open('rb') as src,os.fdopen(fd,'wb') as dst:
                while data:=src.read(CHUNK): dst.write(data)


def run_backup(output):
    from supabase import create_client
    key=backup_key()
    env=database_env(os.environ['BACKUP_DATABASE_URL'])
    sb=create_client(os.environ['SUPABASE_URL'],os.environ['SUPABASE_SERVICE_KEY'])
    with tempfile.TemporaryDirectory() as temp:
        inventory=json.loads(command(['psql','-X','-t','-A','-v','ON_ERROR_STOP=1','-c',INVENTORY],env))
        dump=command(['pg_dump','--format=custom','--schema=public','--no-owner','--no-acl'],env)
        archive=Path(temp)/'backup.zip'
        manifest=build_archive(archive,dump,inventory,lambda b,p:sb.storage.from_(b).download(p))
        # A changing inventory requires a retry at a quiet time, never a false success.
        after=json.loads(command(['psql','-X','-t','-A','-v','ON_ERROR_STOP=1','-c',INVENTORY],env))
        if after!=inventory: raise RuntimeError('Archive changed during backup; retry during a quiet period.')
        verify_archive(archive)
        encrypt_file(archive,output,key)
        # Read the actual encrypted result back before publishing it off-site.
        decrypt_file(output,Path(temp)/'roundtrip.zip',key)
        print(f"Verified encrypted backup: {len(manifest['files'])} files.")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True)
    p.add_argument('--decrypt',help='Encrypted archive to verify and decrypt; does not restore any database.')
    args=p.parse_args()
    try:
        if args.decrypt: decrypt_file(args.decrypt,args.output,backup_key());print('Backup decrypted and integrity verified.')
        else: run_backup(args.output)
    except Exception as exc:
        # No raw exception: database responses can include credentials or document names.
        p.exit(1,f'Backup failed ({type(exc).__name__}); no verified result available.\n')

if __name__=='__main__': main()
