"""Verify every advertised v2 download and its binding to the v1 manifest."""
import gzip,hashlib,json,io
from datetime import datetime,timezone,timedelta
from pathlib import Path
from urllib.request import Request,urlopen
ROOT=Path(__file__).parent
BASE='https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/'
def fetch(url):
    assert url.startswith(BASE)
    with urlopen(Request(url,headers={'Cache-Control':'no-cache'}),timeout=30) as response:
        raw=response.read(128*1024**2+1)
    assert len(raw)<=128*1024**2
    return raw
v1_raw=fetch(BASE+'manifest.json')
v2_raw=fetch(BASE+'manifest-v2.json')
v1,v2=json.loads(v1_raw),json.loads(v2_raw)
assert v1['run_date']==v2['run_date']=='2026-09-10'
assert v2['base']['core_sha']==v1['files']['core']['sha256']
assert v2['base']['details_sha']==v1['files']['details']['sha256']
checks=[]
for name,item in v2['files'].items():
    raw=fetch(item['url'])
    assert len(raw)==item['bytes'] and hashlib.sha256(raw).hexdigest()==item['sha256']
    assert item['encoding']=='gzip'
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
        decoded=compressed.read(256*1024**2+1)
    assert len(decoded)==item['uncompressed_bytes'] and len(decoded)<=256*1024**2
    value=json.loads(decoded)
    if name=='product_history':
        assert value['run_date']==v2['run_date'] and value['core_sha']==v2['base']['core_sha']
        date_binding={'run_date':value['run_date']}
    elif name=='economic_outlook':
        assert value['kind']=='observed_economic_indicators' and value['generated_at']==v2['generated_at']
        generated=datetime.fromisoformat(value['generated_at'].replace('Z','+00:00'))
        assert generated.astimezone(timezone(timedelta(hours=10))).date().isoformat()==v2['run_date']
        date_binding={'generated_at':value['generated_at'],'generated_date_hobart':v2['run_date']}
    else:raise ValueError('Unrecognized v2 date contract: '+name)
    path=ROOT/('v2-'+name+'.json.gz')
    if path.exists():assert path.read_bytes()==raw
    else:
        with path.open('xb') as output:output.write(raw)
    checks.append({'asset':name,'url':item['url'],'bytes':len(raw),'sha256':item['sha256'],
                   'uncompressed_bytes':len(decoded),'date_binding':date_binding,'result':'PASS'})
# Reject a publication revision changing beneath this verification.
assert fetch(BASE+'manifest-v2.json')==v2_raw
with (ROOT/'verified-manifest-v2.json').open('xb') as output:output.write(v2_raw)
report={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'result':'PASS','checks':checks,
        'v2_manifest_sha256':hashlib.sha256(v2_raw).hexdigest(),
        'v1_manifest_sha256':hashlib.sha256(v1_raw).hexdigest(),'base':v2['base'],
        'scope':'Every v2 descriptor downloaded, size/hash/gzip/JSON/date checked; v1 base hashes match. Device state remains unverified.'}
with (ROOT/'v2-publication-check.json').open('x',encoding='utf-8') as output:json.dump(report,output,indent=2)
print(json.dumps(report))
