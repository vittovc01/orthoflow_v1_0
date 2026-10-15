#!/usr/bin/env python3
"""Read-only deployment preflight; never toggles the archive flag."""
import argparse,json
from datetime import datetime,timezone
p=argparse.ArgumentParser();p.add_argument('summary');p.add_argument('--pipeline-sha256',required=True)
a=p.parse_args();s=json.load(open(a.summary))
assert s.get('status')=='COMPLETED' and s.get('accepted') is True,'OCR acceptance gate blocked'
assert s.get('mode')=='live' and s.get('silent_errors')==0 and s.get('repeats',0)>=3,'Live evidence missing'
assert s.get('pipeline_sha256')==a.pipeline_sha256,'Pipeline changed; repeat validation'
assert s.get('acceptance_thresholds',{}).get('min_labels',0)>=300 and s.get('acceptance_thresholds',{}).get('min_cases',0)>=50,'Reduced thresholds are not production evidence'
age=(datetime.now(timezone.utc)-datetime.fromisoformat(s['generated_at'])).total_seconds()
assert 0<=age<=30*86400,'Validation older than 30 days'
print('PASS OCR evidence only. Staging/security/privacy sign-off still required. Archive flag unchanged.')
