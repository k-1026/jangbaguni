// 사러 가기: 판매처 고르기 창 (아래에서 올라오는 시트). 살피는 팔지 않고 연결만 함
// 재료 페이지에서 열면 그 재료 검색 결과로, 홈에서 열면 각 판매처 첫 화면으로 보냄
// 나중에 쿠팡 파트너스를 가입하면 coupang 주소만 제휴 주소로 바꾸면 됨
import { esc } from "../core/dom.js";

// 로고는 각 사이트가 공개한 사이트 아이콘(/static/img/shops/)을 그대로 씀 (모양 · 색 바꾸지 않음)
const SHOPS = [
  { name: "식봄", logo: "foodspring", home: "https://www.foodspring.co.kr", search: (q) => `https://www.foodspring.co.kr/search/all?key=${q}` },
  { name: "쿠팡", logo: "coupang", home: "https://www.coupang.com", search: (q) => `https://www.coupang.com/np/search?q=${q}` },
  { name: "농협몰", logo: "nonghyup", home: "https://www.nonghyupmall.com", search: (q) => `https://www.nonghyupmall.com/BC1F010M/srchTotalList.nh?searchTerm_main=${q}&CHAN_C=1101&chanC=1101` },
  { name: "이마트몰", logo: "emart", home: "https://emart.ssg.com", search: (q) => `https://emart.ssg.com/search.ssg?query=${q}` },
  { name: "롯데마트 제타", logo: "zetta", home: "https://lottemartzetta.com", search: (q) => `https://lottemartzetta.com/products/search?q=${q}` },
  { name: "배민상회", logo: "baemin", home: "https://mart.baemin.com", search: (q) => `https://mart.baemin.com/search/result?w=${q}` },
];
// 식봄은 서버가 준 검색 주소(foodspring_url)가 있으면 그것을 씀
const urlOf = (s, item, fs) => {
  if (!item) return s.home;
  if (s.logo === "foodspring" && fs) return fs;
  return s.search(encodeURIComponent(item));
};

// 화면에서 쓰는 버튼 모양: data-buy="재료 이름(없으면 빈 값)" data-fs="식봄 검색 주소"
export const buyButton = (item, fs, label, cls = "m-buy") =>
  `<button type="button" class="${cls}" data-buy="${esc(item || "")}" data-fs="${esc(fs || "")}">${label}</button>`;

function open(item, fs) {
  document.querySelector(".m-pick")?.remove();
  const box = document.createElement("div");
  box.className = "m-pick";
  box.innerHTML = `<div class="m-pick-sheet" role="dialog" aria-modal="true" aria-label="구매할 곳 고르기">
    <span class="m-pick-grip" aria-hidden="true"></span>
    <h3>${item ? `${esc(item)}, 어디서 살까요?` : "어디서 살까요?"}</h3>
    <div class="m-pick-grid">${SHOPS.map((s) => `<a href="${esc(urlOf(s, item, fs))}" target="_blank" rel="noopener noreferrer">
      <span class="m-pick-logo"><img src="/static/img/shops/${s.logo}.png" alt="" width="48" height="48" loading="lazy"></span>
      <b>${esc(s.name)}</b></a>`).join("")}</div>
    <p class="m-pick-note m-pick-ad">쿠팡 링크는 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.</p>
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
