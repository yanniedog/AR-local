import pathlib,hashlib,json,subprocess,zipfile,re
root=pathlib.Path.cwd();out=root/'docs/evidence/a4-preparation-closeout-20260908';out.mkdir()
old=pathlib.Path(r'C:\code\AR-local-a4-readiness-0908\docs\evidence\a4-readiness-20260908\watchdog-readback.json').read_bytes()
blob=subprocess.check_output(['git','show','46eb380af4979a7078de3962f695a87d48850061:docs/evidence/a4-readiness-20260908/watchdog-readback.json'])
assert len(old)==1794 and hashlib.sha256(old).hexdigest()=='5ce83fd99d41222c7b60118de6dbf231d315bcf2ed04b29b5cf34ac9ff301b13'
assert len(blob)==1769 and hashlib.sha256(blob).hexdigest()=='75b16ec24182f8feade39ef8ee11b9d5bada90c7bc69eb38a3f925da95ce73e4'
assert old.replace(b'\r\n',b'\n')==blob
files={'original/watchdog-readback.crlf.json':old,'git/watchdog-readback.lf.json':blob}
manifest={'scope':'Preserved original working bytes and exact PR648 Git blob; no live re-probe', 'source_commit':'46eb380af4979a7078de3962f695a87d48850061', 'artifacts':[{'path':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()} for name,raw in files.items()]}
archive=out/'watchdog-byte-variants.zip'
with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
 for name,raw in files.items():z.writestr(name,raw)
 z.writestr('manifest.json',json.dumps(manifest,indent=2)+'\n')
with zipfile.ZipFile(archive) as z:
 for item in manifest['artifacts']:
  raw=z.read(item['path']);assert len(raw)==item['bytes'] and hashlib.sha256(raw).hexdigest()==item['sha256']
packet=next((root/'docs/evidence/backup-lan-recovery-20260908').glob('*.zip'))
with zipfile.ZipFile(packet) as z:inspection=json.loads(z.read('evidence/a4-readonly-metadata.json'))
timers=re.findall(r' ([a-zA-Z0-9_.-]+\.timer)$',inspection['files']['/etc/systemd/system/timers.target.wants']['stdout'],re.M)
units=set(timers)|{name.removesuffix('.timer')+'.service' for name in timers}|{'cron.service','tailscaled.service','rpi-eeprom-update.service','e2scrub_reap.service'}
draft={'schema':'ARL-A4-CLONE-ISOLATION-DRAFT-V1','status':'INCOMPLETE','physical_actions_enabled':False,
 'source_inspection':{'packet_sha256':packet.stem,'entry':'evidence/a4-readonly-metadata.json','at_utc':inspection['at_utc']},
 'media':{'target_device':'/dev/mmcblk0','serial':'0xfa922545','current_root_uuid':'ed6c7f1b-238b-41a1-b4b6-7bcdef3270fe','current_root_partuuid':'1a36a1cc-02','device_bytes':31902400512,'prohibited_writable_devices':['/dev/nvme0n1','/dev/sda'],'original_nvme_root_uuid':'4cbd4874-d326-4496-bee2-7fda775a3c4c'},
 'image_inputs':[
 {'role':'historical_recovery_candidate_may21','bytes':31902400512,'sha256':'d0caeeb3a83a50b79703dd650c8198b9a0afcbbb09c667b24b716fada716be4f','acceptance':'historical base only; not current or boot-proven'},
 {'role':'preserved_original_sd_uncompressed','bytes':31902400512,'sha256':'ce0bcd6f1cb4364df2b97fb6324d0871a053fed6ed7738dcb0a65ef174d371d2','acceptance':'preservation baseline; not interchangeable with recovery candidate'},
 {'role':'preserved_original_sd_compressed','bytes':3682092009,'sha256':'e33d3333697f604f424ff3e5ff4852c0234336ca4b22e67cc4bd4eb49a6f361d','acceptance':'compressed preservation copy only'}],
 'required_mask_units':sorted(units),'observed_enabled_timers':timers,
 'required_credential_isolation':['Tailscale state and identity','publication credentials','production deployment credentials'],
 'permitted_intent':['LAN and authenticated SSH with separate clone host pin','isolated restored current dashboard','independently proved bounded return controls'],
 'approved_path_writes':[],
 'prepared_clone_output':{'bytes':None,'sha256':None,'root_uuid':None,'serial':None,'readback_verified':False},
 'return_controls':{'early_boot_reset':None,'kernel_handover':None,'os_watchdog':None,'network_independent_deadline':None,'actual_negotiated_timeouts':None},
 'open_requirements':['Natural current-runtime backup and consolidated A3 acceptance','Full offline activation/dependency/credential inventory including unmodelled writers','Exact path-by-path write manifest with before/after hashes and rollback sources','Preserved image size/hash validation before use, and prepared output/full-device byte hash verification after approved writes','Continuous early-boot to OS reset/return coverage and separate clone SSH pin','Actual current restored data, SD root and bounded return to unchanged NVMe production']}
assert {'apt-daily.timer','apt-daily-upgrade.timer','apt-daily.service','apt-daily-upgrade.service'}<=units
with (out/'clone-isolation-draft.json').open('x',encoding='utf-8',newline='\n') as stream:json.dump(draft,stream,indent=2);stream.write('\n')
print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'draft_sha256':hashlib.sha256((out/'clone-isolation-draft.json').read_bytes()).hexdigest(),'observed_timers':timers,'required_masks':len(units)},indent=2))