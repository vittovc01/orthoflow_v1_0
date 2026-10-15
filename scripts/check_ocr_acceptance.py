#!/usr/bin/env python3
"""Read-only deployment preflight; never toggles the archive flag.

Evidence files must come from the controlled evaluator, not client-uploaded JSON.
This is a release check, not a cryptographic signature or an authorization layer.
"""
import argparse
import json
from datetime import datetime,timezone


def check(summary,pipeline_sha):
    def require(ok,message):
        if not ok:raise ValueError(message)
    s=summary;c=s.get('counts',{});t=s.get('acceptance_thresholds',{})
    require(s.get('status')=='COMPLETED' and s.get('accepted') is True,'OCR acceptance gate blocked')
    require(s.get('mode')=='live' and s.get('silent_errors')==0 and s.get('repeats',0)>=3,'Live evidence missing')
    require(s.get('pipeline_sha256')==pipeline_sha,'Pipeline changed; repeat validation')
    require(t.get('min_labels',0)>=300 and t.get('min_cases',0)>=50,'Reduced thresholds are not production evidence')
    require(s.get('unique_physical_labels',0)>=300 and s.get('cases',0)>=50,'Real sample too small')
    require(s.get('annotations_complete') is True and s.get('truth_manual_review_confirmed') is True,'Ground truth not approved')
    require(not s.get('unlisted_files') and s.get('recall')==1 and c.get('extra',0)==0,'Detection gate failed')
    require(s.get('exact_field_accuracy',0)>=.98 and s.get('field_review_rate',1)<=.15,'Field gate failed')
    require(c.get('quantity_wrong',0)==0 and c.get('quantity_unresolved',0)==0 and c.get('failed_documents',0)==0,'Quantity/documents gate failed')
    require(c.get('condition_expected',0)>0 and c.get('condition_flagged')==c.get('condition_expected'),'Difficult conditions not flagged')
    from evaluate_ocr import REQUIRED_CONDITIONS
    require(REQUIRED_CONDITIONS<=set(s.get('conditions_covered',[])),'Missing edge conditions')
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(s['generated_at'])).total_seconds()
    require(0<=age<=30*86400,'Validation older than 30 days')


if __name__=='__main__':
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    p=argparse.ArgumentParser();p.add_argument('summary');p.add_argument('--pipeline-sha256',required=True)
    a=p.parse_args()
    try:check(json.loads(Path(a.summary).read_text()),a.pipeline_sha256)
    except (ValueError,KeyError,OSError) as exc:print('BLOCKED:',exc);raise SystemExit(2)
    print('PASS OCR evidence only. Staging/security/privacy sign-off still required. Archive flag unchanged.')
