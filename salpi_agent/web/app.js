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

async function getJSON(url) {
  const r = await fetch(url);
  const body = await r.json();
  if (!r.ok) throw new Error(body.detail || "데이터를 불러오지 못했어요");
  return body;
}
const byItem = (name) => overview.find((r) => r.item === name);
const expOf = (r) => r.forecast?.expected_change_pct ?? 0;
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
    $("#slider").innerHTML = `<article class="slide card loading-card"><b>시세를 불러오지 못했어요</b>
      <p class="muted">${esc(e.message)}</p><button class="sort" onclick="location.reload()">다시 불러오기</button></article>`;
    $("#summary").innerHTML = "";
    return;
  }
  const dated = overview.map((r) => r.wholesale_date).filter(Boolean).sort();
  $("#basis").textContent = dated.length ? `대구 북부도매시장 · ${mmdd(dated.at(-1))} 기준` : "";

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
    </article>` + slideOrder().map((r, idx) => {
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
        <ul>${reasons.map((x) => `<li><b>${esc(x.factor)}</b> ${pct(x.effect_pct)} — ${esc(x.detail)}</li>`).join("")
          || "<li>뚜렷하게 오르거나 내릴 이유가 적어요</li>"}</ul>
      </div>
    </article>`;
    }).join("");
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
  renderDetail(s[i]?.dataset.item || slideOrder()[0]?.item);
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
restartAuto();

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
// 아래 "날짜별 시세": 지금 보고 있는 야채 (전체 화면이면 오를 가능성이 가장 큰 야채)
// ---------------------------------------------------------------
function renderDetail(name) {
  const d = byItem(name);
  if (!d) return;
  $("#detailTitle").textContent = `${name} 날짜별 시세`;
  $("#priceRows").innerHTML = [...(d.history || [])].reverse().map((r) => {
    const diff = r.diff == null ? "" : r.diff > 0 ? `<span class="up">▲ ${won(r.diff)}</span>`
      : r.diff < 0 ? `<span class="down">▼ ${won(-r.diff)}</span>` : "-";
    const wx = r.max_temp == null ? "" : `${r.rain_mm ? `비 ${r.rain_mm}mm · ` : ""}${Math.round(r.min_temp)}~${Math.round(r.max_temp)}℃`;
    const tags = (r.holiday ? `<span class="tag hol">${esc(r.holiday)}</span>` : "")
      + (r.events.length ? `<span class="tag" title="${esc(r.events.join(", "))}">행사 ${r.events.length}</span>` : "");
    return `<tr><td>${mmdd(r.date)}${tags}</td><td class="price">${won(r.kg_price)}</td><td>${diff}</td><td>${wx}</td></tr>`;
  }).join("") || `<tr><td colspan="4">최근 거래 기록이 없어요</td></tr>`;
  renderForecast(d.forecast);
}

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
    <span class="badge">다음 7일 예측 · 믿을 만한 정도 ${esc(f.confidence)}</span>
    <p class="dir ${cls(f.expected_change_pct, 2)}">${esc(v.text)}</p>
    <p class="muted">예상 ${won(f.expected_kg_price_range?.[0])} ~ ${won(f.expected_kg_price_range?.[1])} /kg (${pct(f.range_pct[0])} ~ ${pct(f.range_pct[1])})</p>
    <p class="tip">${esc(f.suggestion)}${g ? ` · <a href="${esc(g.url)}" target="_blank" rel="noopener" style="color:var(--accent)">식봄 ${won(g.sale_price)} 상품 보기 →</a>` : ""}</p>
    ${f.factors.map((x) => {
      const w = (Math.abs(x.effect_pct) / maxAbs) * 50;
      const style = x.effect_pct >= 0 ? `left:50%;width:${w}%;background:var(--up)` : `right:50%;width:${w}%;background:var(--down)`;
      return `<div class="factor"><span>${esc(x.factor)}</span><span class="bar"><i style="${style}"></i></span>
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
// 영수증으로 원가율 (사진 → 읽기 → 확인 · 수정 → 저장 → 원가율)
// ---------------------------------------------------------------
const DEMO_RECEIPTS = [
  ["receipt_1104_mart_up", "11/4 값 오른 마트 영수증"], ["receipt_1012_statement", "10/12 도매상 명세서"], ["receipt_1019_photo_tilted", "10/19 기울어진 사진"],
  ["receipt_1026_mart", "10/26 마트 영수증"], ["receipt_1102_handwritten", "11/2 손글씨 영수증"],
];
let receipt = null;   // { image, mime, data(읽은 결과) }

async function sendJSON(url, method, body) {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body && JSON.stringify(body) });
  const out = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(out.detail || "잠시 뒤 다시 해 주세요");
  return out;
}

// 사진을 긴 쪽 1600px JPEG로 줄임 (요청 크기 제한 · 읽기 속도)
function shrink(blob) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, 1600 / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      const g = c.getContext("2d");
      g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
      g.drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(img.src);
      resolve(c.toDataURL("image/jpeg", 0.88));
    };
    img.onerror = () => reject(new Error("사진을 열지 못했어요"));
    img.src = URL.createObjectURL(blob);
  });
}

async function readReceipt(blob) {
  const box = $("#receiptResult");
  $("#receiptStart").hidden = true;
  box.innerHTML = `<div class="reading"><div class="spinner"></div><b>살피가 영수증을 읽는 중이에요</b><p class="muted">10~30초쯤 걸려요</p></div>`;
  try {
    const image = await shrink(blob);
    receipt = { image, mime: "image/jpeg" };
    receipt.data = await sendJSON("/api/receipt/read", "POST", { image, mime: "image/jpeg" });
    renderReceiptEdit();
  } catch (e) {
    box.innerHTML = `<p class="rc-warn">${esc(e.message)}</p><button class="btn" id="receiptAgain">다시 하기</button>`;
    $("#receiptAgain").onclick = resetReceipt;
  }
}

function resetReceipt() {
  receipt = null;
  $("#receiptResult").innerHTML = "";
  $("#receiptStart").hidden = false;
  $("#receiptFile").value = "";
}

function renderReceiptEdit() {
  const d = receipt.data;
  const opts = (sel) => `<option value="">재료 아님</option>` + d.items_list.map((i) =>
    `<option value="${i.id}" ${i.id === sel ? "selected" : ""}>${esc(i.name)}</option>`).join("");
  const unitOf = (id) => d.items_list.find((i) => i.id === +id)?.base_unit || "";
  $("#receiptResult").innerHTML = `
    <div class="receipt-edit">
      <img class="receipt-thumb" src="${receipt.image}" alt="올린 영수증">
      <div>
        <span class="badge">살피가 읽은 내용 · 틀린 곳은 고쳐 주세요</span>
        <div class="receipt-meta">
          <label>날짜 <input type="date" id="rcDate" value="${esc(d.date || "")}"></label>
          <label>판매처 <input id="rcSupplier" value="${esc(d.supplier || "")}"></label>
        </div>
        ${d.total_matches ? "" : `<p class="rc-warn">줄 금액을 더하면 ${won(d.line_sum)}인데 합계는 ${won(d.total)}이에요. 빠진 줄이 없는지 봐 주세요.</p>`}
      </div>
    </div>
    <table class="price-table edit-table">
      <thead><tr><th>영수증 품목</th><th>재료</th><th>양</th><th>금액(원)</th><th></th></tr></thead>
      <tbody>${d.items.map((x, i) => `<tr data-i="${i}">
        <td><input class="rc-name" value="${esc(x.raw_name)}"></td>
        <td><select class="rc-item">${opts(x.item_id)}</select></td>
        <td class="qty-cell"><input class="rc-qty" type="number" step="0.1" min="0" value="${x.qty_base ?? ""}"><span class="rc-unit">${esc(x.base_unit || "")}</span></td>
        <td><input class="rc-amount" type="number" min="0" value="${x.amount ?? ""}"></td>
        <td><button class="rc-del" title="이 줄 빼기">×</button></td></tr>`).join("")}</tbody>
    </table>
    <p class="muted small">양은 재료 기준 단위(kg · 모)로 바꾼 전체 양이에요. 예: 깐양파 15kg 1망 → 15</p>
    <div class="receipt-actions"><button class="btn" id="rcCancel">취소</button><button class="btn primary" id="rcSave">확인했어요, 저장</button></div>`;
  const tb = $("#receiptResult tbody");
  tb.onchange = (e) => {
    if (e.target.classList.contains("rc-item")) e.target.closest("tr").querySelector(".rc-unit").textContent = unitOf(e.target.value);
  };
  tb.onclick = (e) => { if (e.target.classList.contains("rc-del")) e.target.closest("tr").remove(); };
  $("#rcCancel").onclick = resetReceipt;
  $("#rcSave").onclick = saveReceipt;
}

async function saveReceipt() {
  const btn = $("#rcSave");
  const items = [...document.querySelectorAll("#receiptResult tbody tr")].map((tr) => {
    const orig = receipt.data.items[+tr.dataset.i];
    const itemId = tr.querySelector(".rc-item").value;
    return { raw_name: tr.querySelector(".rc-name").value.trim(), qty: orig.qty, item_id: itemId ? +itemId : null,
             qty_base: parseFloat(tr.querySelector(".rc-qty").value) || null, amount: parseFloat(tr.querySelector(".rc-amount").value) || null };
  });
  btn.disabled = true; btn.textContent = "저장하는 중";
  try {
    const r = await sendJSON("/api/receipt/save", "POST", { image: receipt.image, mime: receipt.mime,
      date: $("#rcDate").value || null, supplier: $("#rcSupplier").value || null, items });
    resetReceipt();
    $("#receiptResult").innerHTML = `<p class="ok">${mmdd(r.date)} 영수증 ${r.saved_items}줄을 저장했어요. 오른쪽 원가율이 새로 계산됐어요.</p>`;
    renderCosts(r, true);
    loadCosts(false);
  } catch (e) {
    btn.disabled = false; btn.textContent = "확인했어요, 저장";
    alert(e.message);
  }
}

const ratioCls = (v) => (v == null ? "" : v > 35 ? "up" : v > 30 ? "warnc" : "down");

function renderCosts(r, withChange) {
  const rows = r.menus.map((m) => {
    const ch = withChange && m.change_pt ? ` <small class="${m.change_pt > 0 ? "up" : "down"}">(${m.change_pt > 0 ? "+" : ""}${m.change_pt}%p)</small>` : "";
    return `<tr><td>${esc(m.menu)}</td><td>${won(m.price)}</td><td>${won(m.cost_per_serving)}</td>
      <td class="price ${ratioCls(m.cost_ratio_pct)}">${m.cost_ratio_pct ?? "-"}%${ch}</td><td>${won(m.margin)}</td></tr>
      ${m.tips.length ? `<tr class="tips"><td colspan="5">${m.tips.map((t) => `<span>${esc(t)}</span>`).join("")}</td></tr>` : ""}`;
  }).join("");
  const keep = $("#receiptList")?.innerHTML || "";
  $("#costCard").innerHTML = `
    <span class="badge">시연용 가게 · 최근 영수증 단가 기준 · 목표 원가율 ${r.target_ratio_pct}%</span>
    <table class="price-table cost-table">
      <thead><tr><th>메뉴</th><th>판매가</th><th>1인분 재료비</th><th>원가율</th><th>남는 돈</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="muted small">${esc(r.method)}. 시연용 레시피는 주재료만 들어 있어 실제보다 원가율이 낮게 나와요.</p>
    <div id="receiptList">${r.receipts ? receiptList(r.receipts) : keep}</div>`;
}

function receiptList(list) {
  return `<h3 class="sub-h">최근 영수증</h3><ul class="ctx-list receipt-list">${list.map((p) => `<li>
    <span>${mmdd(p.purchased_on)} · ${esc(p.supplier || "판매처 모름")} · ${p.items}줄 · ${won(p.total_amount)}</span>
    ${p.source === "ocr" ? `<button class="rc-remove" data-id="${p.id}">지우기</button>` : `<small>시연 기본 데이터</small>`}</li>`).join("")}</ul>`;
}

async function loadCosts(full = true) {
  try {
    const r = await getJSON("/api/costs");
    if (full) renderCosts(r, false);
    else $("#receiptList").innerHTML = receiptList(r.receipts);
  } catch (e) {
    if (full) $("#costCard").innerHTML = `<p class="muted">원가율을 불러오지 못했어요. ${esc(e.message)}</p>`;
  }
}

$("#demoReceipts").innerHTML = DEMO_RECEIPTS.map(([f, label]) =>
  `<button data-f="${f}"><img src="/receipts_demo/${f}.png" alt="" loading="lazy"><span>${label}</span></button>`).join("");
$("#demoReceipts").onclick = async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  readReceipt(await (await fetch(`/receipts_demo/${b.dataset.f}.png`)).blob());
};
$("#receiptFile").onchange = (e) => { if (e.target.files[0]) readReceipt(e.target.files[0]); };
$("#costCard").onclick = async (e) => {
  const b = e.target.closest(".rc-remove");
  if (!b || !confirm("이 영수증을 지울까요? 원가율이 다시 계산돼요.")) return;
  try { renderCosts(await sendJSON(`/api/receipt/${b.dataset.id}`, "DELETE"), false); loadCosts(false); }
  catch (err) { alert(err.message); }
};

// ---------------------------------------------------------------
// 식봄 상품 목록
// ---------------------------------------------------------------
let filterItem = "전체";
async function loadProducts() {
  try {
    shop = (await getJSON("/api/products")).items;
  } catch (e) {
    shop = {};
  }
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
  $("#productGrid").innerHTML = cards.map(({ item, g }) => {
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
  }).join("");
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

loadOverview();
loadProducts();
loadContext();
loadDemand();
loadCosts();
if (location.hash === "#chat") openChat();   // 주소 끝에 #chat 을 붙이면 채팅창이 열린 채로 시작
if (location.hash === "#rise") setTimeout(() => goSlide(1, "instant"), 4000);   // 시연용: 첫 야채 대시보드부터
