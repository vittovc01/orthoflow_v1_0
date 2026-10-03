"""Confirm a reachable app and, for mobile, the exact deployed commit."""
import argparse
import json
import os
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check(origin, expected_sha, kind='mobile'):
    parsed=urlsplit(origin)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('Use the HTTPS public origin, without paths, credentials or query strings.')
    endpoint=origin.rstrip('/')+('/health' if kind=='mobile' else '/_stcore/health')
    response=build_opener(NoRedirect).open(Request(endpoint,headers={'Accept':'application/json','User-Agent':'OrthoFlow-release-check'}),timeout=15)
    with response:
        if response.status!=200:
            raise ValueError('Endpoint did not return HTTP 200.')
        body=response.read(4096)
    if kind=='mobile':
        data=json.loads(body)
        if data.get('status')!='ok' or data.get('version')!=expected_sha:
            raise ValueError('The running version does not match the expected commit.')
    elif body.strip()!=b'ok':
        raise ValueError('Unexpected Streamlit health response.')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default=os.getenv('DEPLOYMENT_URL',''))
    parser.add_argument('--sha',default=os.getenv('EXPECTED_SHA',''))
    parser.add_argument('--kind',choices=['mobile','streamlit'],default='mobile')
    parser.add_argument('--timeout',type=int,default=600)
    args=parser.parse_args()
    if not args.url or (args.kind=='mobile' and not args.sha):
        parser.error('Public URL and expected mobile SHA are required.')
    deadline=time.monotonic()+max(0,min(args.timeout,600))
    while True:
        try:
            check(args.url,args.sha,args.kind)
            print('Deployment verified: public health endpoint responded'+(' with the expected commit.' if args.kind=='mobile' else '.'))
            return
        except Exception as exc:
            print(f'Deployment not ready: {type(exc).__name__}')
            if time.monotonic()>=deadline:
                raise SystemExit('Deployment verification failed. No release success can be confirmed.')
            time.sleep(min(10,max(0,deadline-time.monotonic())))


if __name__=='__main__':main()
