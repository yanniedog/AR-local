"""Real subprocess transport checks; no repository credentials or backup data."""
import json
import subprocess
import sys

import pytest

import pi_drive_backup as backup


@pytest.mark.parametrize('command',[('backup','--json'),('check',),('restore','a'*64,'--verify'),
                                  ('stats','--json'),('cat','config'),('init',)])
def test_every_restic_command_sets_backend_connection_limit(tmp_path,monkeypatch,command):
    config=backup.Config(tmp_path,tmp_path,'unused',tmp_path/'password',tmp_path/'rclone',[])
    actual=subprocess.Popen
    seen={}
    code="import json;print(json.dumps({'message_type':'summary','snapshot_id':'a'*64}))"
    def child(args,**kwargs):
        seen['args']=args
        seen['bandwidth']=kwargs['env']['RCLONE_BWLIMIT']
        seen['transfers']=kwargs['env']['RCLONE_TRANSFERS']
        return actual([sys.executable,'-c',code],**kwargs)
    monkeypatch.setattr(backup.subprocess,'Popen',child)
    monkeypatch.setattr(backup,'guard_window',lambda:None)
    backup.Restic(config).run(*command)
    options=[seen['args'][i+1] for i,value in enumerate(seen['args'][:-1]) if value in ('-o','--option')]
    assert options==['rclone.connections=1']
    assert seen['bandwidth']=='8M' and seen['transfers']=='2'
    assert ('--quiet' in seen['args'])==(command[0]=='restore')
    assert not (tmp_path/'latest-verified.json').exists()


@pytest.mark.parametrize('exit_code',[0,1,11])
def test_restore_quiet_avoids_snapshot_path_dump_and_preserves_exit_semantics(tmp_path,monkeypatch,exit_code):
    config=backup.Config(tmp_path,tmp_path,'unused',tmp_path/'password',tmp_path/'rclone',[])
    actual=subprocess.Popen
    code=("import sys;sys.stdout.buffer.write(b'quiet-control\\n' if '--quiet' in sys.argv "
          "else b'x'*(17*1024*1024));sys.stderr.write('transport failure' if int(sys.argv[1]) else '');"
          "sys.exit(int(sys.argv[1]))")
    monkeypatch.setattr(backup.subprocess,'Popen',lambda args,**kwargs:
                        actual([sys.executable,'-c',code,str(exit_code),*args],**kwargs))
    monkeypatch.setattr(backup,'guard_window',lambda:None)
    if exit_code==0:
        assert backup.Restic(config).run('restore','a'*64,'--verify')=='quiet-control\n'
    else:
        with pytest.raises(backup.Blocked if exit_code==11 else RuntimeError):
            backup.Restic(config).run('restore','a'*64,'--verify')
    receipt=json.loads(next((tmp_path/'diagnostics').glob('*/result.json')).read_text())
    assert receipt['exit_code']==exit_code and receipt['reader_complete'] is True
    assert not (tmp_path/'latest-verified.json').exists()
