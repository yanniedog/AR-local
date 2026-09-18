"""Cross-platform refusal must occur before any interpreter process starts."""
import asyncio
import io
from types import SimpleNamespace

import pytest

import pi_terms_codex as transport
import pi_terms_process as process


@pytest.mark.parametrize('platform', ['nt', 'unknown'])
def test_unsupported_platform_never_spawns(monkeypatch, platform):
    monkeypatch.setattr(process, 'os', SimpleNamespace(name=platform))

    async def forbidden(*args, **kwargs):
        pytest.fail('unsupported platform attempted process creation')

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', forbidden)
    with pytest.raises(process.UnsupportedPlatformError):
        process.run_bounded(['never-executed'], input=b'', stdout=io.BytesIO(),
                            stderr=io.BytesIO(), env={}, cwd=None, timeout=1, limit=128)


def test_platform_refusal_has_explicit_no_call_receipt(tmp_path, monkeypatch):
    for name in ('input', 'schema', 'binding'):
        transport.write_receipt(tmp_path / (name + '.json'), {})
    executable = tmp_path / 'unused-executable'
    executable.write_bytes(b'not executable')
    monkeypatch.setattr(transport, 'subscription_environment', lambda *_: {})
    monkeypatch.setattr(transport, 'prompt', lambda *_: 'input')
    monkeypatch.setattr(process, 'os', SimpleNamespace(name='nt'))
    result = transport.run(executable, tmp_path, tmp_path)
    assert result['result'] == 'DEFERRED'
    assert result['reason'] == 'unsupported_platform'
    assert result['codex_called'] is False
    assert (tmp_path / 'events.jsonl').read_bytes() == b''
    assert (tmp_path / 'stderr.log').read_bytes() == b''
