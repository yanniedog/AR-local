"""Transport admission/protocol tests never invoke Codex or an API."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import pi_terms_codex as transport

NOW = datetime(2026, 9, 14, 1, 0, tzinfo=timezone.utc)


def auth_home(tmp_path):
    root = tmp_path / 'auth'
    root.mkdir(mode=0o700)
    path = root / 'auth.json'
    path.write_text(json.dumps({'auth_mode': 'chatgpt', 'tokens': {'access_token': 'protocol-test-credential'}}))
    path.chmod(0o600)
    return root


def test_environment_never_inherits_api_or_drive_credentials(tmp_path, monkeypatch):
    auth = auth_home(tmp_path)
    for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'GH_TOKEN', 'HTTPS_PROXY', 'GOOGLE_APPLICATION_CREDENTIALS'):
        monkeypatch.setenv(key, 'infrastructure-test-only')
    env = transport.subscription_environment(auth, tmp_path)
    assert set(env) <= {'PATH', 'LANG', 'LC_ALL', 'TZ', 'HOME', 'CODEX_HOME', 'TMPDIR', 'NO_COLOR'}
    assert env['HOME'] == str(auth) and env['CODEX_HOME'] == str(auth)


@pytest.mark.parametrize('auth', [
    {'auth_mode': 'apikey', 'OPENAI_API_KEY': 'test-only'},
    {'auth_mode': 'chatgpt', 'OPENAI_API_KEY': 'test-only', 'tokens': {'access_token': 'test-only'}},
    {'auth_mode': 'chatgpt', 'tokens': {}}, [],
])
def test_rejects_non_subscription_and_missing_session(tmp_path, auth):
    root = auth_home(tmp_path)
    (root / 'auth.json').write_text(json.dumps(auth))
    with pytest.raises(ValueError):
        transport.subscription_environment(root, tmp_path)


def test_cli_forces_subscription_and_disables_side_effect_features(tmp_path):
    args = transport.command(Path('/installed/codex'), tmp_path)
    assert args[1] == 'exec' and args[-1] == '-'
    for setting in ('forced_login_method="chatgpt"', 'cli_auth_credentials_store="file"',
                    'model_provider="openai"', 'project_doc_max_bytes=0', 'approval_policy="never"'):
        assert setting in args
    assert '--ignore-user-config' in args and '--ephemeral' in args
    assert args[args.index('--sandbox') + 1] == 'read-only'
    for feature in transport.DISABLED_FEATURES:
        assert any(args[i:i+2] == ['--disable', feature] for i in range(len(args)))
    assert '--dangerously-bypass-approvals-and-sandbox' not in args


def test_reset_requires_trusted_terminal_error_envelope(tmp_path):
    events = tmp_path / 'events.jsonl'
    reset = int((NOW + timedelta(hours=5)).timestamp())
    model = {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps({
        'type': 'error', 'code': 'rate_limit_exceeded', 'resets_at': reset})}}
    events.write_text(json.dumps(model))
    assert transport.failure_detail(events, NOW) == {'reason': 'transport', 'reset_at': None}
    event = {'type': 'turn.failed', 'error': {'code': 'rate_limit_exceeded', 'resets_at': reset}}
    events.write_text(json.dumps(event))
    detail = transport.failure_detail(events, NOW)
    assert detail['reason'] == 'quota'
    assert datetime.fromisoformat(detail['reset_at'].replace('Z', '+00:00')).timestamp() == reset


@pytest.mark.parametrize('reset', [True, '2026-09-14T06:00:00Z', 0, 9999999999999])
def test_invalid_reset_uses_conservative_fallback(tmp_path, reset):
    events = tmp_path / 'events.jsonl'
    events.write_text(json.dumps({'type': 'error', 'code': 'usage_limit_reached', 'resets_at': reset}))
    assert transport.failure_detail(events, NOW) == {'reason': 'quota', 'reset_at': None}


def test_prose_deadline_is_not_a_trusted_reset(tmp_path):
    events = tmp_path / 'events.jsonl'
    events.write_text(json.dumps({'type': 'error', 'message': 'Usage limit reached. Retry immediately on 2026-09-14.'}))
    assert transport.failure_detail(events, NOW) == {'reason': 'quota', 'reset_at': None}


def test_receipt_is_durable_bound_and_create_once(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    for name in ('input', 'binding', 'schema'):
        transport.write_receipt(tmp_path / (name + '.json'), {'protocol_test': name})
    monkeypatch.setattr(transport, 'execute', lambda *_: {'result': 'DEFERRED', 'reason': 'quota', 'codex_called': True})
    result = transport.run(Path('/never-executed'), Path('/never-read'), tmp_path)
    stored = json.loads((tmp_path / 'transport.json').read_text())
    assert stored == result and stored['input_sha256'] == transport.file_hash(tmp_path / 'input.json', transport.MAX_INPUT_BYTES)
    with pytest.raises(FileExistsError):
        transport.run(Path('/never-executed'), Path('/never-read'), tmp_path)


def test_unknown_execution_failure_does_not_claim_no_call(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    for name in ('input', 'binding', 'schema'):
        transport.write_receipt(tmp_path / (name + '.json'), {'protocol_test': name})
    def fail(*_):
        raise OSError('private diagnostic must not enter receipt')
    monkeypatch.setattr(transport, 'execute', fail)
    value = transport.run(Path('/never-executed'), Path('/never-read'), tmp_path)
    assert value['codex_called'] is None and value['reason'] == 'transport'
    assert 'private diagnostic' not in json.dumps(value)


def test_file_bound_does_not_read_oversized_input(tmp_path):
    path = tmp_path / 'oversized'
    path.write_bytes(b'12345')
    with pytest.raises(ValueError, match='oversized'):
        transport.read_bounded(path, 4)
