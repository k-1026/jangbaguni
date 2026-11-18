// 홈: 대시보드(넘기는 카드) → 품목 묶음 탭(작게) → 영수증 분석 바로가기 → 요약
import { disposer } from "../core/observable.js";
import { esc, won, pct, tone, arrow } from "../core/dom.js";
import { swiper, drawPrice, drawBars, clear, chips, loading, errorBox, card } from "../components/index.js";
import { homeVM, KINDS } from "../viewmodels/HomeVM.js";

const overviewSlide = (rows) => `
  <div class="m-dash-head"><span class="m-badge">전체</span><h3>지난주 대비 변화</h3></div>
  <canvas class="m-chart bars" style="height:${Math.min(220, 22 + rows.length * 16)}px" aria-label="품목별 1주 변화"></canvas>
  <p class="m-note">오른 것 빨강 · 내린 것 초록 · 옆으로 넘기면 품목별 7일 예측</p>`;

const itemSlide = (r) => `
  <div class="m-dash-head">
    <h3>${esc(r.name)}</h3>
    <span class="m-week ${tone(r.week)}">${arrow(r.week)} ${pct(r.week)} <small>1주</small></span>
  </div>
  <p class="m-price"><b>${won(r.price)}</b><small>/${esc(r.unit)} · ${esc(r.basis)}</small></p>
  <canvas class="m-chart" aria-label="${esc(r.name)} 최근 시세와 다음 7일 예상"></canvas>
  ${r.exp == null ? `<p class="m-note">예측 자료가 없어요</p>` : `
  <div class="m-fc ${tone(r.exp, 1.9)}">
    <b>${esc(r.direction || "")}</b>
    <span>다음 7일 ${pct(r.exp)}${r.range ? ` · ${won(r.range[0])} ~ ${won(r.range[1])}` : ""}</span>
    <small>${esc(r.tip || "")}${r.reason?.length ? ` · ${esc(r.reason.join(", "))} 영향` : ""}</small>
  </div>`}`;

export function mount(outlet) {
  const vm = homeVM(), d = disposer();
  outlet.innerHTML = `<div class="m-page home">
    <section class="m-dash" id="dash">${loading("시세를 불러오는 중이에요")}</section>
    <div id="kindTabs"></div>
    <a class="m-shortcut" href="#/store/receipt">
      <img src="/static/img/receipt_scan.png" alt="" width="44" height="44" loading="lazy">
      <span><b>영수증 분석</b><small>사진 한 장이면 메뉴별 원가율을 계산해요</small></span><i aria-hidden="true">›</i>
    </a>
    <div id="summary"></div>
  </div>`;
  const dash = outlet.querySelector("#dash"), tabs = outlet.querySelector("#kindTabs"), sum = outlet.querySelector("#summary");
  let sw = null;

  function render() {
    const st = vm.state().get();
    tabs.innerHTML = chips(KINDS, vm.kind.get(), { small: true, name: "kind" });
    if (st.error && !st.data) { sw?.dispose(); sw = null; dash.innerHTML = errorBox(st.error); return; }
    if (!st.data) { sw?.dispose(); sw = null; dash.innerHTML = loading("시세를 불러오는 중이에요"); return; }
    const rows = vm.rows();
    sw?.dispose();
    const slides = [{ all: true, rows }, ...rows];
    sw = swiper(dash, slides, {
      label: `${vm.kind.get()} 시세 대시보드`,
      render: (s) => (s.all ? overviewSlide(s.rows) : itemSlide(s)),
      onShow: (el, s) => {
        const c = el.querySelector("canvas");
        if (s.all) drawBars(c, s.rows.filter((r) => r.week != null).slice(0, 12).map((r) => ({ label: r.name, v: r.week })));
        else drawPrice(c, s.points.slice(-21), s.range);
      },
      onHide: (el) => clear(el.querySelector("canvas")),
    });
    const start = +new URLSearchParams(location.search).get("slide");   // 시연용: /m/?slide=2 → 두 번째 품목 카드부터
    if (start > 0) requestAnimationFrame(() => sw?.go(Math.min(start, slides.length - 1), false));
    const s = vm.summary(rows);
    sum.innerHTML = card("", `<div class="m-sum">
      <div><small>오른 품목</small><b class="up">${s.up}</b></div>
      <div><small>내린 품목</small><b class="down">${s.down}</b></div>
      <div><small>다음 주 오를</small><b class="up">${s.rising}</b></div></div>
      ${s.top ? `<p class="m-note">가장 많이 오른 ${esc(s.top.name)} ${pct(s.top.week)} (1주)</p>` : ""}`, { cls: "flat" });
  }

  d.add(vm.produce.state.subscribe(render, false));
  d.add(vm.extra.state.subscribe(render, false));
  d.on(tabs, "click", (e) => { const b = e.target.closest("[data-kind]"); if (b) { vm.pick(b.dataset.kind); render(); } });
  d.on(dash, "click", (e) => { if (e.target.closest("[data-retry]")) vm.load(); });
  render();
  vm.load();
  return { dispose() { sw?.dispose(); d.run(); } };
}
