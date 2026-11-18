// 대형마트 판매가: 검색 · 종류 칩 · 정렬(오른쪽) · 가로 3칸 카드 (30개씩 더 보기) · 누르면 최저가 온라인몰로
import { disposer } from "../core/observable.js";
import { esc, won, pct, tone, arrow } from "../core/dom.js";
import { chips, loading, errorBox, empty } from "../components/index.js";
import { martVM, SORTS } from "../viewmodels/MartVM.js";

// 품목 이름을 두 줄로: '쇠고기 등심' / '(1등급, 100g)'
function name(n) {
  const m = n.match(/^(.+?)\s*(\(.*\))$/);
  return m ? `<span class="m-mc-name">${esc(m[1])}</span><small class="m-mc-spec">${esc(m[2])}</small>` : `<span class="m-mc-name">${esc(n)}</span>`;
}

const cell = (x) => {
  const inner = `<h3 title="${esc(x.name)}">${name(x.name)}</h3>
    <b class="m-mc-price">${won(x.low)}</b>
    ${x.change_pct ? `<span class="m-mc-chg ${tone(x.change_pct)}">${arrow(x.change_pct)}${Math.abs(x.change_pct).toFixed(1)}%</span>` : `<span class="m-mc-chg flat">–</span>`}
    ${x.shop ? `<span class="m-mc-go">최저가 바로가기 ↗</span>` : `<span class="m-mc-go off">${esc(x.low_chain || "")} 최저</span>`}`;
  // 카드를 누르면 최저가 온라인몰(검색 결과)로 — 몰이 없는 회사뿐이면 링크 없이 보여 줌
  return x.shop
    ? `<a class="m-mc" href="${esc(x.shop.url)}" target="_blank" rel="noopener noreferrer" title="${esc(x.shop.mall)}로 가요 · ${esc(x.shop.chain)} 매장가 기준">${inner}</a>`
    : `<div class="m-mc">${inner}</div>`;
};

export function mount(outlet) {
  const vm = martVM(), d = disposer();
  outlet.innerHTML = `<div class="m-page mart">
    <h1 class="m-title">대형마트 판매가</h1>
    <label class="m-search"><input type="search" placeholder="재료 이름 (예: 고추장)" value="${esc(vm.query.get())}" aria-label="재료 검색"></label>
    <div id="cats"></div><div id="sorts"></div><div id="list">${loading()}</div>
  </div>`;
  const cats = outlet.querySelector("#cats"), sorts = outlet.querySelector("#sorts"), list = outlet.querySelector("#list"), input = outlet.querySelector("input");

  function render() {
    const st = vm.data.state.get();
    if (st.error && !st.data) { list.innerHTML = errorBox(st.error); return; }
    if (!st.data) return;
    cats.innerHTML = chips(vm.categories(), vm.category.get(), { small: true, name: "cat" });
    sorts.innerHTML = `<div class="m-sortbar">${chips(SORTS, vm.sort.get(), { small: true, name: "sort" })}</div>`;
    const all = vm.list(), n = vm.shown.get();
    list.innerHTML = all.length
      ? `<p class="m-note">한국소비자원 참가격 ${esc(st.data.date || "")} 조사 · 카드를 누르면 최저가 온라인몰로 가요</p>
         <div class="m-mgrid">${all.slice(0, n).map(cell).join("")}</div>
         ${all.length > n ? `<button type="button" class="m-btn wide" data-more>더 보기 (${all.length - n}개 남음)</button>` : ""}`
      : empty("찾는 재료가 없어요");
  }

  let timer = 0;
  d.on(input, "input", () => { clearTimeout(timer); timer = setTimeout(() => { vm.search(input.value); render(); }, 200); });
  d.add(() => clearTimeout(timer));
  d.on(cats, "click", (e) => { const b = e.target.closest("[data-cat]"); if (b) { vm.pick(b.dataset.cat); render(); } });
  d.on(sorts, "click", (e) => { const b = e.target.closest("[data-sort]"); if (b) { vm.setSort(b.dataset.sort); render(); } });
  d.on(list, "click", (e) => {
    if (e.target.closest("[data-more]")) { vm.more(); render(); }
    if (e.target.closest("[data-retry]")) vm.load();
  });
  d.add(vm.data.state.subscribe(render, false));
  render();
  vm.load();
  return { dispose: d.run };
}
