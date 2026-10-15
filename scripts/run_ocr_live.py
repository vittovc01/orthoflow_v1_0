#!/usr/bin/env python3
"""Run the actual evaluator live with credential-safe logs; no live call here by default.

Usage: python scripts/run_ocr_live.py --images ... --truth ...
 --annotations ... --privacy-manifest ... --gtin-catalog ... --out ... --repeats 3
API key is read exclusively from the environment, never a command argument.
"""
import os,subprocess,sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from safe_ocr_logs import redact


def main(argv):
    if not os.environ.get('OPENAI_API_KEY'):
        print('NON ESEGUITO: configurare OPENAI_API_KEY nell’ambiente, senza inserirla nel comando.');return 4
    if '--out' not in argv or '--privacy-manifest' not in argv or '--gtin-catalog' not in argv:
        print('NON ESEGUITO: richiesti --out, --privacy-manifest e --gtin-catalog');return 3
    if any(arg.startswith('sk-') or arg==os.environ['OPENAI_API_KEY'] for arg in argv):
        print('NON ESEGUITO: credenziali non ammesse negli argomenti');return 3
    out=Path(argv[argv.index('--out')+1]);out.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();env.pop('OPENAI_LOG',None)
    command=[sys.executable,str(Path(__file__).resolve().parents[1]/'evaluate_ocr.py'),*argv,'--mode','live']
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env,text=True)
    leaked=False
    with (out/'live.log').open('w') as log:
        for line in process.stdout:
            safe,detected=redact(line);leaked|=detected
            log.write(safe);print(safe,end='')
    status=process.wait()
    for path in out.rglob('*'):
        if not path.is_file():continue
        try:raw=path.read_text(encoding='utf-8-sig')
        except (UnicodeError,OSError):continue
        safe,detected=redact(raw)
        if detected:
            leaked=True;path.write_text(safe,encoding='utf-8')
    if leaked:
        summary=out/'summary.json'
        if summary.exists():
            data=json.loads(summary.read_text(encoding='utf-8-sig'));data.update(accepted=False,status='ERROR')
            data.setdefault('gate_reasons',[]).append('Credential log check failed; value redacted')
            summary.write_text(json.dumps(data,indent=2))
        print('BLOCKED: rilevata una credenziale nei dati di log/output, rimossa. Verifica fallita.');return 2
    print('PASS controllo log: chiave assente dai log e dagli output della valutazione.')
    return status


if __name__=='__main__':raise SystemExit(main(sys.argv[1:]))
