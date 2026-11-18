// 화면 그리기 도구 · 숫자 모양 (모든 View · 컴포넌트가 같이 씀)

export const $ = (sel, root = document) => root.querySelector(sel);
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// 문자열 → DOM 하나 (템플릿 한 번에 만들고 붙임 — 작은 노드를 하나씩 만드는 것보다 가벼움)
export function html(str) {
  const t = document.createElement("template");
  t.innerHTML = str.trim();
  return t.content.firstElementChild;
}

export const won = (v) => (v == null ? "-" : `${Math.round(v).toLocaleString("ko-KR")}원`);
export const num = (v) => (v == null ? "-" : Math.round(v).toLocaleString("ko-KR"));
export const pct = (v, d = 1) => (v == null ? "-" : `${v > 0 ? "+" : ""}${Number(v).toFixed(d)}%`);
export const tone = (v, band = 0) => (v == null ? "" : v > band ? "up" : v < -band ? "down" : "flat");
export const mmdd = (d) => (d ? `${+d.slice(5, 7)}/${+d.slice(8, 10)}` : "");
export const arrow = (v) => (v > 0 ? "▲" : v < 0 ? "▼" : "–");
