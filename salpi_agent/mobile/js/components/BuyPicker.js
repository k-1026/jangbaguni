// 사러 가기: 판매처 고르기 창 (아래에서 올라오는 시트). 살피는 팔지 않고 연결만 함
// 재료 검색 없이 항상 각 판매처 첫 화면으로 보냄 (재료 이름은 제목에만 씀)
// 나중에 쿠팡 파트너스를 가입하면 coupang 주소만 제휴 주소로 바꾸면 됨
import { esc } from "../core/dom.js";

// 로고는 각 사이트가 공개한 사이트 아이콘(/static/img/shops/)을 그대로 씀 (모양 · 색 바꾸지 않음)
const SHOPS = [
  { name: "식봄", logo: "foodspring", home: "https://www.foodspring.co.kr" },
  { name: "쿠팡", logo: "coupang", home: "https://www.coupang.com" },
  { name: "농협몰", logo: "nonghyup", home: "https://www.nonghyupmall.com" },
  { name: "이마트몰", logo: "emart", home: "https://emart.ssg.com" },
  { name: "롯데마트 제타", logo: "zetta", home: "https://lottemartzetta.com" },
  { name: "배민상회", logo: "baemin", home: "https://mart.baemin.com" },
];

// 화면에서 쓰는 버튼 모양: data-buy="재료 이름(없으면 빈 값)" data-fs="식봄 검색 주소"
export const buyButton = (item, fs, label, cls = "m-buy") =>
  `<button type="button" class="${cls}" data-buy="${esc(item || "")}" data-fs="${esc(fs || "")}">${label}</button>`;

function open(item) {
  document.querySelector(".m-pick")?.remove();
  const box = document.createElement("div");
  box.className = "m-pick";
  box.innerHTML = `<div class="m-pick-sheet" role="dialog" aria-modal="true" aria-label="구매할 곳 고르기">
    <span class="m-pick-grip" aria-hidden="true"></span>
    <p class="m-pick-eyebrow">사러 가기</p>
    <h3>${item ? `${esc(item)}, 어디서 살까요?` : "어디서 살까요?"}</h3>
    <p class="m-pick-sub">누르면 그 사이트가 열려요</p>
    <div class="m-pick-grid">${SHOPS.map((s) => `<a href="${esc(s.home)}" target="_blank" rel="noopener noreferrer">
      <span class="m-pick-logo"><img src="/static/img/shops/${s.logo}.png" alt="" width="48" height="48" loading="lazy"></span>
      <b>${esc(s.name)}</b></a>`).join("")}</div>
    <p class="m-pick-note">살피는 판매하지 않고 연결만 해요 · 가격은 사이트마다 달라요</p>
    <button type="button" class="m-pick-close">닫기</button></div>`;
  box.addEventListener("click", (e) => { if (e.target === box || e.target.closest(".m-pick-close") || e.target.closest("a")) box.remove(); });
  document.body.appendChild(box);
}

// 한 번만 연결: [data-buy] 를 누르면 어느 화면에서든 같은 창이 뜸
if (!window.__buyPicker) {
  window.__buyPicker = true;
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-buy]");
    if (b) open(b.dataset.buy);
  });
}
