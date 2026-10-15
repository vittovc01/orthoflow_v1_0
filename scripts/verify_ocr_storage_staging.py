#!/usr/bin/env python3
"""Synthetic Storage probe on explicitly selected staging. Never uses SUPABASE_URL.
Requires staging service key, anon key and two real user JWTs (A/B) in environment.
Tests every user denied by this server-only architecture, not tenant read policies.
"""
import argparse
import base64
import json
import os
import time
import uuid
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlparse


def run(url,expected_ref):
    if urlparse(url).hostname != expected_ref+'.supabase.co' or urlparse(url).scheme!='https':
        raise ValueError('URL must match the explicitly supplied staging project ref')
    service=os.environ['OCR_STAGING_SERVICE_KEY'];anon=os.environ['OCR_STAGING_ANON_KEY']
    users=[os.environ['OCR_STAGING_USER_A_JWT'],os.environ['OCR_STAGING_USER_B_JWT']]
    def claims(token):return json.loads(base64.urlsafe_b64decode(token.split('.')[1]+'==='))
    if any(claims(t).get('role')!='authenticated' for t in users) or claims(users[0]).get('sub')==claims(users[1]).get('sub'):
        raise ValueError('Supply two distinct authenticated staging users')
    def request(path,key,token=None,method='GET',data=None,mime='application/json'):
        headers={'apikey':key,'Authorization':'Bearer '+(token or key),'Content-Type':mime}
        raw=json.dumps(data).encode() if isinstance(data,(dict,list)) else data
        try:
            with urlopen(Request(url+path,data=raw,headers=headers,method=method),timeout=20) as r:return r.status,r.read()
        except HTTPError as e:return e.code,e.read()
    def denied(response):
        status,body=response
        # An empty SELECT is safe denial under RLS; a populated SELECT is never safe.
        assert status in (400,401,403,404) or (status==200 and body.strip()==b'[]'), 'Access unexpectedly allowed'
    bucket='scarico-ocr-originals';path='staging-probe/'+str(uuid.uuid4())+'.txt'
    status,body=request('/storage/v1/bucket/'+bucket,service)
    assert status==200 and json.loads(body).get('public') is False,'Bucket not private'
    status,_=request('/storage/v1/object/'+bucket+'/'+path,service,method='POST',data=b'SYNTHETIC NON CLINICAL TEST',mime='text/plain')
    assert status in (200,201),'Synthetic upload failed'
    try:
        for token in [anon]+users:
            denied(request('/rest/v1/ocr_review_sessions?select=id&limit=1',anon,token))
            denied(request('/rest/v1/ocr_review_sessions',anon,token,'POST',{'actor':'unauthorized'}))
            denied(request('/storage/v1/object/authenticated/'+bucket+'/'+path,anon,token))
            denied(request('/storage/v1/object/'+bucket+'/'+path+'-unauthorized',anon,token,'POST',b'x','text/plain'))
            denied(request('/storage/v1/object/sign/'+bucket+'/'+path,anon,token,'POST',{'expiresIn':30}))
        # Public endpoint has no bearer access. Never log URLs/tokens or bodies.
        try:
            with urlopen(url+'/storage/v1/object/public/'+bucket+'/'+path,timeout=20):raise AssertionError('Public download allowed')
        except HTTPError as e:assert e.code in (400,401,403,404)
        status,body=request('/storage/v1/object/sign/'+bucket+'/'+path,service,method='POST',data={'expiresIn':5})
        assert status==200,'Signing failed'
        signed=json.loads(body).get('signedURL') or json.loads(body).get('signedUrl')
        assert signed and signed.startswith('/object/sign/'),'Unexpected signed URL'
        target=url+'/storage/v1'+signed
        with urlopen(target,timeout=20) as r:assert r.status==200
        time.sleep(8)
        try:
            with urlopen(target,timeout=20):raise AssertionError('Expired URL accepted')
        except HTTPError as e:assert e.code in (400,401,403,404)
        print('PASS: anonymous and users A/B denied; private bucket; signed URL works and expires')
    finally:
        status,_=request('/storage/v1/object/'+bucket,service,method='DELETE',data={'prefixes':[path]})
        if status!=200:raise RuntimeError('Synthetic object cleanup failed; remove staging-probe object in staging')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--staging-url',required=True);p.add_argument('--staging-ref',required=True)
    a=p.parse_args()
    try:run(a.staging_url.rstrip('/'),a.staging_ref)
    except Exception as e:
        # HTTP bodies and JWTs are deliberately never printed.
        print('FAIL:',type(e).__name__);raise SystemExit(1)
