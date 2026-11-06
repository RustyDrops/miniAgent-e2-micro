"""Minimal OpenAI-compatible Chat Completions client; no SDK required."""
import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import urllib.error
import urllib.request
from .budget import Budget, microdollars

class ProviderError(RuntimeError):
    pass

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward API credentials to a redirect target.
        return None


def retry_delay(headers, default):
    value = headers.get('Retry-After') if headers else None
    if value:
        try:
            if value.strip().isdigit():
                delay = int(value.strip())
            else:
                moment = parsedate_to_datetime(value)
                if moment.tzinfo is None:
                    moment = moment.replace(tzinfo=timezone.utc)
                delay = max(0, (moment - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            delay = default
    else:
        delay = default
    # A longer provider delay is honored by stopping, not retrying early.
    return None if delay > 30 else max(1, delay)

class ChatProvider:
    def __init__(self, config, budget=None):
        self.config = config
        self.budget = budget or Budget(config.db_path, config.daily_usd)

    def complete(self, messages, tools=None, max_output_tokens=None):
        cfg = self.config
        output_limit = max_output_tokens or cfg.max_output_tokens
        payload = {'model': cfg.model, 'messages': messages, 'max_completion_tokens': output_limit}
        if tools:
            payload['tools'] = tools
        # Luna and other reasoning models require explicit reasoning_effort setting for function calling.
        reasoning = getattr(cfg, 'reasoning_effort', '')
        if not reasoning and any(m in cfg.model for m in ('luna', 'o1', 'o3')):
            reasoning = 'none'
        if reasoning:
            payload['reasoning_effort'] = reasoning
        if cfg.service_tier:
            payload['service_tier'] = cfg.service_tier
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        if len(raw) > cfg.max_input_bytes:
            raise ProviderError('Request is too large; shorten the task or tool output.')
        # UTF-8 bytes plus overhead conservatively bounds text tokens for typical
        # byte-based tokenizers. Pricing and provider limits still need verification.
        input_bound = len(raw) + 512
        estimated = microdollars(input_bound, cfg.input_price) + microdollars(output_limit, cfg.output_price)
        request = urllib.request.Request(cfg.base_url + '/chat/completions', data=raw,
            headers={'Authorization': 'Bearer ' + cfg.api_key, 'Content-Type': 'application/json'}, method='POST')
        for attempt in range(getattr(cfg, 'max_retries', 1) + 1):
            reservation = self.budget.reserve(estimated, model=cfg.model, tier=cfg.service_tier)
            try:
                with urllib.request.build_opener(_NoRedirect()).open(request, timeout=cfg.timeout_seconds) as response:
                    data = response.read(2_000_001)
                if len(data) > 2_000_000:
                    raise ProviderError('Provider response exceeded size limit')
                result = json.loads(data)
                break
            except urllib.error.HTTPError as exc:
                # Do not print response body: providers may echo sensitive request data.
                code = exc.code
                delay = retry_delay(exc.headers, min(30, getattr(cfg, 'retry_wait_seconds', 5) * (2 ** attempt)))
                exc.close()
                if code == 429 and cfg.service_tier == 'flex' and attempt < getattr(cfg, 'max_retries', 1) and delay is not None:
                    time.sleep(delay)
                    continue
                raise ProviderError(f'Model provider returned HTTP {code}; reservation retained.') from exc
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                raise ProviderError('Model request failed or returned invalid JSON; reservation retained.') from exc
        if cfg.service_tier == 'flex' and result.get('service_tier') != 'flex':
            raise ProviderError('Provider did not confirm Flex; reservation retained and task stopped. Check provider billing.')
        usage = result.get('usage')
        if isinstance(usage, dict):
            input_tokens = usage.get('prompt_tokens')
            output_tokens = usage.get('completion_tokens')
            if type(input_tokens) is int and type(output_tokens) is int and input_tokens >= 0 and output_tokens >= 0:
                actual = microdollars(input_tokens, cfg.input_price) + microdollars(output_tokens, cfg.output_price)
                details = usage.get('prompt_tokens_details')
                cached = details.get('cached_tokens') if isinstance(details, dict) else None
                if type(cached) is not int or not 0 <= cached <= input_tokens:
                    cached = None
                self.budget.settle(reservation, actual, input_tokens=input_tokens, output_tokens=output_tokens, cached_tokens=cached)
        try:
            message = result['choices'][0]['message']
            if not isinstance(message, dict):
                raise ValueError('Invalid message')
            return message
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError('Provider response did not contain a chat message.') from exc
