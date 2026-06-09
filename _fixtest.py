from pathlib import Path
import re
p = Path("mobile/__tests__/store.refresh.test.ts")
t = p.read_text(encoding="utf-8")
t = re.sub(r"<<<<<<< HEAD\n(\n  it\('clears refreshing and flags offline on downloadCore failure'.*?)\n=======\n>>>>>>> origin/main\n", r"\1\n", t, flags=re.S)
if "<<<<<<<" in t:
    raise SystemExit("conflict remains")
p.write_text(t, encoding="utf-8")
print("ok")
