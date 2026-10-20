from types import SimpleNamespace

import pytest

from ai_failures import failure_kind, provider_notice, request_with_backoff


class ProviderError(Exception):
    status_code = 429

    def __init__(self, code='rate_limit_exceeded', headers=None, error_type=None):
        super().__init__('secret key and private clinical text')
        self.body = {'error': {'code': code, 'type': error_type}}
        self.response = SimpleNamespace(headers=headers or {})


def test_temporary_limit_honors_retry_after_and_recovers():
    calls, delays = [], []
    def request():
        calls.append(1)
        if len(calls) < 3:
            raise ProviderError(headers={'retry-after': '7'})
        return 'ok'
    assert request_with_backoff(request, sleep=delays.append) == 'ok'
    assert all(7 <= d <= 7.5 for d in delays) and len(calls) == 3


@pytest.mark.parametrize('code', ['insufficient_quota', 'credit_balance_exhausted',
                                  'organization_usage_limit_exceeded'])
def test_quota_never_retries_or_discloses_provider_text(code):
    calls, delays = [], []
    def request():
        calls.append(1)
        raise ProviderError(code)
    with pytest.raises(ProviderError) as error:
        request_with_backoff(request, sleep=delays.append)
    assert failure_kind(error.value) == 'quota'
    assert calls == [1] and not delays
    assert 'secret' not in provider_notice('quota')


def test_quota_type_takes_precedence_over_retry_header():
    error = ProviderError('unknown', {'retry-after': '1'}, 'insufficient_quota')
    assert failure_kind(error) == 'quota'


def test_long_retry_after_returns_without_retrying_early():
    calls = []
    def request():
        calls.append(1)
        raise ProviderError(headers={'retry-after': '120'})
    with pytest.raises(ProviderError):
        request_with_backoff(request, sleep=lambda _: pytest.fail('must not sleep'))
    assert len(calls) == 1


def test_exhausted_temporary_limit_has_bounded_attempts():
    calls, delays = [], []
    def request():
        calls.append(1)
        raise ProviderError()
    with pytest.raises(ProviderError):
        request_with_backoff(request, sleep=delays.append)
    assert len(calls) == 3 and 5 <= delays[0] <= 5.5 and 10 <= delays[1] <= 10.5


def test_service_probe_uses_only_fixed_text_and_never_returns_provider_data():
    from ai_failures import probe_service
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return {'private': 'not for output'}
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    result = probe_service(client, 'gpt-6-astra')
    assert result['ok'] and 'private' not in str(result)
    assert calls == [dict(model='gpt-6-astra', store=False, input='Reply OK.',
                           max_output_tokens=128, reasoning={'effort': 'low'})]


def test_service_probe_reports_quota_without_retry_or_disclosure():
    from ai_failures import probe_service
    calls = []
    def create(**kwargs):
        calls.append(1)
        raise ProviderError('insufficient_quota')
    result = probe_service(SimpleNamespace(responses=SimpleNamespace(create=create)), 'gpt-6-astra')
    assert not result['ok'] and result['kind'] == 'quota' and len(calls) == 1
    assert 'secret' not in str(result)
