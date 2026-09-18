"""Real subprocess controls, with no model, network, or business-data fixtures."""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pi_terms_process import LogLimitError, run_bounded

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='Pi POSIX execution controls')


def execute(tmp_path, script, *, limit=128, timeout=5, payload=b'input'):
    with (tmp_path/'events').open('wb') as out, (tmp_path/'errors').open('wb') as err:
        return run_bounded([sys.executable, '-c', script], input=payload, stdout=out,
                           stderr=err, env=os.environ.copy(), cwd=tmp_path,
                           timeout=timeout, limit=limit)


def test_runtime_files_can_exceed_log_bound_while_streams_are_exact(tmp_path):
    result = execute(tmp_path, "import sys;from pathlib import Path;"
                     "Path('runtime').write_bytes(b'x'*4096);"
                     "sys.stdout.buffer.write(sys.stdin.buffer.read());"
                     "sys.stderr.buffer.write(b'error\\r\\n')")
    assert result.returncode == 0
    assert (tmp_path/'runtime').stat().st_size == 4096
    assert (tmp_path/'events').read_bytes() == b'input'
    assert (tmp_path/'errors').read_bytes() == b'error\r\n'


@pytest.mark.parametrize('fd', [1, 2])
def test_flood_is_capped_and_process_stopped(tmp_path, fd):
    started = time.monotonic()
    with pytest.raises(LogLimitError):
        execute(tmp_path, f"import os,time;os.write({fd},b'x'*(16*1024*1024));time.sleep(30)")
    assert time.monotonic()-started < 8
    assert (tmp_path/('events' if fd == 1 else 'errors')).stat().st_size == 128


def test_timeout_includes_a_child_that_never_reads_input(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        execute(tmp_path, 'import time;time.sleep(30)', timeout=0.5, payload=b'x'*1000000)


def test_exact_limit_and_nonzero_exit_are_preserved(tmp_path):
    result = execute(tmp_path, "import os,sys;os.write(1,b'x'*128);sys.exit(7)")
    assert result.returncode == 7
    assert (tmp_path/'events').read_bytes() == b'x'*128


@pytest.mark.skipif(os.name != 'posix', reason='Pi descendant cleanup')
def test_timeout_kills_descendant_after_leader_exits(tmp_path):
    script = ("import subprocess,sys;from pathlib import Path;"
              "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
              "Path('pid').write_text(str(p.pid))")
    with pytest.raises(subprocess.TimeoutExpired):
        execute(tmp_path, script, timeout=0.5)
    pid = int((tmp_path/'pid').read_text())
    status = Path(f'/proc/{pid}/stat')
    assert not status.exists() or status.read_text().split()[2] == 'Z'


def test_execute_does_not_export_global_file_limit_to_cli(tmp_path):
    # Isolate this control so a regression cannot impose RLIMIT_FSIZE on pytest.
    script = '''import json,sys
from pathlib import Path
import pi_terms_codex as transport
root=Path(sys.argv[1]);auth=root/'auth';auth.mkdir(mode=0o700)
(auth/'auth.json').write_text(json.dumps({'auth_mode':'chatgpt','tokens':{'access_token':'test-only'}}))
(auth/'auth.json').chmod(0o600)
(root/'input.json').write_text('{}')
transport.MAX_LOG_BYTES=128
transport.prompt=lambda _: 'input'
transport.command=lambda *_: [sys.executable,'-c',"from pathlib import Path;Path('runtime').write_bytes(b'x'*4096);Path('result.json').write_text('{}');print('done')"]
value=transport.execute(Path(sys.executable),auth,root)
assert value['result']=='STAGING_ONLY',value
assert (root/'runtime').stat().st_size==4096
print('TRANSPORT_RUNTIME_FILE_PASS')
'''
    env = os.environ.copy()
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)],
                            env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert 'TRANSPORT_RUNTIME_FILE_PASS' in result.stdout
