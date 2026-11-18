// 맨 위 헤더: 로고 + 검색창 + 로그인 버튼 (모든 화면에 고정)
// 검색하면 재료 목록이 아래로 펼쳐지고, 누르면 그 재료 상세 화면(#/item/이름)으로 감
import { esc, won } from "../core/dom.js";
import { session } from "../core/api.js";
import { homeVM } from "../viewmodels/HomeVM.js";
import { toast } from "./ui.js";

// 이름에 없지만 사장님이 흔히 쓰는 말 (데스크톱 검색과 같음)
const ALIAS = {
  "한우 등심": "소고기", "한우 양지": "소고기 국거리", "돼지고기 앞다리": "돼지 제육 찌개용", "돼지고기 삼겹살": "돼지 오겹",
  "닭고기": "생닭 닭볶음탕", "계란": "달걀", "새우젓": "젓갈", "멸치액젓": "젓갈 액젓", "명태": "동태 생태", "새우": "흰다리",
};
const squash = (s) => String(s).replace(/\s/g, "").toLowerCase();

export function appHeader(el) {
  const vm = homeVM();
  el.innerHTML = `<div class="m-head-row">
    <a class="m-logo" href="#/home" aria-label="살피 홈"><img src="/static/img/logo.png" alt="살피" height="30"></a>
    <form class="m-hsearch" role="search" autocomplete="off">
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" stroke-width="2.2"/><path d="M15.5 15.5 21 21" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>
      <input type="search" enterkeyhint="search" placeholder="어떤 식재료를 찾으세요?" aria-label="재료 검색">
    </form>
    <a class="m-login" href="#/login"></a>
  </div>
  <div class="m-hresults" hidden></div>`;
  const form = el.querySelector("form"), input = el.querySelector("input"), box = el.querySelector(".m-hresults"), btn = el.querySelector(".m-login");

  function drawLogin(u) {
    btn.href = u ? "#/my" : "#/login";
    btn.classList.toggle("on", !!u);
    btn.textContent = u ? (u.name || "내 정보") : "로그인";
    btn.setAttribute("aria-label", u ? "마이페이지" : "로그인");
  }
  session.subscribe(drawLogin);

  const hits = () => {
    const key = squash(input.value);
    if (!key) return [];
    return vm.all().filter((r) => squash(`${r.name} ${ALIAS[r.name] || ""}`).includes(key));
  };
  const close = () => { box.hidden = true; };
  function open() {
    const key = input.value.trim();
    if (!key) { close(); return; }
    const list = hits();
    box.innerHTML = list.length
      ? list.slice(0, 20).map((r) => `<a class="m-hit" href="#/item/${encodeURIComponent(r.name)}"><span>${esc(r.name)}</span><small>${esc(r.kind)} · ${won(r.price)}/${esc(r.unit)}</small></a>`).join("")
      : `<p class="m-hit-empty">${vm.all().length ? `'${esc(key)}'이(가) 들어간 재료가 없어요` : "시세를 불러오는 중이에요"}</p>`;
    box.hidden = false;
  }

  input.addEventListener("input", open);
  input.addEventListener("focus", () => { vm.loadAll().then(() => { if (document.activeElement === input) open(); }); open(); });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const first = hits()[0];
    if (!first) { open(); if (input.value.trim()) toast("찾는 재료가 없어요"); return; }
    close(); input.blur();
    location.hash = `#/item/${encodeURIComponent(first.name)}`;
  });
  box.addEventListener("click", (e) => { if (e.target.closest(".m-hit")) { close(); input.value = ""; input.blur(); } });
  document.addEventListener("click", (e) => { if (!el.contains(e.target)) close(); });
  addEventListener("hashchange", close);
  vm.loadAll();   // 검색할 재료 목록을 미리 받아 둠
}
