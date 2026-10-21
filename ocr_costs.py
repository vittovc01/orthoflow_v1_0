"""Product-reader consumption only: no image, text or credential persistence.

USD estimates at standard rates checked 2026-10-21; not provider invoices.
Output tokens include any provider-billed reasoning tokens, never added twice.
"""
RATES = {'gpt-6.1-sol': (2, .10, 10), 'gpt-5.4-mini': (.75, .075, 4.5), 'gpt-6-astra': (10, 1, 50),
         'gpt-5.4': (2.5, .25, 15)}


def value(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def response_usage(response, model):
    usage = value(response, 'usage')
    if usage is None:
        return None
    incoming, outgoing = value(usage, 'input_tokens'), value(usage, 'output_tokens')
    if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in (incoming, outgoing)):
        return None
    cached = value(value(usage, 'input_tokens_details'), 'cached_tokens', 0) or 0
    reasoning = value(value(usage, 'output_tokens_details'), 'reasoning_tokens', 0) or 0
    cached = min(incoming, cached) if isinstance(cached, int) and not isinstance(cached, bool) and cached >= 0 else 0
    reasoning = min(outgoing, reasoning) if isinstance(reasoning, int) and not isinstance(reasoning, bool) and reasoning >= 0 else 0
    rates = RATES.get(model)
    cost = ((incoming-cached)*rates[0] + cached*rates[1] + outgoing*rates[2])/1e6 if rates else None
    return dict(model=model, input_tokens=incoming, output_tokens=outgoing,
                total_tokens=incoming+outgoing, cached_input_tokens=cached,
                reasoning_tokens=reasoning, estimated_cost_usd=round(cost,8) if cost is not None else None)


def usage_totals(reads):
    return dict(reads=len(reads), input_tokens=sum(r['input_tokens'] for r in reads),
                output_tokens=sum(r['output_tokens'] for r in reads),
                estimated_cost_usd=round(sum(r['estimated_cost_usd'] for r in reads),8)
                if reads and all(r.get('estimated_cost_usd') is not None for r in reads) else None)
