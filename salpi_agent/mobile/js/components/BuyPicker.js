// 사러 가기: 판매처 고르기 창 (아래에서 올라오는 시트). 살피는 팔지 않고 연결만 함
// 재료 이름이 있으면 그 재료 검색 결과로, 없으면 판매처 첫 화면으로 보냄
// 나중에 쿠팡 파트너스를 가입하면 coupang 주소만 제휴 주소로 바꾸면 됨
import { esc } from "../core/dom.js";

const SHOPS = [
  { name: "식봄", home: "https://www.foodspring.co.kr", search: null },   // 서버가 준 주소(foodspring_url)를 씀
  { name: "쿠팡", home: "https://www.coupang.com", search: (q) => `https://www.coupang.com/np/search?q=${q}` },
  { name: "마켓컬리", home: "https://www.kurly.com", search: (q) => `https://www.kurly.com/search?sword=${q}` },
  { name: "이마트몰", home: "https://emart.ssg.com", search: (q) => `https://emart.ssg.com/search.ssg?query=${q}` },
];

// 화면에서 쓰는 버튼 모양: data-buy="재료 이름(없으면 빈 값)" data-fs="식봄 검색 주소"
export const buyButton = (item, fs, label, cls = "m-buy") =>
  `<button type="button" class="${cls}" data-buy="${esc(item || "")}" data-fs="${esc(fs || "")}">${label}</button>`;

function open(item, fs) {
  const q = encodeURIComponent(item || "");
  const links = SHOPS.map((s) => ({ name: s.name, url: item ? (s.search ? s.search(q) : fs || s.home) : s.home }));
  document.querySelector(".m-pick")?.remove();
  const box = document.createElement("div");
  box.className = "m-pick";
  box.innerHTML = `<div class="m-pick-sheet" role="dialog" aria-modal="true" aria-label="구매할 곳 고르기">
    <h3>${item ? `${esc(item)} 사러 가기` : "식자재 사러 가기"}</h3>
    <p class="m-note">${item ? "고른 곳의 검색 결과로 이동해요" : "고른 곳으로 이동해요"}</p>
    ${links.map((l) => `<a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${esc(l.name)}<i aria-hidden="true">↗</i></a>`).join("")}
    <button type="button" class="m-pick-close">닫기</button></div>`;
  box.addEventListener("click", (e) => { if (e.target === box || e.target.closest(".m-pick-close") || e.target.closest("a")) box.remove(); });
  document.body.appendChild(box);
}

// 한 번만 연결: [data-buy] 를 누르면 어느 화면에서든 같은 창이 뜸
if (!window.__buyPicker) {
  window.__buyPicker = true;
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-buy]");
    if (b) open(b.dataset.buy, b.dataset.fs);
  });
}
