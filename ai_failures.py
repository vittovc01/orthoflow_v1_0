"""Safe provider diagnostics and bounded retries for product recognition."""
import math
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


QUOTA_CODES = {'insufficient_quota', 'credit_balance_exhausted',
               'billing_hard_limit_reached', 'billing_not_active',
               'organization_usage_limit_exceeded', 'project_usage_limit_exceeded',
               'usage_limit_reached', 'spend_limit_exceeded'}


def failure_kind(exc):
    body = getattr(exc, 'body', None)
    body = body if isinstance(body, dict) else {}
    body = body.get('error', body)
    body = body if isinstance(body, dict) else {}
    codes = [getattr(exc, 'code', None), getattr(exc, 'type', None),
             body.get('code'), body.get('type')]
    if any(isinstance(c, str) and c in QUOTA_CODES for c in codes):
        return 'quota'
    if getattr(exc, 'status_code', None) == 429:
        return 'rate_limit'
    return None


def retry_delay(exc, attempt):
    headers = getattr(getattr(exc, 'response', None), 'headers', {}) or {}
    try:
        if headers.get('retry-after-ms') is not None:
            delay = float(headers['retry-after-ms']) / 1000
        elif headers.get('retry-after') is not None:
            value = headers['retry-after']
            try:
                delay = float(value)
            except ValueError:
                date = parsedate_to_datetime(value)
                delay = (date - datetime.now(timezone.utc)).total_seconds()
        else:
            delay = 5 * 2**attempt
        return max(0, delay) if math.isfinite(delay) else 61
    except (ValueError, TypeError, OverflowError):
        return 5 * 2**attempt


def provider_notice(kind):
    if kind == 'quota':
        return ('Quota o credito API OpenAI esaurito, oppure limite di spesa raggiunto. '
                'L’amministratore deve verificare fatturazione e limiti del progetto API. '
                'Il documento caricato resta disponibile: non serve rifare la foto.')
    return ('Limite temporaneo del servizio AI (429). Riprova più tardi con il documento '
            'già caricato: non serve rifare la foto. Se persiste, verificare i limiti API del progetto.')


def request_with_backoff(request, sleep=None):
    """No retries for quota; at most two retries and 60 seconds of total wait."""
    sleep = sleep or time.sleep
    waited = 0
    for attempt in range(3):
        try:
            return request()
        except Exception as exc:
            if failure_kind(exc) != 'rate_limit' or attempt == 2:
                raise
            delay = retry_delay(exc, attempt) + random.uniform(0, .5)
            if waited + delay > 60:
                raise
            sleep(delay)
            waited += delay


def probe_service(client, model):
    """Single text-only request. No retries, documents or provider response text."""
    try:
        options = {'reasoning': {'effort': 'low'}} if model in {'gpt-6-astra', 'gpt-5.4'} else {}
        client.responses.create(model=model, store=False, input='Reply OK.',
                                max_output_tokens=128, **options)
        return {'ok': True, 'message': 'Servizio AI raggiungibile (' + model + '). '
                'Prova testuale riuscita; la lettura della foto completa resta da verificare.'}
    except Exception as exc:
        kind = failure_kind(exc)
        message = provider_notice(kind) if kind else 'Servizio AI non disponibile: ' + type(exc).__name__
        return {'ok': False, 'kind': kind, 'message': message}
