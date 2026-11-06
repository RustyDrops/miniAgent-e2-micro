"""Environment configuration. Model pricing must be supplied explicitly."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os


def _decimal(name: str, default: str | None = None) -> Decimal:
    value = os.environ.get(name, default)
    if value is None or not value.strip():
        raise ValueError(f"{name} must be set to a verified price")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{name} must be a finite, positive number")
    return result


def _int(name: str, default: int, low: int, high: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def _bool(name: str, default: str = '0') -> bool:
    value = os.environ.get(name, default).strip()
    if value not in ('0', '1'):
        raise ValueError(f'{name} must be 0 or 1')
    return value == '1'


@dataclass(frozen=True)
class Config:
    db_path: str
    daily_usd: Decimal
    api_key: str
    base_url: str
    model: str
    input_price: Decimal
    output_price: Decimal
    max_output_tokens: int
    timeout_seconds: int
    max_input_bytes: int
    max_tool_rounds: int
    service_tier: str
    max_retries: int = 1
    retry_wait_seconds: int = 5
    planner_enabled: bool = False
    reasoning_effort: str = ''
    tinyfish_api_key: str = ''

    @classmethod
    def from_env(cls):
        daily = _decimal('MINIAGENT_DAILY_USD', '0.90')
        if daily <= 0 or daily > 1:
            raise ValueError('MINIAGENT_DAILY_USD must be greater than 0 and no more than 1')
        key = os.environ.get('MINIAGENT_API_KEY', '').strip()
        base = os.environ.get('MINIAGENT_BASE_URL', '').strip().rstrip('/')
        model = os.environ.get('MINIAGENT_MODEL', '').strip()
        if not key or not base.startswith('https://') or not model:
            raise ValueError('Set MINIAGENT_API_KEY, MINIAGENT_MODEL and an HTTPS MINIAGENT_BASE_URL')
        return cls(
            db_path=os.environ.get('MINIAGENT_DB', 'miniagent.db'), daily_usd=daily,
            api_key=key, base_url=base, model=model,
            input_price=_decimal('MINIAGENT_INPUT_USD_PER_MILLION'),
            output_price=_decimal('MINIAGENT_OUTPUT_USD_PER_MILLION'),
            max_output_tokens=_int('MINIAGENT_MAX_OUTPUT_TOKENS', 768, 32, 4096),
            timeout_seconds=_int('MINIAGENT_TIMEOUT_SECONDS', 120, 5, 900),
            max_input_bytes=_int('MINIAGENT_MAX_INPUT_BYTES', 24000, 1024, 64000),
            max_tool_rounds=_int('MINIAGENT_MAX_TOOL_ROUNDS', 3, 0, 5),
            service_tier=os.environ.get('MINIAGENT_SERVICE_TIER', '').strip(),
            max_retries=_int('MINIAGENT_MAX_RETRIES', 1, 0, 2),
            retry_wait_seconds=_int('MINIAGENT_RETRY_WAIT_SECONDS', 5, 1, 30),
            planner_enabled=_bool('MINIAGENT_PLANNER'),
            reasoning_effort=os.environ.get('MINIAGENT_REASONING_EFFORT', '').strip(),
            tinyfish_api_key=os.environ.get('TINYFISH_API_KEY', '').strip(),
        )

    def secondary_from_env(self):
        """Optional reviewer model. All secondary settings must be explicit."""
        from dataclasses import replace
        if not os.environ.get('MINIAGENT_SECONDARY_MODEL', '').strip():
            return None
        base = os.environ.get('MINIAGENT_SECONDARY_BASE_URL', '').strip().rstrip('/')
        key = os.environ.get('MINIAGENT_SECONDARY_API_KEY', '').strip()
        if not base.startswith('https://') or not key:
            raise ValueError('Secondary model requires HTTPS MINIAGENT_SECONDARY_BASE_URL and MINIAGENT_SECONDARY_API_KEY')
        tier = os.environ.get('MINIAGENT_SECONDARY_SERVICE_TIER', '').strip()
        timeout = _int('MINIAGENT_SECONDARY_TIMEOUT_SECONDS', 900 if tier == 'flex' else self.timeout_seconds, 5, 900)
        sec_reasoning = os.environ.get('MINIAGENT_SECONDARY_REASONING_EFFORT', '').strip()
        return replace(self, base_url=base, api_key=key,
            model=os.environ['MINIAGENT_SECONDARY_MODEL'].strip(),
            input_price=_decimal('MINIAGENT_SECONDARY_INPUT_USD_PER_MILLION'),
            output_price=_decimal('MINIAGENT_SECONDARY_OUTPUT_USD_PER_MILLION'),
            service_tier=tier, timeout_seconds=timeout,
            reasoning_effort=sec_reasoning)
