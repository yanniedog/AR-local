from pathlib import Path
import re
p = Path("mobile/src/data/store.ts")
t = p.read_text(encoding="utf-8")
t = re.sub(
    r"<<<<<<< HEAD\n            set\(\{ manifest: remote, source: 'remote' \}\);\n=======\n            set\(\{ manifest: remote, source: 'remote', offline: false \}\);\n>>>>>>> [^\n]+\n",
    "            set({ manifest: remote, source: 'remote', offline: false });\n",
    t,
)
if "<<<<<<<" in t:
    raise SystemExit("conflict remains")
p.write_text(t, encoding="utf-8")
print("ok")
