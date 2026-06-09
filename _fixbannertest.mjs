import fs from "node:fs";
const p = "mobile/__tests__/bannerState.test.ts";
let t = fs.readFileSync(p, "utf8");
const start = t.indexOf("  it('prefers offline copy");
const end = t.indexOf("});", start) + 3;
if (start < 0) throw new Error("start not found");
const replacement = `  it('shows connecting while retrying sample upgrade even if offline flag is still set', () => {
    const view = resolveOfflineBanner('sample', true, true, progress);
    expect(view.mode).toBe('connecting');
    expect(view.showLiveProgress).toBe(true);
  });

  it('shows connecting copy during offline-flagged retry before progress events', () => {
    const view = resolveOfflineBanner('sample', true, true, null);
    expect(view.mode).toBe('connecting');
    expect(view.showLiveProgress).toBe(false);
  });`;
t = t.slice(0, start) + replacement + t.slice(end);
fs.writeFileSync(p, t);
console.log("ok");
