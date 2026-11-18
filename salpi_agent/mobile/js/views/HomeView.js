// 홈: 품목 묶음 칩 → 대시보드(넘기는 카드) → 영수증 분석 → 식자재 바로가기 → 요약(눌러서 대시보드 바꾸기)
import { disposer } from "../core/observable.js";
import { esc, pct } from "../core/dom.js";
import { swiper, drawPrice, drawBars, clear, chips, loading, errorBox, empty } from "../components/index.js";
import { itemBody } from "../components/ItemCard.js";
import { homeVM, KINDS, MODES } from "../viewmodels/HomeVM.js";

const overviewSlide = (rows, mode, kind) => `
  <div class="m-dash-head"><span class="m-badge">${esc(MODES[mode])}</span><h3>${esc(kind)} 지난주 대비 변화</h3></div>
  <canvas class="m-chart bars" style="height:220px" aria-label="품목별 1주 변화"></canvas>
  <p class="m-note">왼쪽 오른 것(빨강) · 오른쪽 내린 것(초록) · 옆으로 넘기면 품목별 7일 예측</p>`;

export function mount(outlet) {
  const vm = homeVM(), d = disposer();
  outlet.innerHTML = `<div class="m-page home">
    <div id="kindTabs"></div>
    <section class="m-dash" id="dash">${loading("시세를 불러오는 중이에요")}</section>
    <a class="m-shortcut" href="#/store/receipt">
      <img src="/static/img/receipt_scan.png" alt="" width="44" height="44" loading="lazy">
      <span><b>영수증 분석</b><small>사진 한 장이면 메뉴별 원가율을 계산해요</small></span><i aria-hidden="true">›</i>
    </a>
    <a class="m-shortcut buy" href="https://www.foodspring.co.kr" target="_blank" rel="noopener">
      <span><b>식자재 바로가기</b><small>식봄에서 오늘 필요한 식자재를 사요</small></span><i aria-hidden="true">›</i>
    </a>
    <div id="summary"></div>
  </div>`;
  const dash = outlet.querySelector("#dash"), tabs = outlet.querySelector("#kindTabs"), sum = outlet.querySelector("#summary");
  let sw = null;

  function renderTabs() { tabs.innerHTML = chips(KINDS, vm.kind.get(), { small: true, name: "kind" }); }

  function renderSummary() {
    const st = vm.state().get();
    if (!st.data) { sum.innerHTML = ""; return; }
    const s = vm.summary(vm.baseRows()), m = vm.mode.get();
    const cell = (key, label, n, cls) => `<button type="button" class="m-sum-btn${m === key ? " on" : ""}" data-mode="${key}" aria-pressed="${m === key}">
      <small>${label}</small><b class="${cls}">${n}</b></button>`;
    sum.innerHTML = `<section class="m-card flat"><div class="m-sum">
      ${cell("up", "오른 품목", s.up, "up")}${cell("down", "내린 품목", s.down, "down")}${cell("rising", "다음 주 오를", s.rising, "up")}</div>
      ${s.top ? `<p class="m-note">${m === "all" ? "숫자를 누르면 위 대시보드가 바뀌어요 · " : ""}가장 많이 오른 ${esc(s.top.name)} ${pct(s.top.week)} (1주)</p>` : ""}</section>`;
  }

  function render() {
    renderTabs();
    const st = vm.state().get();
    if (st.error && !st.data) { sw?.dispose(); sw = null; dash.innerHTML = errorBox(st.error); sum.innerHTML = ""; return; }
    if (!st.data) { sw?.dispose(); sw = null; dash.innerHTML = loading("시세를 불러오는 중이에요"); sum.innerHTML = ""; return; }
    const rows = vm.rows(), mode = vm.mode.get(), kind = vm.kind.get();
    sw?.dispose();
    sw = null;
    renderSummary();
    if (!rows.length) { dash.innerHTML = `<div class="m-slide">${empty(`${kind}에는 '${MODES[mode]}'이(가) 없어요`)}</div>`; return; }
    const slides = [{ all: true, rows }, ...rows];
    sw = swiper(dash, slides, {
      label: `${kind} 시세 대시보드`,
      render: (s) => (s.all ? overviewSlide(s.rows, mode, kind) : itemBody(s)),
      onShow: (el, s) => {
        const c = el.querySelector("canvas");
        if (s.all) drawBars(c, s.rows.filter((r) => r.week != null).map((r) => ({ label: r.name, v: r.week })));
        else drawPrice(c, s.points.slice(-21), s.range);
      },
      onHide: (el) => clear(el.querySelector("canvas")),
    });
  }

  d.add(vm.produce.state.subscribe(render, false));
  d.add(vm.extra.state.subscribe(render, false));
  d.add(vm.mode.subscribe(() => { render(); }, false));
  d.on(tabs, "click", (e) => { const b = e.target.closest("[data-kind]"); if (b) { vm.pick(b.dataset.kind); render(); } });
  d.on(sum, "click", (e) => {
    const b = e.target.closest("[data-mode]");
    if (b) { vm.setMode(b.dataset.mode); tabs.scrollIntoView({ block: "start", behavior: "smooth" }); }   // 바뀐 대시보드가 바로 보이게 위로
  });
  d.on(dash, "click", (e) => { if (e.target.closest("[data-retry]")) vm.load(); });
  render();
  vm.load();
  return { dispose() { sw?.dispose(); d.run(); } };
}
