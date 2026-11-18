// 재료 상세 (검색에서 들어옴): 지금 시세 · 최근 그래프 · 다음 7일 예상 · 식봄 바로가기
import { disposer } from "../core/observable.js";
import { loading, empty, errorBox, drawPrice, clear } from "../components/index.js";
import { itemBody } from "../components/ItemCard.js";
import { homeVM } from "../viewmodels/HomeVM.js";

export function mount(outlet, rest = []) {
  const vm = homeVM(), d = disposer();
  let name = "";
  try { name = decodeURIComponent(rest[0] || ""); } catch (e) { name = rest[0] || ""; }
  outlet.innerHTML = `<div class="m-page item">
    <button type="button" class="m-back" data-back aria-label="뒤로">‹ 뒤로</button>
    <section class="m-card" id="body">${loading()}</section>
  </div>`;
  const body = outlet.querySelector("#body");

  function render() {
    const r = vm.find(name);
    clear(body.querySelector("canvas"));
    if (r) {
      body.innerHTML = itemBody(r);
      drawPrice(body.querySelector("canvas"), r.points.slice(-28), r.range);
      return;
    }
    const busy = vm.produce.state.get().loading || vm.extra.state.get().loading;
    const err = vm.produce.state.get().error || vm.extra.state.get().error;
    body.innerHTML = busy ? loading() : err && !vm.all().length ? errorBox(err) : empty(`'${name}' 시세를 찾지 못했어요`);
  }

  d.add(vm.produce.state.subscribe(render, false));
  d.add(vm.extra.state.subscribe(render, false));
  d.on(outlet, "click", (e) => {
    if (e.target.closest("[data-back]")) history.length > 1 ? history.back() : (location.hash = "#/home");
    if (e.target.closest("[data-retry]")) vm.loadAll();
  });
  render();
  vm.loadAll();
  return { dispose() { clear(body.querySelector("canvas")); d.run(); } };
}
