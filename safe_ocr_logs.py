"""No credentials in evaluation output. Never prints the value being checked."""
import os,re


def redact(text,secret=None):
    secret=secret if secret is not None else os.environ.get('OPENAI_API_KEY','')
    leaked=bool(secret and secret in text)
    if secret:text=text.replace(secret,'[REDACTED]')
    text=re.sub(r'(?i)(authorization[\s\"\x27:=]+bearer\s+)[^\s\"\x27,}]+',r'\1[REDACTED]',text)
    text=re.sub(r'\bsk-[A-Za-z0-9_-]{12,}', '[REDACTED]', text)
    return text,leaked
