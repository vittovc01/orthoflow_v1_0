"""Scheduled capacity probe. Fail visibly instead of reporting unknown usage as zero."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cloud_capacity import capacity
from supabase import create_client


def main():
    try:
        sb=create_client(os.environ['SUPABASE_URL'],os.environ['SUPABASE_SERVICE_KEY'])
        data=capacity(sb,os.getenv('CLOUD_DATABASE_LIMIT_BYTES') or 500_000_000,
                      os.getenv('CLOUD_FILE_LIMIT_BYTES') or 1_000_000_000)
        for key,limit in data['limits'].items():
            print(f'{key}: {int(data[key])/limit:.1%} of configured quota')
        if data['warning']: raise RuntimeError('Cloud capacity alert: usage >= 80%.')
    except Exception:
        print('Cloud check failed or quota threshold reached; inspect the cloud dashboard.',file=sys.stderr)
        return 1
    return 0

if __name__=='__main__': sys.exit(main())
