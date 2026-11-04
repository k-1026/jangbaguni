// 살피 시세 대시보드 화면 동작
const $ = (s) => document.querySelector(s);
const won = (v) => (v == null ? "-" : `${Math.round(v).toLocaleString("ko-KR")}원`);
const pct = (v) => (v == null ? "-" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`);
const cls = (v, band = 0) => (v == null ? "" : v > band ? "up" : v < -band ? "down" : "");
const mmdd = (d) => `${d.slice(5, 7)}.${d.slice(8, 10)}`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

let overview = [];          // 재료별 시세 · 날짜별 기록 · 예측 (/api/overview 한 번으로 받음)
let shop = {};              // 재료별 식봄 상품
const charts = {};          // 슬라이드별 차트 (보이는 슬라이드만 그림)
const ITEM = new URLSearchParams(location.search).get("item");   // 재료 전용 페이지(/?item=토마토)의 재료 이름
if (ITEM) {
  document.body.classList.add("item-view");
  $("#itemPage").hidden = false;
}

async function getJSON(url) {
  const r = await fetch(url);
  const body = await r.json();
  if (!r.ok) throw new Error(body.detail || "데이터를 불러오지 못했어요");
  return body;
}
const byItem = (name) => overview.find((r) => r.item === name);
const expOf = (r) => r.forecast?.expected_change_pct ?? 0;
const factorName = (name) => name.replace(/\s*\(.*\)/, "");   // 화면에는 괄호 설명 없이 표시
// 예측 한마디: 오를 / 떨어질 / 유지될
function verdict(f) {
  const e = f?.expected_change_pct ?? 0;
  if (e >= 2) return { kind: "up", text: "다음 주 오를 가능성이 있어요" };
  if (e <= -2) return { kind: "down", text: "다음 주 떨어질 가능성이 있어요" };
  return { kind: "flat", text: "다음 주 지금 가격이 유지될 가능성이 커요" };
}

// ---------------------------------------------------------------
// 첫 화면: 요약 · 슬라이드(전체 → 야채별)
// ---------------------------------------------------------------
async function loadOverview(attempt = 1) {
  try {
    overview = (await getJSON("/api/overview")).items;
  } catch (e) {
    if (attempt < 4) { setTimeout(() => loadOverview(attempt + 1), 5000); return; }   // 서버가 막 켜졌을 때는 잠시 뒤 다시
    if (ITEM) { $("#itemHead").innerHTML = `<p class="muted">시세를 불러오지 못했어요. ${esc(e.message)}</p>`; return; }
    $("#slider").innerHTML = `<article class="slide card loading-card"><b>시세를 불러오지 못했어요</b>
      <p class="muted">${esc(e.message)}</p><button class="sort" onclick="location.reload()">다시 불러오기</button></article>`;
    $("#summary").innerHTML = "";
    return;
  }
  const dated = overview.map((r) => r.wholesale_date).filter(Boolean).sort();
  $("#basis").textContent = dated.length ? `대구 북부도매시장 · ${mmdd(dated.at(-1))} 기준` : "";
  if (ITEM) { renderItemPage(); return; }

  const up = overview.filter((r) => (r.wholesale_change_pct ?? 0) >= 3);
  const down = overview.filter((r) => (r.wholesale_change_pct ?? 0) <= -3);
  const rising = overview.filter((r) => expOf(r) >= 2);
  const top = [...overview].sort((a, b) => (b.wholesale_change_pct ?? -999) - (a.wholesale_change_pct ?? -999))[0];
  $("#summary").innerHTML = `
    <div class="chip up"><b>${up.length}개</b><small>지난주보다 오른 야채</small></div>
    <div class="chip down"><b>${down.length}개</b><small>지난주보다 내린 야채</small></div>
    <div class="chip warn"><b>${rising.length}개</b><small>다음 주 오를 가능성</small></div>
    ${top ? `<div class="chip up"><b>${esc(top.item)} ${pct(top.wholesale_change_pct)}</b><small>가장 많이 오른 야채</small></div>` : ""}`;

  renderSlides();
  renderFilter();
  renderProducts();
  onSlideChange();
}

// 슬라이드 순서: 전체 → 오를 가능성 높은 순 → 유지 → 떨어질 가능성
function slideOrder() { return [...overview].sort((a, b) => expOf(b) - expOf(a)); }

function renderSlides() {
  Object.values(charts).forEach((c) => c.destroy());
  Object.keys(charts).forEach((k) => delete charts[k]);
  lastSlide = -1;
  cur = 0;
  $("#slider").innerHTML = `
    <article class="slide card" data-item="" data-title="전체 야채 시세">
      <div class="chart-head">
        <div><h3>전체 야채 시세</h3><p class="price-now muted">지난주보다 얼마나 올랐나 · 내렸나 (도매 kg당)</p></div>
        <div class="legend"><span><i class="lg up"></i>올랐어요</span><span><i class="lg down"></i>내렸어요</span></div>
      </div>
      <div class="chart-box"><canvas></canvas></div>
      <p class="overview-note">막대를 누르거나 옆으로 넘기면 야채별 시세와 다음 주 예측을 볼 수 있어요.
        다음 주 <b class="up">오를 가능성 ${overview.filter((r) => expOf(r) >= 2).length}개</b> ·
        <b>유지 ${overview.filter((r) => Math.abs(expOf(r)) < 2).length}개</b> ·
        <b class="down">떨어질 가능성 ${overview.filter((r) => expOf(r) <= -2).length}개</b></p>
    </article>` + slideOrder().map(itemSlide).join("");
}

// 재료 한 장: 메인 슬라이드와 재료 페이지가 함께 씀
function itemSlide(r, idx) {
  const f = r.forecast || {};
  const v = verdict(f);
  const reasons = [...(f.factors || [])].filter((x) => x.effect_pct !== 0)
    .sort((a, b) => Math.abs(b.effect_pct) - Math.abs(a.effect_pct)).slice(0, 2);
  // 오름: 경광등 살피(2 · 4번째 포즈 번갈아) · 유지: 알람시계 살피(1 · 3번째) · 내림: 쇼핑백 살피(6번째)
  const pose = v.kind === "down" ? "alert_down" : `alert_${v.kind === "up" ? "rise" : "flat"}${(idx % 2) + 1}`;
  const say = { up: "미리 사두는 게 좋을 것 같아요.", flat: "평소대로 구매하셔도 좋아요", down: "급하지 않으면 나중에 사셔도 좋아요" }[v.kind];
  return `
<article class="slide card" data-item="${esc(r.item)}" data-title="${esc(r.item)} 시세">
  <div class="chart-head">
    <div>
      <h3>${esc(r.item)} 시세</h3>
      <p class="price-now"><strong>${won(r.wholesale_kg)}/kg</strong>
        <span class="${cls(r.wholesale_change_pct, 3)}">1주 전보다 ${pct(r.wholesale_change_pct)}</span></p>
    </div>
    <div class="legend">
      <span><i class="lg line"></i>도매 kg당</span><span><i class="lg fc"></i>7일 예측</span>
      <span><i class="lg rain"></i>비</span><span><i class="lg event"></i>행사</span><span><i class="lg hol"></i>공휴일</span>
    </div>
  </div>
  <div class="chart-box"><canvas></canvas></div>
  <div class="fc-strip ${v.kind}">
    <div class="advice"><span class="say">${say}</span><img class="pose" src="/static/img/${pose}.png" alt=""></div>
    <span class="verdict">${v.text}</span>
    <span class="range">예상 ${pct(f.range_pct?.[0])} ~ ${pct(f.range_pct?.[1])}
      (${won(f.expected_kg_price_range?.[0])} ~ ${won(f.expected_kg_price_range?.[1])}/kg · 믿을 만한 정도 ${esc(f.confidence || "-")})</span>
    <ul>${reasons.map((x) => `<li><b>${esc(factorName(x.factor))}</b> ${pct(x.effect_pct)} — ${esc(x.detail)}</li>`).join("")
      || "<li>뚜렷하게 오르거나 내릴 이유가 적어요</li>"}</ul>
  </div>
</article>`;
}

// 슬라이드 넘기기: 화살표 · 8초 자동 · 휴대폰 손가락. 끝에서 처음으로(처음에서 끝으로) 돌아감
const slider = $("#slider");
const slides = () => [...slider.querySelectorAll(".slide")];
const SLIDE_PAD = 32, SLIDE_GAP = 64;   // style.css 의 .slider 여백 · 간격과 같게
function slideIndex() { return Math.round(slider.scrollLeft / (slider.clientWidth - 2 * SLIDE_PAD + SLIDE_GAP)); }
let cur = 0;   // 지금 보고 있는 장 (화살표는 이 값 기준 — 넘어가는 도중의 스크롤 위치로 계산하면 어긋남)
function goSlide(i, behavior = "smooth") {
  const s = slides();
  if (!s.length) return;
  cur = ((i % s.length) + s.length) % s.length;
  slider.scrollTo({ left: s[cur].offsetLeft - s[0].offsetLeft, behavior });
  onSlideChange(cur);
}
let lastSlide = -1;
function onSlideChange(target) {
  const s = slides(), i = target ?? Math.min(slideIndex(), s.length - 1);
  $("#dots").textContent = s.length > 1 ? `${i + 1} / ${s.length}` : "";
  $("#slideTitle").textContent = s[i]?.dataset.title || "야채 시세";
  if (i === lastSlide || !overview.length) return;
  lastSlide = i;
  drawSlideChart(i);
}
$("#prevSlide").onclick = () => { goSlide(cur - 1); restartAuto(); };
$("#nextSlide").onclick = () => { goSlide(cur + 1); restartAuto(); };

// 휴대폰: 손가락으로 옆으로 밀면 넘김 (마우스 끌기는 그래프 보기와 겹쳐서 쓰지 않음)
let touchX = null;
slider.addEventListener("pointerdown", (e) => { if (e.pointerType === "touch") touchX = e.clientX; });
slider.addEventListener("pointerup", (e) => {
  if (touchX == null) return;
  const dx = e.clientX - touchX;
  touchX = null;
  if (Math.abs(dx) > 50) { goSlide(cur + (dx < 0 ? 1 : -1)); restartAuto(); }
});

// 8초마다 자동으로 다음 장. 대시보드에 마우스를 올려 보는 동안 · 다른 탭을 볼 때는 멈춤
const AUTO_MS = 8000;
let autoTimer = null, hovering = false;
function restartAuto() {
  clearInterval(autoTimer);
  autoTimer = setInterval(() => { if (!hovering && !document.hidden && slides().length > 1) goSlide(cur + 1); }, AUTO_MS);
}
$(".hero-board").addEventListener("mouseenter", () => { hovering = true; });
$(".hero-board").addEventListener("mouseleave", () => { hovering = false; });
if (!ITEM) restartAuto();

function drawSlideChart(i) {
  const el = slides()[i];
  if (!el || charts[i]) return;
  const item = el.dataset.item;
  charts[i] = item ? drawItemChart(el.querySelector("canvas"), byItem(item)) : drawOverviewChart(el.querySelector("canvas"));
}

function drawOverviewChart(canvas) {
  const rows = [...overview].filter((r) => r.wholesale_change_pct != null).sort((a, b) => b.wholesale_change_pct - a.wholesale_change_pct);
  return new Chart(canvas.getContext("2d"), {
    type: "bar",
    data: {
      labels: rows.map((r) => r.item),
      datasets: [{ data: rows.map((r) => r.wholesale_change_pct), borderRadius: 4,
        backgroundColor: rows.map((r) => (r.wholesale_change_pct >= 0 ? "#E2453C" : "#1E9E7A")) }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: (c) => ` 1주 ${pct(c.raw)} · ${won(rows[c.dataIndex].wholesale_kg)}/kg · ${verdict(rows[c.dataIndex].forecast).text}` } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#1F2622", font: { size: 14, weight: "700" }, autoSkip: false, maxRotation: 0 } },
        y: { grid: { color: "#F0EDE6" }, ticks: { color: "#8A918C", font: { size: 11 }, callback: (v) => `${v}%` } },
      },
      onClick: (_e, els) => { if (els.length) goSlide(slides().findIndex((s) => s.dataset.item === rows[els[0].index].item)); },
    },
  });
}

// 행사 수(위쪽 띠) · 공휴일(세로 점선)을 그리는 차트 플러그인
const overlayPlugin = {
  id: "overlay",
  beforeDatasetsDraw(c, _args, opts) {
    const { ctx, chartArea: a, scales: { x } } = c;
    const step = (x.getPixelForValue(1) - x.getPixelForValue(0)) || 10;
    ctx.save();
    (opts.eventCounts || []).forEach((n, i) => {
      if (!n) return;
      ctx.fillStyle = `rgba(255, 200, 60, ${Math.min(0.15 + n * 0.08, 0.55)})`;
      ctx.fillRect(x.getPixelForValue(i) - step / 2, a.top, step, 7);
    });
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = "#E2453C";
    ctx.fillStyle = "#E2453C";
    ctx.font = "11px Noto Sans KR";
    (opts.holidays || []).forEach(({ i, name }) => {
      const px = x.getPixelForValue(i);
      ctx.beginPath(); ctx.moveTo(px, a.top + 9); ctx.lineTo(px, a.bottom); ctx.stroke();
      ctx.fillText(name, px + 3, a.top + 20);
    });
    ctx.restore();
  },
};

function drawItemChart(canvas, d) {
  const h = d.history || [];
  const f = d.forecast;
  const labels = h.map((r) => mmdd(r.date));
  const price = h.map((r) => r.kg_price);
  const fcLine = h.map(() => null), lo = h.map(() => null), hi = h.map(() => null);
  if (h.length && f && !f.error && f.expected_kg_price_range) {
    const base = h.at(-1).kg_price;
    fcLine[h.length - 1] = lo[h.length - 1] = hi[h.length - 1] = base;
    const start = new Date(h.at(-1).date);
    for (let k = 1; k <= 7; k++) {
      labels.push(mmdd(new Date(start.getTime() + k * 864e5).toISOString().slice(0, 10)));
      price.push(null);
      fcLine.push(k === 7 ? base * (1 + f.expected_change_pct / 100) : null);
      lo.push(k === 7 ? f.expected_kg_price_range[0] : null);
      hi.push(k === 7 ? f.expected_kg_price_range[1] : null);
    }
  }
  const rain = labels.map((_, i) => h[i]?.rain_mm ?? null);
  const eventCounts = labels.map((_, i) => h[i]?.events.length ?? 0);
  const hols = h.map((r, i) => (r.holiday ? { i, name: r.holiday } : null)).filter(Boolean);
  const ctx = canvas.getContext("2d");
  const grad = ctx.createLinearGradient(0, 0, 0, 260);
  grad.addColorStop(0, "rgba(91, 194, 54, 0.30)");
  grad.addColorStop(1, "rgba(91, 194, 54, 0.02)");
  return new Chart(ctx, {
    data: {
      labels,
      datasets: [
        { type: "line", label: "도매 kg당", data: price, borderColor: "#5BC236", backgroundColor: grad, fill: true,
          tension: 0.15, pointRadius: 3, pointBackgroundColor: "#5BC236", borderWidth: 2, yAxisID: "y", order: 1 },
        { type: "line", label: "예측 상단", data: hi, borderColor: "transparent", backgroundColor: "rgba(232,106,46,0.12)",
          fill: "+1", spanGaps: true, pointRadius: 0, yAxisID: "y", order: 2 },
        { type: "line", label: "예측 하단", data: lo, borderColor: "transparent", spanGaps: true, pointRadius: 0, yAxisID: "y", order: 2 },
        { type: "line", label: "다음 7일 예측", data: fcLine, borderColor: "#E86A2E", borderDash: [6, 5], spanGaps: true,
          pointRadius: (c) => (c.dataIndex === labels.length - 1 ? 4 : 0), pointBackgroundColor: "#E86A2E", borderWidth: 2, yAxisID: "y", order: 0 },
        { type: "bar", label: "강수량(mm)", data: rain, backgroundColor: "rgba(120, 175, 230, 0.55)", yAxisID: "rain", order: 3, barPercentage: 0.6 },
      ],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        overlay: { eventCounts, holidays: hols },
        tooltip: {
          filter: (item) => item.raw != null && !["예측 상단", "예측 하단"].includes(item.dataset.label),
          callbacks: {
            label: (c) => c.dataset.label === "강수량(mm)" ? ` 비 ${c.raw}mm` : ` ${c.dataset.label} ${won(c.raw)}`,
            afterBody: (items) => {
              const r = h[items[0].dataIndex];
              if (!r) return f && !f.error ? [`예상 범위 ${won(f.expected_kg_price_range[0])} ~ ${won(f.expected_kg_price_range[1])}`] : [];
              const out = [];
              if (r.max_temp != null) out.push(`기온 ${r.min_temp}~${r.max_temp}℃`);
              if (r.holiday) out.push(`공휴일: ${r.holiday}`);
              if (r.events.length) out.push(`행사 ${r.events.length}개: ${r.events.slice(0, 2).join(", ")}${r.events.length > 2 ? " 외" : ""}`);
              return out;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { maxTicksLimit: 7, color: "#8A918C", font: { size: 11 } } },
        y: { position: "right", grid: { color: "#F0EDE6" }, ticks: { color: "#8A918C", font: { size: 11 }, callback: (v) => won(v) } },
        rain: { position: "left", display: false, min: 0, max: Math.max(40, ...rain.filter(Boolean)) * 4 },
      },
    },
    plugins: [overlayPlugin],
  });
}

// ---------------------------------------------------------------
// 재료 전용 페이지 (/?item=토마토): 그 재료의 날짜별 시세 · 예측 · 식봄 연결만 보여 줌
// ---------------------------------------------------------------
function renderItemPage() {
  const r = byItem(ITEM);
  if (!r) {
    $("#itemHead").innerHTML = `<h1>${esc(ITEM)}</h1><p class="muted">아직 시세를 제공하지 않는 재료예요.</p>`;
    return;
  }
  document.title = `${r.item} 시세 · 살피`;
  const v = verdict(r.forecast);
  $("#itemHead").innerHTML = `
    <div><h1>${esc(r.item)}</h1><p class="${v.kind === "flat" ? "" : v.kind}">${esc(v.text)}</p></div>
    <a class="item-shop" href="${esc(r.foodspring_url || "https://www.foodspring.co.kr")}" target="_blank" rel="noopener">${esc(r.item)} 구매 바로가기 →</a>`;
  $("#itemBody").hidden = false;
  $("#itemDash").innerHTML = itemSlide(r, 0);
  drawItemChart($("#itemDash canvas"), r);
  renderDetail(r.item);
  renderProducts();
}

function renderItemGoods() {
  const r = byItem(ITEM);
  if (!r || !shopLoaded) return;
  renderForecast(r.forecast);   // 식봄 최저가 안내가 들어가도록 다시 그림
  const goods = (shop[ITEM] || []).slice(0, 8);
  $("#itemGoodsWrap").hidden = !goods.length;   // 상품을 못 받으면 위 구매 버튼만 남김
  $("#itemGoods").innerHTML = goods.map((g) => productCard({ item: ITEM, g })).join("");
}

function renderDetail(name) {
  const d = byItem(name);
  if (!d) return;
  boardItem = d;
  renderBoard();
  renderForecast(d.forecast);
}

// 시세판: 최근 10거래일의 직전 거래일 대비 증감 (등락액 원 / 등락률 %)
const BOARD_DAYS = 10;
let boardItem = null, boardMode = "won";

const rate = (r) => (r.diff == null || r.kg_price === r.diff ? null : (r.diff / (r.kg_price - r.diff)) * 100);
const arrow = (v) => (v > 0 ? "▲" : v < 0 ? "▼" : "");
const number = (v) => Math.round(v).toLocaleString("ko-KR");
// 그래프 값 · 표시: 등락액은 원, 등락률은 %
const boardValue = (r) => (boardMode === "won" ? r.diff : rate(r));
const boardText = (v) => (boardMode === "won" ? `${number(Math.abs(v))}원` : `${Math.abs(v).toFixed(1)}%`);
const boardSigned = (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${boardText(v)}`;

// 눈금 간격: 1 · 2 · 5 × 10ⁿ 중 위아래로 세 칸 안팎이 나오는 값
function boardScale(peak) {
  const raw = (peak || 1) / 3, unit = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * unit).find((v) => v >= raw);
  return { step, top: step * Math.ceil((peak || 1) / step) };
}

function renderBoard() {
  const d = boardItem;
  const rows = (d.history || []).slice(-BOARD_DAYS);
  const last = rows.at(-1);
  if (!last) { $("#priceBoard").innerHTML = `<p class="muted">최근 거래 기록이 없어요</p>`; return; }
  const prev = (d.history || []).at(-2);
  const moved = rows.filter((r) => boardValue(r) != null);
  const ups = moved.filter((r) => r.diff > 0), downs = moved.filter((r) => r.diff < 0);
  const total = (list) => list.reduce((a, r) => a + boardValue(r), 0) / (boardMode === "won" ? 1 : list.length || 1);
  const totalName = boardMode === "won" ? "합계" : "평균";
  const big = [...moved].sort((a, b) => Math.abs(boardValue(b)) - Math.abs(boardValue(a)))[0];
  const change = boardValue(last);

  const { step, top } = boardScale(Math.max(0, ...moved.map((r) => Math.abs(boardValue(r)))));
  const place = (v) => 50 - (v / top) * 50;   // 값 → 위에서부터 %
  const ticks = [];
  for (let v = -top; v <= top + step / 2; v += step) ticks.push(v);
  const tickText = (v) => (v > 0 ? "+" : v < 0 ? "-" : "") + (boardMode === "won" ? number(Math.abs(v)) : `${+Math.abs(v).toFixed(1)}%`);

  const cols = rows.map((r) => {
    const v = boardValue(r);
    if (v == null) return `<div class="board-col"></div>`;
    const h = (Math.abs(v) / top) * 50, kind = v > 0 ? "up" : v < 0 ? "down" : "";
    const bar = kind ? `<i class="board-bar ${kind}" style="top:${v > 0 ? place(v) : 50}%;height:${h}%"></i>` : "";
    const at = v >= 0 ? `bottom:calc(${50 + h}% + 3px)` : `top:calc(${50 + h}% + 3px)`;
    return `<div class="board-col">${bar}<b class="board-val ${kind}" style="${at}">${arrow(v)}${boardMode === "won" ? number(Math.abs(v)) : boardText(v)}</b></div>`;
  }).join("");

  const days = rows.map((r) => `<div class="board-day ${r === last ? "today" : ""}"><span>${mmdd(r.date)}</span><b>${won(r.kg_price)}</b></div>`).join("");

  $("#priceBoard").innerHTML = `
    <div class="board-head">
      <div>
        <p class="board-label">${esc(d.item)} · 도매 kg당 · ${mmdd(last.date)} 기준</p>
        <p class="board-now"><b>${number(last.kg_price)}<small>원</small></b>
          ${change == null ? "" : `<span><strong class="${cls(change)}">${arrow(change)} ${boardSigned(change)}</strong> 직전 거래일${prev ? `(${mmdd(prev.date)})` : ""} 대비</span>`}</p>
      </div>
      <div class="board-toggle" role="group" aria-label="증감 표시 단위">
        <button data-mode="won" aria-pressed="${boardMode === "won"}">등락액 원</button>
        <button data-mode="pct" aria-pressed="${boardMode === "pct"}">등락률 %</button>
      </div>
    </div>
    <div class="board-stats">
      <div class="board-stat"><small>상승한 날</small><b>${ups.length}일</b><span>${totalName} ${ups.length ? boardSigned(total(ups)) : "-"}</span></div>
      <div class="board-stat"><small>하락한 날</small><b>${downs.length}일</b><span>${totalName} ${downs.length ? boardSigned(total(downs)) : "-"}</span></div>
      <div class="board-stat"><small>가장 크게 움직인 날</small><b>${big ? `${mmdd(big.date)} <span class="${cls(boardValue(big))}" style="margin:0;font-size:inherit">${arrow(boardValue(big))} ${boardText(boardValue(big))}</span>` : "-"}</b></div>
    </div>
    <div class="board-scroll"><div class="board-inner" style="--days:${rows.length}">
      <div class="board-plot">
        ${ticks.map((v) => `<div class="board-tick ${v === 0 ? "zero" : ""}" style="top:${place(v)}%"><span>${tickText(v)}</span></div>`).join("")}
        <div class="board-cols">${cols}</div>
      </div>
      <div class="board-days">${days}</div>
    </div></div>
    <p class="board-legend">
      <span><i style="background:var(--up)"></i>▲ 상승</span><span><i style="background:var(--down)"></i>▼ 하락</span>
    </p>`;
  const scroll = $(".board-scroll");
  scroll.scrollLeft = scroll.scrollWidth;   // 좁은 화면은 최근 날짜부터 보이게
}
$("#priceBoard").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-mode]");
  if (!b) return;
  boardMode = b.dataset.mode;
  renderBoard();
});

function cheapest(item) {
  // kg당 가격이 있는 상품 중 가장 싼 것, 없으면 첫 상품
  const list = shop[item] || [];
  return [...list].filter((g) => g.price_per_kg).sort((a, b) => a.price_per_kg - b.price_per_kg)[0] || list[0];
}

function renderForecast(f) {
  if (!f || f.error) { $("#forecastCard").innerHTML = ""; return; }
  const maxAbs = Math.max(4, ...f.factors.map((x) => Math.abs(x.effect_pct)));
  const g = cheapest(f.item);
  const v = verdict(f);
  $("#forecastCard").innerHTML = `
    <p class="dir ${cls(f.expected_change_pct, 2)}">${esc(v.text)}</p>
    <p class="tip">${esc(f.suggestion)}${g ? ` · <a href="${esc(g.url)}" target="_blank" rel="noopener" style="color:var(--accent)">식봄 ${won(g.sale_price)} 상품 보기 →</a>` : ""}</p>
    <p class="muted range">예상 ${won(f.expected_kg_price_range?.[0])} ~ ${won(f.expected_kg_price_range?.[1])} /kg</p>
    ${f.factors.map((x) => {
      const w = (Math.abs(x.effect_pct) / maxAbs) * 50;
      const style = x.effect_pct >= 0 ? `left:50%;width:${w}%;background:var(--up)` : `right:50%;width:${w}%;background:var(--down)`;
      return `<div class="factor"><span>${esc(factorName(x.factor))}</span><span class="bar"><i style="${style}"></i></span>
        <b class="${cls(x.effect_pct)}">${pct(x.effect_pct)}</b><span class="detail-text">${esc(x.detail)}</span></div>`;
    }).join("")}
    <p class="muted" style="margin-top:8px;font-size:12px">${esc(f.method)}</p>`;
}

// ---------------------------------------------------------------
// 우리 가게 내일 준비 (판매 기록 → 예상 그릇 수 → 재료 필요량 · 발주)
// ---------------------------------------------------------------
const qty = (v, unit) => (unit === "모" ? `${Math.round(v)}모` : `${(+v).toFixed(1)}${unit}`);

// 가장 영향이 큰 이유 한 줄 (factors: 0.05 = 평소보다 +5%)
function demandReason(factors) {
  const [name, v] = Object.entries(factors).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0] || [];
  if (name === "휴무일") return "가게 쉬는 날이에요";
  if (v == null || Math.abs(v) < 0.02) return "평소와 비슷하게 팔릴 날이에요";
  const p = Math.round(Math.abs(v) * 100);
  if (name === "최근 2주 흐름") return `최근 2주 판매가 그 전보다 ${p}% ${v > 0 ? "늘었어요" : "줄었어요"}`;
  return `${name}은 평소보다 ${p}% ${v > 0 ? "많이" : "적게"} 팔려요`;
}

async function loadDemand() {
  let d;
  try {
    d = await getJSON("/api/demand");
  } catch (e) {
    $("#storeBasis").textContent = "";
    $("#menuForecast").innerHTML = `<p class="muted">판매 기록을 불러오지 못했어요. ${esc(e.message)}</p>`;
    return;
  }
  if (d.error) { $("#menuForecast").innerHTML = `<p class="muted">${esc(d.error)}</p>`; return; }
  const day = `${mmdd(d.target_date)}(${d.target_weekday})`;
  $("#storeBasis").textContent = `${d.store.is_demo ? "시연용 가게 · " : ""}${d.store.name} · 판매 기록 ${mmdd(d.last_sales_date)}까지 · ${d.method}`;
  $("#menuForecast").innerHTML = `
    <span class="badge">내일 ${day}${d.is_holiday ? " · 공휴일" : ""} 예상 판매</span>
    <p class="demand-total">${d.is_open ? `모두 <b>${d.total_predicted}그릇</b> 팔릴 것 같아요` : "내일은 가게 쉬는 날이에요"}</p>
    ${d.menus.map((m) => {
      const max = Math.max(m.range[1], ...m.recent.map((x) => x.qty), 1);
      const bars = m.recent.map((x) => `<i style="height:${(x.qty / max) * 100}%" title="${mmdd(x.date)} ${x.qty}그릇"></i>`).join("");
      return `<div class="demand-row">
        <div class="demand-name"><b>${esc(m.menu)}</b><small>${esc(demandReason(m.factors))}</small></div>
        <div class="spark" aria-hidden="true">${bars}<i class="next" style="height:${(m.predicted / max) * 100}%" title="내일 예상 ${m.predicted}그릇"></i></div>
        <div class="demand-qty"><b>${m.predicted}그릇</b><small>${m.range[0]} ~ ${m.range[1]}</small></div>
      </div>`;
    }).join("")}
    <p class="muted small">막대: 최근 14일 판매 · <span style="color:var(--accent)">주황</span>은 내일 예상</p>`;
  $("#orderCard").innerHTML = `
    <table class="price-table order-table">
      <thead><tr><th>재료</th><th>내일 필요</th><th>${d.next_delivery_date ? `${mmdd(d.next_delivery_date)} 입고 전까지` : "필요"}</th><th>재고</th><th>발주</th><th>판단</th></tr></thead>
      <tbody>${d.items.map((i) => `<tr title="${esc(i.reason)}">
        <td>${esc(i.item)}</td><td>${qty(i.need_target, i.unit)}</td><td>${qty(i.need_until_delivery, i.unit)}</td>
        <td>${qty(i.on_hand, i.unit)}</td><td class="price">${i.order_qty > 0 ? qty(i.order_qty, i.unit) : "-"}</td>
        <td><span class="decision ${i.decision === "지금 사기" ? "buy" : i.decision === "나눠 사기" ? "split" : "wait"}">${esc(i.decision)}</span></td>
      </tr>`).join("")}</tbody>
    </table>
    <p class="muted small" style="padding:0 8px">발주 = 다음 입고 전까지 필요량 + 10% 여유 − 재고. 줄에 마우스를 올리면 이유가 보여요.</p>`;
}

// ---------------------------------------------------------------
// 식봄 상품 목록
// ---------------------------------------------------------------
let filterItem = "전체", shopLoaded = false;
async function loadProducts() {
  try {
    shop = (await getJSON("/api/products")).items;
  } catch (e) {
    shop = {};
  }
  shopLoaded = true;
  renderProducts();
}

function renderFilter() {
  $("#productFilter").innerHTML = ["전체", ...overview.map((r) => r.item)]
    .map((n) => `<button data-f="${esc(n)}" class="${n === filterItem ? "active" : ""}">${esc(n)}</button>`).join("");
  $("#productFilter").onclick = (e) => {
    const b = e.target.closest("button[data-f]");
    if (!b) return;
    filterItem = b.dataset.f;
    renderFilter();
    renderProducts();
  };
}

function renderProducts() {
  if (!overview.length) return;
  if (ITEM) { renderItemGoods(); return; }
  const items = filterItem === "전체" ? overview.map((r) => r.item) : [filterItem];
  const perItem = filterItem === "전체" ? 2 : 8;
  const cards = items.flatMap((item) => (shop[item] || []).slice(0, perItem).map((g) => ({ item, g })));
  if (!cards.length) {
    // 식봄 상품을 못 받아 왔을 때: 재료별 식봄 검색으로 연결
    $("#productGrid").innerHTML = items.map((item) => {
      const r = byItem(item) || {};
      return `<a class="product" href="${esc(r.foodspring_url || "https://www.foodspring.co.kr")}" target="_blank" rel="noopener">
        <div class="img" style="display:grid;place-items:center;font-size:26px;font-weight:900;color:#6F7570">${esc(item)}</div>
        <span class="name">식봄에서 ${esc(item)} 찾아보기 →</span>
        ${r.wholesale_kg ? `<span class="per">도매 kg당 ${won(r.wholesale_kg)} · 1주 <b class="${cls(r.wholesale_change_pct, 3)}">${pct(r.wholesale_change_pct)}</b></span>` : ""}
      </a>`;
    }).join("");
    return;
  }
  $("#productGrid").innerHTML = cards.map(productCard).join("");
}

function productCard({ item, g }) {
  const r = byItem(item) || { forecast: {} };
  const exp = expOf(r);
  const flag = exp >= 2 ? `<span class="flag" style="background:var(--up)">다음 주 오를 듯</span>`
    : exp <= -2 ? `<span class="flag" style="background:var(--down)">다음 주 떨어질 듯</span>` : "";
  const salpi = r.wholesale_change_pct == null ? ""
    : `<span class="salpi">살피: ${esc(item)} 도매 1주 <b class="${cls(r.wholesale_change_pct, 3)}">${pct(r.wholesale_change_pct)}</b></span>`;
  const sale = g.discount_rate && g.original_price > g.sale_price;
  return `
    <a class="product" href="${esc(g.url)}" target="_blank" rel="noopener">
      <div class="img">${g.image ? `<img src="${esc(g.image)}" alt="" loading="lazy">` : ""}${flag}</div>
      <span class="vendor">${esc(g.vendor || "")}</span>
      <span class="name">${esc(g.name)}</span>
      ${sale ? `<span class="orig">${won(g.original_price)}</span>` : ""}
      <span class="price">${sale ? `<span class="rate">${g.discount_rate}%</span>` : ""}${won(g.sale_price)}</span>
      ${g.price_per_kg ? `<span class="per">kg당 ${won(g.price_per_kg)}</span>` : ""}
      ${salpi}
    </a>`;
}

// ---------------------------------------------------------------
// 날씨 · 공휴일 · 행사
// ---------------------------------------------------------------
async function loadContext() {
  let c;
  try { c = await getJSON("/api/context"); } catch (e) { return; }
  const w = c.weather;
  $("#weatherCard").innerHTML = `<h3>대구 날씨 (지난 7일)</h3>
    <p class="muted" style="margin-bottom:10px">비 ${w.rain_total_mm}mm (${w.rain_days}일) · 최저 ${w.min_temp}℃ · 최고 ${w.max_temp}℃</p>
    <div class="wx">${(w.daily || []).map((d) => `<div>${mmdd(d.date)}<b>${Math.round(d.max_temp)}°</b>${d.rain_mm ? `비 ${d.rain_mm}` : "-"}</div>`).join("")}</div>`;
  const fmt = (s) => `${s.slice(4, 6)}.${s.slice(6, 8)}`;
  $("#holidayCard").innerHTML = `<h3>다가오는 공휴일 (30일)</h3>` + (c.holidays.length
    ? `<ul class="ctx-list">${c.holidays.map((x) => `<li>${fmt(x.date)} ${esc(x.name)}<small>도매시장 휴장 전 수요가 몰릴 수 있어요</small></li>`).join("")}</ul>`
    : `<p class="muted">30일 안에 공휴일이 없어요</p>`);
  $("#eventCard").innerHTML = `<h3>대구 행사 · 축제 (14일, ${c.events.length}개)</h3>` + (c.events.length
    ? `<ul class="ctx-list">${c.events.slice(0, 8).map((x) => `<li>${esc(x.title)}<small>${fmt(x.start)} ~ ${fmt(x.end)} · ${esc((x.addr || "").replace("대구광역시 ", ""))}</small></li>`).join("")}</ul>`
    : `<p class="muted">14일 안에 열리는 행사가 없어요</p>`);
}

// ---------------------------------------------------------------
// 살피 챗봇
// ---------------------------------------------------------------
const chatEl = $("#chat"), body = $("#chatBody");
const history = [];   // 지난 대화 (서버가 기억하지 않으므로 화면이 보관해서 매번 보냄)

function md(text) {
  // 굵게 · 목록 · 줄바꿈만 지원하는 간단한 변환
  const lines = esc(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").split(/\n/);
  let html = "", inList = false;
  for (const raw of lines) {
    const line = raw.trim();
    const item = line.match(/^(?:[*\-•]|\d+\.)\s+(.*)/);
    if (item) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${item[1]}</li>`; continue; }
    if (inList) { html += "</ul>"; inList = false; }
    if (line) html += `<p>${line}</p>`;
  }
  return html + (inList ? "</ul>" : "");
}

function addMsg(role, text) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.innerHTML = role === "bot" ? md(text) : esc(text);
  body.appendChild(el);
  body.scrollTop = body.scrollHeight;
  return el;
}

function openChat() {
  chatEl.classList.add("open");
  chatEl.setAttribute("aria-hidden", "false");
  document.body.classList.add("chat-open");
  placeChat();
  if (!body.children.length) addMsg("bot", "사장님, 오늘 대구 시세 살펴왔어요.\n아래 버튼을 누르거나 편하게 물어보세요.");
  $("#chatText").focus();
}
function closeChat() {
  chatEl.classList.remove("open");
  chatEl.setAttribute("aria-hidden", "true");
  document.body.classList.remove("chat-open");
}
$("#chatClose").addEventListener("click", closeChat);

// 채팅창 크기: 가장자리 · 모서리에 마우스를 대면 화살표 커서로 바뀌고, 끌면 크기 조절
const EDGE = 8, CORNER = 22;   // 모서리는 둥글어서 끝점이 창 밖 → 가장자리 근처 22px까지 모서리로 봄
const CURSOR = { n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize",
                 ne: "nesw-resize", sw: "nesw-resize", nw: "nwse-resize", se: "nwse-resize" };
function edgeAt(e) {
  const r = chatEl.getBoundingClientRect();
  const near = (d) => (d < EDGE ? 2 : d < CORNER ? 1 : 0);   // 2: 가장자리 위, 1: 모서리 근처
  const t = near(e.clientY - r.top), b = near(r.bottom - e.clientY), l = near(e.clientX - r.left), rt = near(r.right - e.clientX);
  const v = t ? "n" : b ? "s" : "", h = l ? "w" : rt ? "e" : "";
  if (v && h && Math.max(t, b) + Math.max(l, rt) >= 3) return v + h;   // 모서리
  return (Math.max(t, b) === 2 ? v : "") + (Math.max(l, rt) === 2 ? h : "");
}
let rs = null;
chatEl.addEventListener("pointermove", (e) => {
  if (rs) {
    const dx = e.clientX - rs.x, dy = e.clientY - rs.y;
    let { left, top, width, height } = rs.box;
    if (rs.dir.includes("e")) width += dx;
    if (rs.dir.includes("s")) height += dy;
    if (rs.dir.includes("w")) { width -= dx; left += dx; }
    if (rs.dir.includes("n")) { height -= dy; top += dy; }
    const w = Math.max(320, Math.min(window.innerWidth - 16, width));
    const h = Math.max(360, Math.min(window.innerHeight - 16, height));
    if (rs.dir.includes("w")) left += width - w;   // 최소 크기에 걸리면 반대쪽이 밀리지 않게
    if (rs.dir.includes("n")) top += height - h;
    Object.assign(chatEl.style, { width: `${w}px`, height: `${h}px`, right: "auto", bottom: "auto",
      left: `${Math.max(0, Math.min(window.innerWidth - w, left))}px`, top: `${Math.max(0, Math.min(window.innerHeight - h, top))}px` });
    return;
  }
  chatEl.style.cursor = CURSOR[edgeAt(e)] || "";
});
chatEl.addEventListener("pointerdown", (e) => {
  const dir = edgeAt(e);
  if (!dir) return;
  const r = chatEl.getBoundingClientRect();
  rs = { dir, x: e.clientX, y: e.clientY, box: { left: r.left, top: r.top, width: r.width, height: r.height } };
  chatEl.setPointerCapture(e.pointerId);
  chatEl.classList.add("resizing");
  e.preventDefault();
}, true);
chatEl.addEventListener("pointerup", () => { if (rs) { rs = null; chatEl.classList.remove("resizing"); } });
chatEl.addEventListener("pointerleave", () => { if (!rs) chatEl.style.cursor = ""; });

// 살피 캐릭터 끌어서 옮기기 (살짝 누르면 채팅 열기 · 끌면 이동), 놓은 자리는 이 브라우저에 기억
const fab = $("#fab");
const FAB_KEY = "salpi_fab_pos";
function placeFab(x, y) {
  const w = fab.offsetWidth, h = fab.offsetHeight;
  x = Math.max(0, Math.min(window.innerWidth - w, x));
  y = Math.max(64, Math.min(window.innerHeight - h, y));
  Object.assign(fab.style, { left: `${x}px`, top: `${y}px`, right: "auto", bottom: "auto" });
  fab.classList.toggle("on-left", x + w / 2 < window.innerWidth / 2);   // 왼쪽에 있으면 말풍선을 오른쪽에
  placeChat();
}
function placeChat() {
  // 채팅창을 살피가 있는 쪽에 붙임 (넓은 화면만, 모바일은 아래에서 올라옴)
  if (window.innerWidth <= 700 || !fab.style.left) { chatEl.style.left = chatEl.style.right = chatEl.style.top = chatEl.style.bottom = ""; return; }
  const r = fab.getBoundingClientRect(), cw = chatEl.offsetWidth, ch = chatEl.offsetHeight;
  const left = r.left + r.width / 2 < window.innerWidth / 2 ? r.right + 8 : r.left - cw - 8;
  const top = Math.max(72, Math.min(window.innerHeight - ch - 12, r.bottom - ch));
  Object.assign(chatEl.style, { left: `${Math.max(8, Math.min(window.innerWidth - cw - 8, left))}px`, top: `${top}px`, right: "auto", bottom: "auto" });
}
try {
  const saved = JSON.parse(localStorage.getItem(FAB_KEY) || "null");
  if (saved) requestAnimationFrame(() => placeFab(saved.x * window.innerWidth, saved.y * window.innerHeight));
} catch (e) {}

let drag = null;
fab.addEventListener("pointerdown", (e) => {
  const r = fab.getBoundingClientRect();
  drag = { dx: e.clientX - r.left, dy: e.clientY - r.top, sx: e.clientX, sy: e.clientY, moved: false };
  fab.setPointerCapture(e.pointerId);
});
fab.addEventListener("pointermove", (e) => {
  if (!drag) return;
  if (!drag.moved && Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) < 6) return;   // 손 떨림은 클릭으로 봄
  drag.moved = true;
  fab.classList.add("dragging");
  placeFab(e.clientX - drag.dx, e.clientY - drag.dy);
});
fab.addEventListener("pointerup", () => {
  if (!drag) return;
  fab.classList.remove("dragging");
  if (drag.moved) {
    const r = fab.getBoundingClientRect();
    try { localStorage.setItem(FAB_KEY, JSON.stringify({ x: r.left / window.innerWidth, y: r.top / window.innerHeight })); } catch (e) {}
  } else {
    chatEl.classList.contains("open") ? closeChat() : openChat();
  }
  drag = null;
});
window.addEventListener("resize", () => { if (fab.style.left) placeFab(fab.offsetLeft, fab.offsetTop); });

let busy = false;
async function send(text) {
  text = text.trim();
  if (!text || busy) return;
  busy = true;
  document.querySelectorAll("#quick button").forEach((b) => (b.disabled = true));
  addMsg("me", text);
  const typing = addMsg("bot", "살피가 살펴보는 중이에요…");
  typing.classList.add("typing");
  try {
    const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history }) });
    const d = await r.json();
    typing.remove();
    addMsg("bot", d.reply);
    history.push({ role: "user", text }, { role: "bot", text: d.reply });
  } catch (e) {
    typing.remove();
    addMsg("bot", "연결이 끊겼어요. 잠시 뒤 다시 물어봐 주세요.");
  }
  busy = false;
  document.querySelectorAll("#quick button").forEach((b) => (b.disabled = false));
}
$("#quick").addEventListener("click", (e) => { const b = e.target.closest("button[data-q]"); if (b) send(b.dataset.q); });
$("#chatForm").addEventListener("submit", (e) => { e.preventDefault(); const t = $("#chatText"); send(t.value); t.value = ""; });

// ---------------------------------------------------------------
// 검색: 글자가 이름 어디에 들어 있든 찾음 ("토" → 토마토, 방울토마토 상품). 띄어쓰기와 대소문자는 무시
// ---------------------------------------------------------------
const searchInput = $("#searchInput"), searchList = $("#searchList");
const squash = (s) => String(s ?? "").toLowerCase().replace(/\s/g, "");
let searchHits = [], searchActive = -1;

function markHit(text, word) {
  const at = String(text).toLowerCase().indexOf(word.toLowerCase());
  if (at < 0) return esc(text);
  const end = at + word.length;
  return `${esc(text.slice(0, at))}<mark>${esc(text.slice(at, end))}</mark>${esc(text.slice(end))}`;
}

function findAll(word) {
  const key = squash(word);
  const items = overview.filter((r) => squash(r.item).includes(key))
    .map((r) => ({ name: r.item, note: r.wholesale_kg ? `도매 kg당 ${won(r.wholesale_kg)}` : "" }));
  const seen = new Set();
  const goods = Object.values(shop).flat().filter((g) => {
    if (seen.has(g.url) || !squash(g.name).includes(key)) return false;
    seen.add(g.url);
    return true;
  }).map((g) => ({ name: g.name, note: won(g.sale_price), url: g.url }));
  return { items, goods };
}

function closeSearch() {
  searchList.hidden = true;
  searchActive = -1;
  searchInput.setAttribute("aria-expanded", "false");
  searchInput.removeAttribute("aria-activedescendant");
}

function renderSearch() {
  const word = searchInput.value.trim();
  if (!squash(word)) { closeSearch(); return; }
  const { items, goods } = findAll(word);
  searchHits = [...items, ...goods];
  searchActive = -1;
  searchInput.removeAttribute("aria-activedescendant");
  const hit = (h, i) => `<a class="search-hit" id="hit${i}" role="option" aria-selected="false" href="${h.url ? esc(h.url) : `/?item=${encodeURIComponent(h.name)}`}"
    ${h.url ? 'target="_blank" rel="noopener"' : ""}><span>${markHit(h.name, word)}</span><small>${esc(h.note)}</small></a>`;
  searchList.innerHTML = searchHits.length
    ? (items.length ? `<p class="search-group">야채 시세 ${items.length}개</p>${items.map((h, i) => hit(h, i)).join("")}` : "")
      + (goods.length ? `<p class="search-group">식봄 상품 ${goods.length}개</p>${goods.map((h, i) => hit(h, items.length + i)).join("")}` : "")
    : `<p class="search-empty">${overview.length ? `'${esc(word)}'이(가) 들어간 재료나 상품이 없어요` : "시세를 불러오는 중이에요"}</p>`;
  searchList.hidden = false;
  searchInput.setAttribute("aria-expanded", "true");
}

function moveSearch(step) {
  if (!searchHits.length) return;
  $(`#hit${searchActive}`)?.classList.remove("active");
  $(`#hit${searchActive}`)?.setAttribute("aria-selected", "false");
  searchActive = (searchActive + step + searchHits.length) % searchHits.length;
  const el = $(`#hit${searchActive}`);
  el.classList.add("active");
  el.setAttribute("aria-selected", "true");
  el.scrollIntoView({ block: "nearest" });
  searchInput.setAttribute("aria-activedescendant", el.id);
}

searchInput.addEventListener("input", renderSearch);
searchInput.addEventListener("focus", renderSearch);
searchInput.addEventListener("keydown", (e) => {
  if (e.isComposing) return;   // 한글 조합 중에는 키 동작 없음
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); moveSearch(e.key === "ArrowDown" ? 1 : -1); }
  if (e.key === "Escape") closeSearch();
  if (e.key === "Enter" && searchHits.length && !searchList.hidden) {
    e.preventDefault();
    $(`#hit${Math.max(searchActive, 0)}`).click();
  }
});
searchList.addEventListener("click", (e) => { if (e.target.closest(".search-hit")) closeSearch(); });
document.addEventListener("click", (e) => { if (!e.target.closest(".search")) closeSearch(); });
document.addEventListener("focusin", (e) => { if (!e.target.closest(".search")) closeSearch(); });

// ---------------------------------------------------------------
// 알림톡 시연: 세그먼트별 메시지 (실제 발송 없음). 시세 문장은 오늘 값, 나머지는 예시 문장
// ---------------------------------------------------------------
function talkMessages() {
  const byExp = slideOrder();
  const rising = byExp.filter((r) => expOf(r) >= 2);
  const falling = byExp.at(-1);
  const top = rising[0];
  const live = "오늘 시세 기준";
  const sample = "가게 데이터가 쌓이면 실제 값으로 나가는 예시 문장";
  return {
    S1: { name: "S1 시세 민감", policy: "가격 알림을 먼저 보내요", title: "기다려도 좋은 재료",
      ...(falling && expOf(falling) <= -2
        ? { body: `${falling.item}, 다음 주에 떨어질 가능성이 있어요.\n급하지 않으면 며칠 기다려 보세요.`, basis: live }
        : { body: "양파, 오늘보다 다음 주가 쌀 가능성이 있어요.\n급하지 않으면 며칠 기다려 보세요.", basis: sample }) },
    S2: { name: "S2 루틴 고정", policy: "평소와 다를 때만 보내요", title: "평소와 달라요",
      body: "이번 주는 평소보다 돼지고기 3kg 더 필요해요.\n발주량을 확인해 보세요.", basis: sample },
    S3: { name: "S3 대량 계획", policy: "주 1회 요약 리포트로 보내요", title: "주간 가격 위험 요약",
      ...(rising.length
        ? { body: `다음 주 오를 가능성이 있는 재료 ${rising.length}개: ${rising.slice(0, 3).map((r) => r.item).join(", ")}\n식단을 확정하기 전에 살펴보세요.`, basis: live }
        : { body: "다음 주 식단 중 가격 위험 품목 2개가 있어요.\n식단을 확정하기 전에 살펴보세요.", basis: sample }) },
    S4: { name: "S4 급발주 위험", policy: "전날 오후에 미리 보내요", title: "미리 준비할 재료",
      body: "금요일 비 예보가 있어요.\n제육볶음 재료를 오늘 미리 살펴보세요.", basis: sample },
    S5: { name: "S5 이탈 위험", policy: "성과 요약을 1회만 보내고 다른 알림은 줄여요", title: "지난주 살피 성과",
      body: "지난주 김치찌개 예측이 얼마나 맞았는지 정리했어요.\n한 번 살펴보세요.", basis: sample },
    hold: { name: "판단 보류", policy: "기록이 적어 누구에게나 맞는 기본 안내만 보내요", title: "오늘의 시세",
      ...(top
        ? { body: `${top.item}, 다음 주에 오를 가능성이 있어요.\n필요한 양을 확인해 보세요.`, basis: live }
        : { body: "오늘 대구 도매 시세를 살펴왔어요.\n필요한 재료를 확인해 보세요.", basis: sample }) },
  };
}

let talkKind = "S1";
function renderTalk() {
  const all = talkMessages(), m = all[talkKind];
  $("#talkTabs").innerHTML = Object.entries(all).map(([key, v]) =>
    `<button data-kind="${key}" aria-pressed="${key === talkKind}">${esc(v.name)}</button>`).join("");
  $("#talkPolicy").textContent = m.policy;
  $("#talkRoom").innerHTML = `
    <p class="talk-time">오전 7:00</p>
    <div class="talk-msg">
      <img src="/static/img/salpi_face.png" alt="">
      <div>
        <p class="talk-from">살피</p>
        <div class="talk-card"><h3>${esc(m.title)}</h3><p>${esc(m.body)}</p><a href="/#dashboard" id="talkLink">시세 보러 가기</a></div>
      </div>
    </div>
    <p class="talk-basis">${esc(m.basis)}</p>`;
}
function openTalk() {
  renderTalk();
  $("#talk").hidden = false;
  $("#talkClose").focus();
}
function closeTalk() {
  $("#talk").hidden = true;
  $("#talkOpen").focus();
}
$("#talkOpen").addEventListener("click", openTalk);
$("#talkClose").addEventListener("click", closeTalk);
$("#talk").addEventListener("click", (e) => {
  if (e.target.id === "talk" || e.target.id === "talkLink") closeTalk();
  const b = e.target.closest("button[data-kind]");
  if (b) { talkKind = b.dataset.kind; renderTalk(); $(`#talkTabs [data-kind="${talkKind}"]`).focus(); }
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#talk").hidden) closeTalk(); });

loadOverview();
loadProducts();
if (!ITEM) {
  loadContext();
  loadDemand();
}
if (location.hash === "#chat") openChat();   // 주소 끝에 #chat 을 붙이면 채팅창이 열린 채로 시작
if (location.hash === "#talk") openTalk();   // 주소 끝에 #talk 을 붙이면 알림톡 시연이 열린 채로 시작
if (location.hash === "#rise") setTimeout(() => goSlide(1, "instant"), 4000);   // 시연용: 첫 야채 대시보드부터
