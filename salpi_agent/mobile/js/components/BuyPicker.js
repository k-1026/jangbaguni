// 사러 가기: 판매처 고르기 창 (아래에서 올라오는 시트). 살피는 팔지 않고 연결만 함
// 재료 페이지에서 열면 그 재료 검색 결과로, 홈에서 열면 각 판매처 첫 화면으로 보냄
// 쿠팡 파트너스 제휴 주소는 서버(price/seller_links.py)가 바꿔 줌 — 키는 .env COUPANG_ACCESS_KEY · COUPANG_SECRET_KEY
import { esc } from "../core/dom.js";
import { get } from "../core/api.js";

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
    <div class="m-pick-grid">${SHOPS.map((s) => `<a href="${esc(urlOf(s, item, fs))}" data-shop="${s.logo}" target="_blank" rel="noopener noreferrer">
      <span class="m-pick-logo"><img src="/static/img/shops/${s.logo}.png" alt="" width="48" height="48" loading="lazy"></span>
      <b>${esc(s.name)}</b></a>`).join("")}</div>
    <p class="m-pick-note m-pick-ad" hidden></p>
    <button type="button" class="m-pick-close">닫기</button></div>`;
  box.addEventListener("click", (e) => { if (e.target === box || e.target.closest(".m-pick-close") || e.target.closest("a")) box.remove(); });
  document.body.appendChild(box);
  applyLinks(box, item);
}

// 판매처 주소는 서버(/api/buy-links)가 정함: 쿠팡 파트너스 키가 있으면 제휴 주소 + 대가성 안내 문구, 없으면 안내를 숨김
async function applyLinks(box, item) {
  try {
    const d = await get(`/api/buy-links?item=${encodeURIComponent(item || "")}`, { ttl: 3600 });
    for (const s of d.shops || []) {
      const a = box.querySelector(`a[data-shop="${s.logo}"]`);
      if (a) { a.href = s.url; if (s.affiliate) a.rel = "noopener noreferrer sponsored"; }
    }
    const note = box.querySelector(".m-pick-ad");
    if (note) { note.textContent = d.ad_note || ""; note.hidden = !d.ad_note; }
  } catch (e) { /* 서버에 못 닿으면 기본 주소 그대로 */ }
}

// 한 번만 연결: [data-buy] 를 누르면 어느 화면에서든 같은 창이 뜸
if (!window.__buyPicker) {
  window.__buyPicker = true;
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-buy]");
    if (b) open(b.dataset.buy, b.dataset.fs);
  });
}
