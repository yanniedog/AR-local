"""Fixed, independently reviewed root-readonly environment projection.

The literal has no candidate imports, arbitrary path arguments or write calls.
It emits only the daily unit's staging assignments and protected-file metadata.
"""
import hashlib
import json
import subprocess

ROOT_READER = r'''
import json,os,pathlib,re,stat,subprocess,sys
KEY='AR_LOCAL_RAM_ROOT'
def canonical(name):
 p=pathlib.Path(name)
 if len(name)>1024 or not re.fullmatch(r'/[A-Za-z0-9._/-]+',name) or '..' in p.parts or str(p)!=name or p.resolve()!=p:raise ValueError('path')
 return p
def identity(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def assignments(text):
 if chr(0) in text or any(c.isspace() and c not in ' \t\r\n' for c in text) or '\r' in text.replace('\r\n',''):raise ValueError('separator')
 result=[]
 for line in text.replace('\r\n','\n').split('\n'):
  line=line.strip()
  if not line or line.startswith(('#',';')):continue
  key,sep,value=line.partition('=');key=key.strip();value=value.strip()
  if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',key) or chr(92) in value:raise ValueError('syntax')
  if value[:1] in {'\'', '"'}:
   quote=value[0]
   if len(value)<2 or value[-1]!=quote or quote in value[1:-1]:raise ValueError('quotes')
   value=value[1:-1]
  if key==KEY:
   canonical(value);result.append(value)
 return result
def read_file(name,optional):
 p=canonical(name)
 for parent in (p.parent,*p.parent.parents):
  try:s=parent.lstat()
  except FileNotFoundError:
   if optional:continue
   raise
  if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise ValueError('parent')
 try:before=p.lstat()
 except FileNotFoundError:
  if optional:return {'path':name,'optional':True,'missing':True,'assignments':[]}
  raise
 if not stat.S_ISREG(before.st_mode) or before.st_uid!=0 or before.st_nlink!=1 or before.st_mode&0o022 or before.st_size>1048576:raise ValueError('file')
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 with os.fdopen(fd,'rb') as f:
  if identity(os.fstat(f.fileno()))!=identity(before):raise ValueError('identity')
  raw=f.read(1048577)
  if len(raw)>1048576 or identity(os.fstat(f.fileno()))!=identity(before):raise ValueError('changed')
 if identity(p.lstat())!=identity(before):raise ValueError('path changed')
 return {'path':name,'optional':optional,'identity':identity(before),'assignments':assignments(raw.decode('utf-8'))}
def collect():
 r=subprocess.run(['/usr/bin/systemctl','show','ar-local-daily.service','--property=EnvironmentFiles'],capture_output=True,text=True,check=True,timeout=10)
 if len(r.stdout.encode('utf-8'))>65536:raise ValueError('property bound')
 rows=[]
 for line in r.stdout.splitlines():
  key,sep,text=line.partition('=')
  if key!='EnvironmentFiles' or not sep:raise ValueError('property')
  text=text.strip()
  while text:
   m=re.match(r'(/[^\s\\]+) \(ignore_errors=(yes|no)\)(?:\s+|$)',text)
   if not m:raise ValueError('representation')
   if len(rows)>=32:raise ValueError('file count bound')
   rows.append(read_file(m[1],m[2]=='yes'));text=text[m.end():]
 if not r.stdout.splitlines():raise ValueError('missing property')
 return {'schema':'ar-local-stage-environment-v1','files':rows}
if __name__=='__main__':
 try:print(json.dumps(collect(),sort_keys=True))
 except Exception as error:
  print(json.dumps({'error':type(error).__name__}));sys.exit(1)
'''

# Review this exact literal independently before privileged observation.
ROOT_READER_SHA256 = "a45ad06d421eaa0de3e2fbe2574cc32d47926ae94b98d3f07607665d70a837e1"


def read_files():
    if hashlib.sha256(ROOT_READER.encode()).hexdigest() != ROOT_READER_SHA256:
        raise ValueError("root-readonly observer differs from reviewed literal")
    result = subprocess.run(["sudo", "-n", "/usr/bin/python3", "-I", "-B", "-c", ROOT_READER],
        capture_output=True, text=True, check=True, timeout=25)
    if len(result.stdout) > 65536:
        raise ValueError("root-readonly environment projection exceeds bound")
    value = json.loads(result.stdout)
    if set(value) != {"schema", "files"} or value["schema"] != "ar-local-stage-environment-v1" or not isinstance(value["files"], list):
        raise ValueError("invalid root-readonly environment projection")
    return value["files"]
