// 대형마트 판매가: 검색 · 종류 칩 · 목록 (30개씩 더 보기)
import { disposer } from "../core/observable.js";
import { esc, won, pct, tone, arrow } from "../core/dom.js";
import { chips, loading, errorBox, empty } from "../components/index.js";
import { martVM } from "../viewmodels/MartVM.js";

const row = (x) => `<li class="m-mart">
  <div><b>${esc(x.name)}</b><small>${esc(x.category)}${x.daegu?.price ? ` · 대구 ${won(x.daegu.price)}` : ""}</small></div>
  <div class="m-mart-price"><b>${won(x.low)}</b><small>${esc(x.low_chain || "")} 최저</small>
    ${x.change_pct ? `<span class="${tone(x.change_pct)}">${arrow(x.change_pct)} ${pct(x.change_pct)}</span>` : ""}</div></li>`;

export function mount(outlet) {
  const vm = martVM(), d = disposer();
  outlet.innerHTML = `<div class="m-page mart">
    <h1 class="m-title">대형마트 판매가</h1>
    <label class="m-search"><input type="search" placeholder="재료 이름 (예: 고추장)" value="${esc(vm.query.get())}" aria-label="재료 검색"></label>
    <div id="cats"></div><div id="list">${loading()}</div>
  </div>`;
  const cats = outlet.querySelector("#cats"), list = outlet.querySelector("#list"), input = outlet.querySelector("input");

  function render() {
    const st = vm.data.state.get();
    if (st.error && !st.data) { list.innerHTML = errorBox(st.error); return; }
    if (!st.data) return;
    cats.innerHTML = chips(vm.categories(), vm.category.get(), { small: true, name: "cat" });
    const all = vm.list(), n = vm.shown.get();
    list.innerHTML = all.length
      ? `<p class="m-note">한국소비자원 참가격 ${esc(st.data.date || "")} 조사 · 2주 새 오른 것부터</p>
         <ul class="m-list">${all.slice(0, n).map(row).join("")}</ul>
         ${all.length > n ? `<button type="button" class="m-btn wide" data-more>더 보기 (${all.length - n}개 남음)</button>` : ""}`
      : empty("찾는 재료가 없어요");
  }

  let timer = 0;
  d.on(input, "input", () => { clearTimeout(timer); timer = setTimeout(() => { vm.search(input.value); render(); }, 200); });
  d.add(() => clearTimeout(timer));
  d.on(cats, "click", (e) => { const b = e.target.closest("[data-cat]"); if (b) { vm.pick(b.dataset.cat); render(); } });
  d.on(list, "click", (e) => {
    if (e.target.closest("[data-more]")) { vm.more(); render(); }
    if (e.target.closest("[data-retry]")) vm.load();
  });
  d.add(vm.data.state.subscribe(render, false));
  render();
  vm.load();
  return { dispose: d.run };
}
