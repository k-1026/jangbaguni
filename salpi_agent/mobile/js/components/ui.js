// 작은 공통 조각: 카드 · 칩 · 불러오는 중 · 오류 · 빈 화면 · 로그인 안내 · 알림 한 줄
import { esc, html } from "../core/dom.js";

export const card = (title, body, { cls = "", action = "" } = {}) =>
  `<section class="m-card ${cls}">${title ? `<header class="m-card-head"><h2>${esc(title)}</h2>${action}</header>` : ""}${body}</section>`;

// 칩 묶음: [{key, label}] → 누른 칩의 data-chip 으로 고름 (이벤트는 부모 하나에 — 칩마다 달지 않음)
export const chips = (items, active, { small = false, name = "chip" } = {}) =>
  `<div class="m-chips${small ? " small" : ""}" role="tablist">${items.map((c) =>
    `<button type="button" role="tab" class="m-chip${c.key === active ? " on" : ""}" data-${name}="${esc(c.key)}" aria-selected="${c.key === active}">${esc(c.label)}</button>`).join("")}</div>`;

export const loading = (text = "불러오는 중이에요") => `<div class="m-loading"><i class="m-spin"></i><span>${esc(text)}</span></div>`;
export const empty = (text) => `<p class="m-empty">${esc(text)}</p>`;
export const errorBox = (err, retry = true) =>
  `<div class="m-error"><p>${esc(err?.message || "불러오지 못했어요")}</p>${retry ? `<button type="button" class="m-btn" data-retry>다시 하기</button>` : ""}</div>`;

// back = 로그인 뒤 돌아갈 탭 이름 (예: "my" · "store")
export const loginGate = (what, back = "my") => card("", `<div class="m-gate">
  <img src="/static/img/salpi_face.png" alt="" width="64" height="58">
  <p><b>${esc(what)}</b>은(는) 로그인하면 볼 수 있어요</p>
  <a class="m-btn primary" href="#/login/${esc(back)}">로그인</a></div>`);

export function toast(text, ms = 2600) {
  const t = html(`<div class="m-toast" role="status">${esc(text)}</div>`);
  document.body.append(t);
  setTimeout(() => t.remove(), ms);
}
