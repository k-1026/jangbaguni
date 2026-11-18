// 작은 시세 그래프 (canvas 하나, 라이브러리 없음): 최근 가격 선 + 다음 7일 예상 범위(부채꼴)
// onHide 때 clear() 로 그림 메모리를 비움 (canvas 크기를 0으로)

export function drawPrice(canvas, points, range) {
  if (!canvas || !points?.length) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1);   // 3배 화면도 2배까지만 → 그림 메모리 절반 이하
  const w = canvas.clientWidth || 300, h = canvas.clientHeight || 120;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const g = canvas.getContext("2d");
  g.scale(dpr, dpr);
  const vals = points.map((p) => p[1]).concat(range ? [range[0], range[1]] : []);
  const lo = Math.min(...vals), hi = Math.max(...vals), pad = (hi - lo) * 0.12 || hi * 0.05 || 1;
  const n = points.length + (range ? 3 : 0);
  const X = (i) => 6 + (i / Math.max(1, n - 1)) * (w - 12);
  const Y = (v) => h - 16 - ((v - (lo - pad)) / (hi - lo + 2 * pad)) * (h - 26);
  const css = getComputedStyle(canvas);
  // 예상 범위
  if (range) {
    const last = points.length - 1, x0 = X(last), x1 = X(n - 1);
    g.fillStyle = css.getPropertyValue("--chart-band") || "rgba(232,106,46,.16)";
    g.beginPath(); g.moveTo(x0, Y(points[last][1])); g.lineTo(x1, Y(range[1])); g.lineTo(x1, Y(range[0])); g.closePath(); g.fill();
    g.setLineDash([4, 4]); g.strokeStyle = css.getPropertyValue("--accent") || "#E86A2E"; g.lineWidth = 1.5;
    g.beginPath(); g.moveTo(x0, Y(points[last][1])); g.lineTo(x1, Y((range[0] + range[1]) / 2)); g.stroke(); g.setLineDash([]);
  }
  // 가격 선
  g.strokeStyle = css.getPropertyValue("--line") || "#3B7A0A"; g.lineWidth = 2.2; g.lineJoin = "round";
  g.beginPath(); points.forEach((p, i) => (i ? g.lineTo(X(i), Y(p[1])) : g.moveTo(X(i), Y(p[1])))); g.stroke();
  // 끝점 · 날짜
  const lx = X(points.length - 1), ly = Y(points[points.length - 1][1]);
  g.fillStyle = g.strokeStyle; g.beginPath(); g.arc(lx, ly, 3.5, 0, 7); g.fill();
  g.fillStyle = css.getPropertyValue("--muted") || "#5B645E"; g.font = "11px 'Noto Sans KR', sans-serif";
  g.fillText(points[0][0], 4, h - 2);
  g.textAlign = "right"; g.fillText(range ? "다음 7일" : points[points.length - 1][0], w - 4, h - 2);
}

export function drawBars(canvas, bars) {
  if (!canvas || !bars?.length) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const w = canvas.clientWidth || 300, h = canvas.clientHeight || 160;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const g = canvas.getContext("2d");
  g.scale(dpr, dpr);
  const css = getComputedStyle(canvas);
  const max = Math.max(5, ...bars.map((b) => Math.abs(b.v)));
  const rowH = Math.min(18, (h - 4) / bars.length), mid = w * 0.5;
  g.font = "11px 'Noto Sans KR', sans-serif"; g.textBaseline = "middle";
  bars.forEach((b, i) => {
    const y = 2 + i * rowH, len = (Math.abs(b.v) / max) * (w * 0.32);
    g.fillStyle = b.v >= 0 ? (css.getPropertyValue("--up") || "#D93A30") : (css.getPropertyValue("--down") || "#0F8A6A");
    g.fillRect(b.v >= 0 ? mid : mid - len, y + 3, len, rowH - 6);
    g.fillStyle = css.getPropertyValue("--ink") || "#1B201C";
    g.textAlign = b.v >= 0 ? "right" : "left";
    g.fillText(b.label, b.v >= 0 ? mid - 6 : mid + 6, y + rowH / 2);
    g.textAlign = b.v >= 0 ? "left" : "right";
    g.fillStyle = css.getPropertyValue("--muted") || "#5B645E";
    g.fillText(`${b.v > 0 ? "+" : ""}${b.v.toFixed(1)}%`, b.v >= 0 ? mid + len + 4 : mid - len - 4, y + rowH / 2);
  });
}

export function clear(canvas) {
  if (canvas) { canvas.width = 0; canvas.height = 0; }
}
