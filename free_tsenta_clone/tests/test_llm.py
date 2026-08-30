"""Tests for provider configuration and error reporting.

Every failure mode used to look identical from the dashboard — an empty string
— so these assert that each one names its own cause.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.services import core


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status
        self.text = str(payload)

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError('err', request=None, response=self)


def _with_env(**env):
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update({k: v for k, v in env.items() if v is not None})
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
    return saved


def _restore(saved):
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.update({k: v})


def _run(post_impl, **env):
    saved = _with_env(**env)
    original = httpx.post
    httpx.post = post_impl
    core.LLM_LAST_ERROR = None
    try:
        return core.llm('hi'), core.LLM_LAST_ERROR
    finally:
        httpx.post = original
        _restore(saved)


OR = dict(LLM_PROVIDER='openai_compatible', LLM_BASE_URL='https://openrouter.ai/api/v1',
          LLM_API_KEY='k', LLM_MODEL='some/model:free')


def test_timeout_defaults_to_600_not_180():
    # A free tier generating a full resume routinely exceeds 180s.
    saved = _with_env(LLM_TIMEOUT=None)
    try:
        assert core.llm_timeout() == 600
    finally:
        _restore(saved)


def test_timeout_is_configurable_and_survives_a_bad_value():
    saved = _with_env(LLM_TIMEOUT='45')
    try:
        assert core.llm_timeout() == 45
    finally:
        _restore(saved)
    saved = _with_env(LLM_TIMEOUT='banana')
    try:
        assert core.llm_timeout() == 600
    finally:
        _restore(saved)


def test_missing_api_key_is_named_before_any_request():
    def explode(*a, **k):
        raise AssertionError('should not have made a request')
    out, err = _run(explode, **{**OR, 'LLM_API_KEY': None})
    assert out == '' and 'LLM_API_KEY is not set' in err


def test_successful_call_clears_the_error():
    reply = {'choices': [{'message': {'content': '{"ok": true}'}}]}
    out, err = _run(lambda *a, **k: _Resp(reply), **OR)
    assert out == '{"ok": true}' and err is None


def test_openrouter_error_object_in_a_200_is_reported():
    # A bad slug or exhausted quota comes back as HTTP 200 with an error body,
    # so this is not an exceptional path and must be checked explicitly.
    body = {'error': {'message': 'No endpoints found for some/model:free'}}
    out, err = _run(lambda *a, **k: _Resp(body), **OR)
    assert out == '' and 'No endpoints found' in err


def test_http_error_reports_status_and_body():
    out, err = _run(lambda *a, **k: _Resp('Unauthorized', status=401), **OR)
    assert out == '' and 'HTTP 401' in err


def test_timeout_names_itself_and_suggests_the_fix():
    def timeout(*a, **k):
        raise httpx.TimeoutException('too slow')
    out, err = _run(timeout, **OR)
    assert out == '' and 'Timed out' in err and 'LLM_TIMEOUT' in err


def test_connect_error_is_distinct_from_a_timeout():
    def refused(*a, **k):
        raise httpx.ConnectError('refused')
    out, err = _run(refused, LLM_PROVIDER='ollama')
    assert out == '' and 'Could not reach the model' in err


def test_unknown_provider_is_named():
    out, err = _run(lambda *a, **k: _Resp({}), LLM_PROVIDER='nonsense')
    assert out == '' and 'Unknown LLM_PROVIDER: nonsense' in err


def test_openrouter_requests_carry_identifying_headers():
    seen = {}

    def capture(url, headers=None, json=None, timeout=None):
        seen.update(headers or {})
        return _Resp({'choices': [{'message': {'content': 'x'}}]})
    _run(capture, **OR)
    assert seen.get('X-Title') == 'Open Career Agent'
    assert 'HTTP-Referer' in seen


def test_non_openrouter_endpoint_gets_no_openrouter_headers():
    seen = {}

    def capture(url, headers=None, json=None, timeout=None):
        seen.update(headers or {})
        return _Resp({'choices': [{'message': {'content': 'x'}}]})
    _run(capture, **{**OR, 'LLM_BASE_URL': 'https://api.openai.com/v1'})
    assert 'X-Title' not in seen


def test_config_reports_what_will_be_called():
    saved = _with_env(**OR)
    try:
        cfg = core.llm_config()
        assert cfg['provider'] == 'openai_compatible'
        assert cfg['model'] == 'some/model:free'
        assert cfg['has_key'] is True
    finally:
        _restore(saved)


if __name__ == '__main__':
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                passed += 1
            except Exception as exc:
                failed += 1
                print(f'FAIL {name}: {type(exc).__name__}: {exc}')
    print(f'\n{passed} passed, {failed} failed')
    sys.exit(1 if failed else 0)
