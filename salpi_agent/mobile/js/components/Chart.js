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
  const up = css.getPropertyValue("--up") || "#E2453C", down = css.getPropertyValue("--down") || "#1E9E7A";
  const ink = css.getPropertyValue("--ink") || "#1B201C", muted = css.getPropertyValue("--muted") || "#5B645E";
  // 웹 대시보드와 같은 방향: 세로 막대, 큰 값(오른 것)이 왼쪽 → 작은 값(내린 것)이 오른쪽
  const rows = [...bars].sort((a, b) => b.v - a.v);
  const lo = Math.min(0, ...rows.map((b) => b.v)), hi = Math.max(0, ...rows.map((b) => b.v));
  const span = Math.max(5, hi - lo);
  const left = 34, right = 4, top = 14;
  const LINE = 11, labelH = 8 + LINE * Math.max(2, ...rows.map((b) => [...b.label].length));   // 품목 이름: 글자 하나가 한 줄, 가장 긴 이름만큼 아래 자리   // 왼쪽 % 눈금 · 아래 품목 이름 자리
  const plotH = h - top - labelH, step = (w - left - right) / rows.length;
  const yOf = (v) => top + ((hi - v) / span) * plotH;
  g.font = "10px 'Noto Sans KR', sans-serif"; g.textBaseline = "middle"; g.textAlign = "right";
  g.fillStyle = muted; g.strokeStyle = "#F0EDE6"; g.lineWidth = 1;
  [hi, 0, lo].filter((v, i, a) => a.indexOf(v) === i).forEach((v) => {   // 위 · 0 · 아래 눈금
    const y = yOf(v);
    g.beginPath(); g.moveTo(left, y); g.lineTo(w - right, y); g.stroke();
    g.fillText(`${Math.round(v)}%`, left - 4, y);
  });
  const bw = Math.max(3, Math.min(22, step * 0.62));
  rows.forEach((b, i) => {
    const cx = left + step * (i + 0.5), y0 = yOf(0), y1 = yOf(b.v);
    g.fillStyle = b.v >= 0 ? up : down;
    g.fillRect(cx - bw / 2, Math.min(y0, y1), bw, Math.max(1, Math.abs(y1 - y0)));
    // 품목 이름: 모든 글자를 세로로 (토 / 마 / 토) — 눈러 세우지 않아 읽기 쉽고 이웃 이름끼리 겹치지 않음
    g.fillStyle = ink; g.font = "700 10px 'Noto Sans KR', sans-serif"; g.textAlign = "center"; g.textBaseline = "top";
    [...b.label].forEach((ch, k) => g.fillText(ch, cx, h - labelH + 6 + k * LINE));
  });
}

export function clear(canvas) {
  if (canvas) { canvas.width = 0; canvas.height = 0; }
}
