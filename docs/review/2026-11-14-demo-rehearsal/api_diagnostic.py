"""One bounded API admission probe; never starts DAW or a music model.

Only allowlisted error codes/types and a numeric Retry-After leave the HTTP
error handler. Raw response bodies, messages, headers, credentials and model
reasoning are neither printed nor saved. This is deliberately not a retry loop.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'scripts'))
from music_agent.config import active_config
from music_agent.providers import create_provider
from music_agent.provider import ProviderError

ALLOWED_ERROR_VALUES = frozenset({
    'insufficient_quota', 'rate_limit_exceeded', 'rate_limit_error',
    'tokens', 'requests', 'server_error', 'invalid_request_error',
    'billing_hard_limit_reached', 'billing_not_active', 'account_deactivated',
    'invalid_api_key', 'authentication_error', 'permission_denied',
    'model_not_found', 'context_length_exceeded',
})


class OneRequestCapture:
    def __init__(self, opener, report):
        self.opener, self.report, self.count = opener, report, 0

    def open(self, request, **kwargs):
        if self.count:
            raise ProviderError('probe_budget', 'Diagnostic permits one HTTP request.')
        self.count += 1
        self.report['http_requests'] = self.count
        try:
            response = self.opener.open(request, **kwargs)
            self.report['http_status'] = int(response.status)
            return response
        except HTTPError as exc:
            self.report['http_status'] = int(exc.code)
            retry = exc.headers.get('Retry-After') if exc.headers else None
            if isinstance(retry, str) and re.fullmatch(r'[0-9]{1,6}(?:\.[0-9]{1,3})?', retry):
                seconds = float(retry)
                if math.isfinite(seconds) and 0 <= seconds <= 86400:
                    self.report['retry_after_seconds'] = seconds
            try:
                raw = exc.read(8193)
                self.report['error_body_within_limit'] = len(raw) <= 8192
                payload = json.loads(raw) if len(raw) <= 8192 else {}
                error = payload.get('error', {}) if isinstance(payload, dict) else {}
                for field in ('code', 'type'):
                    value = error.get(field) if isinstance(error, dict) else None
                    self.report['api_error_'+field] = value if isinstance(value, str) and value in ALLOWED_ERROR_VALUES else 'unrecognized_or_missing'
            except Exception:
                self.report['error_body_parse_failed'] = True
            # The production adapter closes/discards the exception without
            # printing body/message/headers. Preserve its normal error mapping.
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    output = args.out.resolve()
    if output.drive.upper() != 'E:' or output.exists():
        raise ValueError('Choose a new diagnostic JSON file on E:.')
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = {'started_at': datetime.now(timezone.utc).isoformat(),
              'purpose': 'One small API admission diagnostic after HTTP 429',
              'request_limit': 1, 'http_requests': 0, 'max_output_tokens': 64,
              'tools_enabled': False, 'daw_started': False, 'music_tasks': 0,
              'settings_changed': False, 'raw_response_saved': False,
              'original_large_request_diagnosed': False}
    try:
        settings = active_config()
        kwargs = {'reasoning_effort': 'low'} if settings['provider'] == 'openai' else {}
        provider = create_provider(settings['provider'], settings['model'], settings['base_url'], **kwargs)
        report.update(provider=settings['provider'], model=provider.model,
                      probe_reasoning_effort=kwargs.get('reasoning_effort'),
                      network_mode=provider.network_mode)
        capture = OneRequestCapture(provider._opener, report)
        provider._opener = capture
        # These constants affect this probe process only; user settings remain.
        with patch('music_agent.openai_provider.MAX_COMPLETION_TOKENS', 64), patch('music_agent.provider.MAX_COMPLETION_TOKENS', 64):
            provider.complete([{'role': 'user', 'content': 'Reply with exactly OK.'}], tools=None)
        report['adapter_completed'] = True
    except ProviderError as exc:
        report['adapter_completed'] = False
        report['adapter_error_code'] = exc.code
        report['adapter_http_status'] = exc.status
    except Exception as exc:
        report['adapter_completed'] = False
        report['exception_type'] = type(exc).__name__
    finally:
        status = report.get('http_status')
        codes = {report.get('api_error_code'), report.get('api_error_type')}
        report['classification'] = (
            'insufficient_quota' if codes & {'insufficient_quota', 'billing_hard_limit_reached', 'billing_not_active'}
            else 'rate_limit' if codes & {'rate_limit_exceeded', 'rate_limit_error', 'tokens', 'requests'}
            else 'small_request_admitted' if status == 200
            else 'http_429_undifferentiated' if status == 429
            else 'other_or_no_http_response')
        report['elapsed_seconds'] = round(time.monotonic()-started, 3)
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        with output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps(report, ensure_ascii=False), flush=True)
        print(str(output), flush=True)


if __name__ == '__main__':
    main()
