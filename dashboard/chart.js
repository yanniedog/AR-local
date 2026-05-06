(function () {
  'use strict';

  function pct(raw) {
    const value = Number(raw);
    if (!Number.isFinite(value)) return '';
    return (value * 100).toFixed(2) + '%';
  }

  function draw(canvas, items, sector) {
    const rect = canvas.getBoundingClientRect();
    const scale = window.devicePixelRatio || 1;
    canvas.width = Math.max(800, Math.floor(rect.width * scale));
    canvas.height = Math.max(360, Math.floor(rect.height * scale));
    const ctx = canvas.getContext('2d');
    ctx.scale(scale, scale);
    const width = canvas.width / scale;
    const height = canvas.height / scale;
    ctx.clearRect(0, 0, width, height);
    const left = 190;
    const top = 24;
    const rowHeight = Math.max(10, Math.min(18, (height - 48) / Math.max(items.length, 1)));
    const max = Math.max(...items.map((item) => item.value), 1);
    const cssVar = window.LocalCdrUtils.cssVar;
    const sectionSoft = cssVar('--ar-section-soft', 'rgba(37,99,235,0.16)');
    const sectionAccent = cssVar('--ar-section-accent', cssVar('--ar-accent', '#2563eb'));
    const textSoft = cssVar('--ar-text-soft', '#c5ced8');
    ctx.font = '12px "Space Grotesk", Segoe UI, sans-serif';
    items.forEach((item, index) => {
      const y = top + index * rowHeight;
      const bar = Math.max(3, (width - left - 92) * item.value / max);
      ctx.fillStyle = sectionSoft;
      ctx.fillRect(left, y, width - left - 92, Math.max(5, rowHeight - 5));
      ctx.fillStyle = sectionAccent;
      ctx.fillRect(left, y, bar, Math.max(5, rowHeight - 5));
      ctx.fillStyle = textSoft;
      ctx.fillText(item.label.slice(0, 24), 14, y + rowHeight - 6);
      ctx.fillText(sector === 'banks' ? pct(item.value) : String(Math.round(item.value)), left + bar + 8, y + rowHeight - 6);
    });
  }

  window.LocalCdrChart = { draw };
})();
