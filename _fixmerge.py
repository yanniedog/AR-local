from pathlib import Path
import re
p = Path("mobile/src/data/store.ts")
t = p.read_text(encoding="utf-8")
t = re.sub(r"<<<<<<< HEAD\n.*?>>>>>>> origin/main\n", "", t, flags=re.S)
t = re.sub(r"<<<<<<< HEAD\n.*?>>>>>>> [^\n]+\n", "", t, flags=re.S)
# ensure up-to-date path sets offline false
old = "set({ manifest: remote, source: 'remote' });"
new = "set({ manifest: remote, source: 'remote', offline: false });"
if old in t:
    t = t.replace(old, new, 1)
if "<<<<<<<" in t:
    raise SystemExit("conflict remains in store")
p.write_text(t, encoding="utf-8")
print("store ok")
