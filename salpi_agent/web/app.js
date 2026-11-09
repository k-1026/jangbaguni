// 살피 시세 대시보드 화면 동작
const $ = (s) => document.querySelector(s);
const won = (v) => (v == null ? "-" : `${Math.round(v).toLocaleString("ko-KR")}원`);
const pct = (v) => (v == null ? "-" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`);
const cls = (v, band = 0) => (v == null ? "" : v > band ? "up" : v < -band ? "down" : "");
const mmdd = (d) => `${d.slice(5, 7)}.${d.slice(8, 10)}`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

let overview = [];          // 재료별 시세 · 날짜별 기록 · 예측 (/api/overview 한 번으로 받음)
const charts = {};          // 슬라이드별 차트 (보이는 슬라이드만 그림)
const ITEM = new URLSearchParams(location.search).get("item");   // 재료 전용 페이지(/?item=토마토)의 재료 이름
if (ITEM) {
  document.body.classList.add("item-view");
  $("#itemPage").hidden = false;
}
// 나의 가게 페이지(/?page=store): 내일 준비 · 영수증 분석 · 메뉴별 원가율은 사장님 로그인 시에만
// 로그인(카카오)은 아직 없어서 시연에서는 기본 계정으로 로그인한 것으로 봄
const SIGNED_IN = true;
const STORE_VIEW = !ITEM && SIGNED_IN && new URLSearchParams(location.search).get("page") === "store";
if (STORE_VIEW) document.body.classList.add("store-view");
$("#storeBtn").hidden = !SIGNED_IN;

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
  if (ITEM) { renderItemPage(); deliverAlerts(); return; }

  const up = overview.filter((r) => (r.wholesale_change_pct ?? 0) >= 3);
  const down = overview.filter((r) => (r.wholesale_change_pct ?? 0) <= -3);
  const week = (r) => r.wholesale_change_pct;
  summaryLists = {
    up: [...up].sort((a, b) => week(b) - week(a)).map((r) => [r.item, week(r)]),
    down: [...down].sort((a, b) => week(a) - week(b)).map((r) => [r.item, week(r)]),
  };
  const chip = (key, tone, count, label) => `<button class="chip ${tone}" type="button" data-list="${key}" aria-expanded="false" aria-controls="summaryList-${key}"><b>${count}개</b><small>${label}</small></button>`;
  $("#summary").innerHTML = `
    ${chip("up", "up", up.length, "지난주보다 <em>오른</em> 야채")}
    ${chip("down", "down", down.length, "지난주보다 <em>내린</em> 야채")}`;

  renderSlides();
  onSlideChange();
  deliverAlerts();
}

// 요약 칸을 누르면 해당 야채 목록을 펼침 · 다시 누르면 접음 · 야채를 누르면 그 대시보드에서 멈춤
let summaryLists = {};
// 다른 칸으로 바꿀 때는 지금 목록이 접히는 동시에 새 목록이 펼쳐짐 (목록마다 칸을 따로 만들고, 접힌 칸은 지움)
function openSummaryList(key) {
  const box = document.createElement("div");
  box.className = "summary-list";
  box.id = `summaryList-${key}`;
  box.innerHTML = summaryHTML(summaryLists[key] || []);
  $("#summary").appendChild(box);
  box.offsetHeight;   // 접힌 상태를 먼저 그려야 펼쳐지는 움직임이 보임
  box.classList.add("open");
}
function closeSummaryLists() {
  $("#summary").querySelectorAll(".summary-list.open").forEach((box) => {
    box.classList.remove("open");
    box.inert = true;
    box.setAttribute("aria-hidden", "true");
    setTimeout(() => box.remove(), 500);   // style.css 접힘 시간(.45초)이 지난 뒤
  });
}
$("#summary").onclick = (e) => {
  const item = e.target.closest(".summary-list button[data-item]");
  if (item) return showItem(item.dataset.item);
  const b = e.target.closest("button.chip");
  if (!b) return;
  if (b.dataset.item) return showItem(b.dataset.item);
  const open = b.getAttribute("aria-expanded") !== "true";
  $("#summary").querySelectorAll("[aria-expanded]").forEach((c) => c.setAttribute("aria-expanded", "false"));
  b.setAttribute("aria-expanded", open);
  closeSummaryLists();
  if (open) openSummaryList(b.dataset.list);
};
// 두 겹으로 감쌈: 바깥은 높이 0 → 실제 높이로 움직이고(접히는 목록과 펼치는 목록 높이 합이 넘치지 않게), 안쪽은 버튼 그림자 여백
const summaryHTML = (list) => `<div class="summary-clip"><div class="summary-inner">${list.map(([item, v]) =>
  `<button type="button" data-item="${esc(item)}"><b>${esc(item)}</b> <span class="${v > 0 ? "rise" : "fall"}">${pct(v)}</span></button>`).join("")
  || "<p>해당하는 야채가 없어요</p>"}</div></div>`;


// 고른 야채의 대시보드로 가서 자동 넘김을 멈춤
function showItem(name) {
  setPaused(true);
  goSlide(slides().findIndex((s) => s.dataset.item === name));
  $(".hero-board").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// 예측 근거를 사장님 말로 한 줄만: 판단과 같은 방향에서 가장 큰 이유
function plainReason(factors, kind) {
  const sign = { up: 1, down: -1 }[kind];
  if (!sign) return "";
  const top = (factors || []).filter((x) => x.effect_pct * sign > 0).sort((a, b) => Math.abs(b.effect_pct) - Math.abs(a.effect_pct))[0];
  if (!top) return "";
  if (top.factor.startsWith("최근 2주")) return `최근 2주 동안 ${sign > 0 ? "올랐어요" : "내렸어요"}`;
  if (top.factor.startsWith("도매시장")) return `시장에 들어오는 양이 ${sign > 0 ? "줄었어요" : "늘었어요"}`;
  if (top.factor.startsWith("날씨")) return "최근 날씨 영향이 있어요";
  if (top.factor.includes("공휴일")) return "공휴일을 앞두고 있어요";
  return "대구 행사가 많아요";
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
      <p class="overview-note">다음 주 <b class="up">오를 가능성 ${overview.filter((r) => expOf(r) >= 2).length}개</b> ·
        <b>유지 ${overview.filter((r) => Math.abs(expOf(r)) < 2).length}개</b> ·
        <b class="down">떨어질 가능성 ${overview.filter((r) => expOf(r) <= -2).length}개</b></p>
    </article>` + slideOrder().map(itemSlide).join("");
}

// 재료 한 장: 메인 슬라이드와 재료 페이지가 함께 씀
// 포즈별 치수 (원본 그림 높이 240px 기준, 화면에서는 좌우반전)
// body: 머리 꼭대기~발끝 길이 (머리 위 시계 · 경광등은 뺌) → 화면에서 미어캣 키가 모두 같게 그림 크기를 맞춤
// foot: 그림에서 가장 아래 닿는 곳 (쇼핑백 살피는 발보다 낮은 가방 밑을 맞춰 대시보드 밖으로 나가지 않게) · my: 입 높이 · side: 입 높이에서 몸이 가장 왼쪽으로 나온 곳
// → 말풍선은 몸 바깥 왼쪽에 두고 꼬리만 입 쪽을 가리킴 (살피가 말풍선을 가리지 않게)
const POSE_SIZE = {
  alert_down: { body: 206, foot: 238, my: 65, side: 192 }, alert_flat1: { body: 182, foot: 238, my: 115, side: 150 },
  alert_flat2: { body: 230, foot: 238, my: 98, side: 170 }, alert_rise1: { body: 178, foot: 238, my: 122, side: 168 },
  alert_rise2: { body: 226, foot: 238, my: 82, side: 240 },
};
const poseVars = (p) => Object.entries(POSE_SIZE[p]).map(([k, v]) => `--${k}:${v}`).join(";");

function itemSlide(r, idx) {
  const f = r.forecast || {};
  const v = verdict(f);
  const why = plainReason(f.factors, v.kind);
  // 오름: 경광등 살피(2 · 4번째 포즈 번갈아) · 유지: 알람시계 살피(1 · 3번째) · 내림: 쇼핑백 살피(6번째)
  const pose = v.kind === "down" ? "alert_down" : `alert_${v.kind === "up" ? "rise" : "flat"}${(idx % 2) + 1}`;
  const say = { up: "미리 사두는 게 좋을 것 같아요.", flat: "평소대로 구매하셔도 좋아요", down: "급하지 않으면 나중에 사셔도 좋아요" }[v.kind];
  return `
<article class="slide card" data-item="${esc(r.item)}">
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
    <div class="fc-text">
      <span class="verdict">${v.text}</span>
      <span class="range">예상 ${won(f.expected_kg_price_range?.[0])} ~ ${won(f.expected_kg_price_range?.[1])}/kg${why ? ` · ${why}` : ""}</span>
    </div>
    <div class="advice" style="${poseVars(pose)}"><span class="say">${say}</span><img class="pose" src="/static/img/${pose}.png" alt=""></div>
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
let autoTimer = null, hovering = false, paused = false;
function restartAuto() {
  clearInterval(autoTimer);
  if (paused) return;
  autoTimer = setInterval(() => { if (!hovering && !document.hidden && slides().length > 1) goSlide(cur + 1); }, AUTO_MS);
}
$(".hero-board").addEventListener("mouseenter", () => { hovering = true; });
$(".hero-board").addEventListener("mouseleave", () => { hovering = false; });
if (!ITEM) restartAuto();

// 일시정지 버튼: 누르면 자동 넘김을 멈추고 다시 누르면 이어서 넘김
function setPaused(on) {
  paused = on;
  const b = $("#pauseSlide");
  b.setAttribute("aria-pressed", on);
  b.setAttribute("aria-label", on ? "자동 넘김 다시 시작" : "자동 넘김 멈춤");
  b.title = on ? "다시 시작" : "멈춤";
  b.innerHTML = on ? '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 1.5v9l7.5-4.5z"/></svg>'
    : '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 1.5h2.5v9H2.5zM7 1.5h2.5v9H7z"/></svg>';
  restartAuto();
}
$("#pauseSlide").onclick = () => setPaused(!paused);

function drawSlideChart(i) {
  const el = slides()[i];
  if (!el || charts[i]) return;
  const item = el.dataset.item;
  charts[i] = item ? drawItemChart(el.querySelector("canvas"), byItem(item)) : drawOverviewChart(el.querySelector("canvas"));
}

function drawOverviewChart(canvas) {
  const rows = [...overview].filter((r) => r.wholesale_change_pct != null).sort((a, b) => b.wholesale_change_pct - a.wholesale_change_pct);
  // 이웃한 야채 이름끼리 겹치지 않는 글자 크기: 막대 한 칸 너비 ÷ (가장 긴 이웃 두 이름의 평균 글자 수 + 띄움 0.5자)
  const longestPair = Math.max(...rows.slice(1).map((r, i) => (r.item.length + rows[i].item.length) / 2));
  const labelSize = (c) => Math.min(14, Math.floor((c.chart.width - 48) / rows.length / (longestPair + 0.5)));
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
        x: { grid: { display: false }, ticks: { color: "#1F2622", font: (c) => ({ size: labelSize(c), weight: "700" }), autoSkip: false, maxRotation: 0 } },
        y: { grid: { color: "#F0EDE6" }, ticks: { color: "#8A918C", font: { size: 11 }, callback: (v) => `${v}%` } },
      },
      onClick: (_e, els) => { if (els.length) showItem(rows[els[0].index].item); },
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
    <a class="item-shop" href="${esc(r.foodspring_url || "https://www.foodspring.co.kr")}" target="_blank" rel="noopener" title="식봄에서 ${esc(r.item)} 사기">식자재 바로가기 →</a>`;
  $("#itemBody").hidden = false;
  $("#itemDash").innerHTML = itemSlide(r, 0);
  drawItemChart($("#itemDash canvas"), r);
  renderDetail(r.item);
  renderItemGoods();
}

function renderItemGoods() {
  const r = byItem(ITEM);
  if (!r || !shopLoaded) return;
  const goods = (shop[ITEM] || []).slice(0, 8);
  $("#itemGoodsWrap").hidden = !goods.length;   // 상품을 못 받으면 위 구매 버튼만 남김
  $("#itemGoods").innerHTML = goods.map((g) => productCard({ item: ITEM, g })).join("");
}

function renderDetail(name) {
  const d = byItem(name);
  if (!d) return;
  boardItem = d;
  renderBoard();
  renderForecast(d.forecast, d.history);
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
      <button class="board-toggle" type="button" aria-label="증감 표시 단위 바꾸기 (지금 ${boardMode === "won" ? "등락액 원" : "등락률 %"})">
        <span class="${boardMode === "won" ? "on" : ""}">등락액 원</span>
        <span class="${boardMode === "pct" ? "on" : ""}">등락률 %</span>
      </button>
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
// 토글 아무 곳이나 누르면 원 ↔ % 전환
$("#priceBoard").addEventListener("click", (e) => {
  if (!e.target.closest(".board-toggle")) return;
  boardMode = boardMode === "won" ? "pct" : "won";
  renderBoard();
});

function renderForecast(f, history = []) {
  if (!f || f.error) { $("#forecastCard").innerHTML = ""; return; }
  const v = verdict(f);
  const big = (x) => Math.abs(x.effect_pct) >= 0.1;
  const moved = f.factors.filter(big).sort((a, b) => Math.abs(b.effect_pct) - Math.abs(a.effect_pct));
  const still = f.factors.filter((x) => !big(x));
  const [lo, hi] = f.expected_kg_price_range || [];
  $("#forecastCard").className = `card forecast-card fc-${v.kind}`;   // up · down 이름은 전체 글자색 규칙과 겹쳐서 fc- 를 붙임
  $("#forecastCard").innerHTML = `
    <div class="fc-summary">
      <span class="fc-label">다음 7일 예측</span>
      <p class="dir">${esc(v.text)}</p>
      <p class="tip">${esc(f.suggestion)}</p>
      ${fcSpark(history, lo, hi)}
      <div class="fc-range">
        <div><small>지금 (kg당)</small><b>${won(f.base_kg_price)}</b></div>
        <i aria-hidden="true">→</i>
        <div><small>7일 뒤 예상</small><b>${won(lo)} ~ ${won(hi)}</b></div>
      </div>
    </div>
    <div class="fc-reasons">
      <h4>이렇게 본 이유</h4>
      <div class="reason-grid">${moved.map((x) => `<div class="reason ${x.effect_pct > 0 ? "r-up" : "r-down"}">
        <span class="reason-icon" aria-hidden="true">${x.effect_pct > 0 ? "▲" : "▼"}</span>
        <div><b>${esc(factorName(x.factor))}</b><small>${esc(x.detail)}</small></div>
        <strong>${pct(x.effect_pct)}</strong>
      </div>`).join("") || `<p class="muted">뚜렷하게 오르거나 내릴 이유가 없어요</p>`}</div>
      ${still.length ? `<p class="reason-still"><span>영향 없음</span>${still.map((x) => `<em title="${esc(x.detail)}">${esc(factorName(x.factor))}</em>`).join("")}</p>` : ""}
      ${monthRange(history, f.base_kg_price)}
    </div>`;
}

// 최근 2주(거래일) 시세 선 + 오늘에서 7일 뒤 예상 범위(부채꼴)
function fcSpark(history, lo, hi) {
  const rows = history.slice(-14).filter((r) => r.kg_price > 0);
  if (rows.length < 4 || lo == null || hi == null) return "";
  const vals = [...rows.map((r) => r.kg_price), lo, hi];
  const min = Math.min(...vals), max = Math.max(...vals), pad = (max - min) * 0.12 || 1;
  const W = 300, H = 100, PAST = 200;   // 앞 200칸은 지난 2주, 뒤 100칸은 다음 7일
  const y = (v) => (H - ((v - (min - pad)) / (max - min + 2 * pad)) * H).toFixed(1);
  const x = (i) => ((i / (rows.length - 1)) * PAST).toFixed(1);
  const line = rows.map((r, i) => `${x(i)},${y(r.kg_price)}`).join(" ");
  const last = rows.at(-1).kg_price, mid = (lo + hi) / 2;
  return `<div class="fc-spark">
      <p class="fc-spark-title">최근 2주 흐름과 7일 뒤 예상</p>
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="최근 2주 ${won(rows[0].kg_price)}에서 오늘 ${won(last)}, 7일 뒤 ${won(lo)} ~ ${won(hi)} 예상">
        <polygon class="band" points="${PAST},${y(last)} ${W},${y(hi)} ${W},${y(lo)}"/>
        <line class="today" x1="${PAST}" x2="${PAST}" y1="0" y2="${H}"/>
        <polyline class="past" points="${line}"/>
        <line class="next" x1="${PAST}" y1="${y(last)}" x2="${W}" y2="${y(mid)}"/>
      </svg>
      <p class="fc-spark-axis"><span>${mmdd(rows[0].date)}</span><span class="t">오늘</span><span>7일 뒤</span></p>
    </div>`;
}

// 최근 한 달(거래일) 최저 · 평균 · 최고와 지금 가격이 그 사이 어디쯤인지
function monthRange(history, now) {
  const prices = history.slice(-22).map((r) => r.kg_price).filter((v) => v > 0);
  if (prices.length < 5 || !now) return "";
  const lo = Math.min(...prices), hi = Math.max(...prices), avg = prices.reduce((a, v) => a + v, 0) / prices.length;
  const at = hi === lo ? 50 : ((now - lo) / (hi - lo)) * 100;
  const where = at >= 70 ? "비싼 편" : at <= 30 ? "싼 편" : "보통";
  const vsAvg = ((now - avg) / avg) * 100;
  const avgAt = hi === lo ? 50 : Math.max(28, Math.min(72, ((avg - lo) / (hi - lo)) * 100));   // 양끝 글자와 겹치지 않게
  return `<div class="month-range">
      <h4>최근 한 달 시세 위치 <small>최근 ${prices.length}거래일</small></h4>
      <p class="month-say">지금 가격은 한 달 중 <b class="m-${at >= 70 ? "high" : at <= 30 ? "low" : "mid"}">${where}</b>이에요 · 평균보다 ${pct(vsAvg)}</p>
      <div class="month-bar" role="img" aria-label="한 달 최저 ${won(lo)}, 최고 ${won(hi)} 사이에서 지금 ${won(now)}">
        <b class="avg-tick" style="left:${avgAt}%"></b>
        <i style="left:${Math.max(0, Math.min(100, at))}%"><em style="transform:translateX(-${Math.round(Math.max(0, Math.min(100, at)))}%)">지금 ${won(now)}</em></i>
      </div>
      <div class="month-scale">
        <span class="lo"><small>한 달 최저</small>${won(lo)}</span>
        <span class="avg" style="left:${avgAt}%"><small>평균</small>${won(Math.round(avg))}</span>
        <span class="hi"><small>한 달 최고</small>${won(hi)}</span>
      </div>
    </div>`;
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

const weekday = (s) => "일월화수목금토"[new Date(`${s}T00:00:00`).getDay()];

// 내일 예상이 평소(최근 14일 평균)와 얼마나 다른지 한눈에 (3% 안쪽은 비슷하다고 봄)
function usualChip(predicted, usual) {
  const diff = predicted - usual;
  if (Math.abs(diff) < usual * 0.03) return `<span class="demand-chip">평소 수준</span>`;
  return diff > 0
    ? `<span class="demand-chip up">평소 +${diff}</span>`
    : `<span class="demand-chip down">평소 −${-diff}</span>`;
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
  // 메뉴끼리 그릇 수를 막대 높이로 비교할 수 있게 같은 눈금을 씀 (위 여백은 숫자 자리)
  const max = Math.max(...d.menus.flatMap((m) => [m.predicted, ...m.recent.map((x) => x.qty)]), 1) * 1.2;
  $("#storeBasis").textContent = `판매 기록 ${mmdd(d.last_sales_date)}까지`;
  $("#storeBasis").title = d.method;
  $("#menuForecast").innerHTML = `
    <div class="demand-top">
      <span class="badge">내일 ${day}${d.is_holiday ? " · 공휴일" : ""} 예상 판매</span>
      <p class="demand-total">${d.is_open ? `모두 <b>${d.total_predicted}그릇</b> 팔릴 것 같아요` : "내일은 가게 쉬는 날이에요"}</p>
      <button class="order-all demand-all" type="button">모두 보기</button>
    </div>
    <div class="demand-grid">${d.menus.map((m) => {
      const pct = (v) => (v / max) * 100;
      const usual = Math.round(m.recent.reduce((s, x) => s + x.qty, 0) / (m.recent.length || 1));
      const bars = m.recent.map((x) => {
        const wd = weekday(x.date);
        return `<span title="${mmdd(x.date)}(${wd}) ${x.qty}그릇"><i class="${wd === d.target_weekday ? "same" : ""}" style="height:${pct(x.qty)}%"></i></span>`;
      }).join("");
      return `<div class="demand-item">
        <button class="order-row" type="button" aria-expanded="false" aria-controls="demand-${m.menu_id}">
          <span class="order-name">${esc(m.menu)}${d.is_open ? usualChip(m.predicted, usual) : ""}</span>
          <b>${m.predicted}그릇</b>
          <i class="order-arrow" aria-hidden="true"></i>
        </button>
        <div class="demand-detail" id="demand-${m.menu_id}" hidden>
          <div class="demand-chart">
            <p class="demand-legend">
              <span><i></i>최근 판매</span>
              <span><i class="same"></i>지난 ${d.target_weekday}요일</span>
              <span><i class="next"></i>내일</span>
              <span><i class="usual"></i>평소 ${usual}</span>
            </p>
            <div class="spark" role="img" aria-label="${esc(m.menu)} 평소 ${usual}그릇, 내일 예상 ${m.predicted}그릇">
              ${bars}<span title="내일 예상 ${m.predicted}그릇 (${m.range[0]} ~ ${m.range[1]})"><i class="next" style="height:${pct(m.predicted)}%"></i></span>
              <div class="spark-usual" style="bottom:${pct(usual)}%"></div>
            </div>
          </div>
          <p>${esc(demandReason(m.factors))} · 예상 ${m.range[0]} ~ ${m.range[1]}그릇</p>
        </div>
      </div>`;
    }).join("")}</div>`;
  const until = d.next_delivery_date ? `${mmdd(d.next_delivery_date)} 입고까지` : "다음 입고까지";
  $("#orderCard").innerHTML = `
    <div class="order-head">
      <h3>오늘 주문 <b>${d.items.filter((i) => i.order_qty > 0).length}개</b></h3>
      <button class="order-all" type="button">근거 모두 보기</button>
    </div>
    ${orderGroups(d.items).map((g) => `<section class="order-group ${g.key}">
      <h4><i></i>${g.title}${g.note ? `<small>${g.note}</small>` : ""}</h4>
      <div class="order-grid">${g.items.map((i) => orderItem(i, g.key, until)).join("")}</div>
    </section>`).join("")}
    <p class="order-foot">주문량 = 입고까지 필요량 + 여유 10% − 재고</p>`;
}

// 표의 판단을 사장님이 움직일 순서로 묶음 (빈 묶음은 숨김)
function orderGroups(items) {
  const rising = (i) => i.decision === "지금 사기" && i.price_change_pct >= 2;
  return [
    { key: "first", title: "먼저 사기", note: "시세가 오를 수 있어요", items: items.filter(rising) },
    { key: "normal", title: "평소대로 주문", items: items.filter((i) => i.decision === "지금 사기" && !rising(i)) },
    { key: "split", title: "나눠 사기", note: "시세가 내릴 수 있어요", items: items.filter((i) => i.decision === "나눠 사기") },
    { key: "wait", title: "이번엔 안 사도 돼요", note: "재고가 충분해요", items: items.filter((i) => i.decision === "기다리기") },
  ].filter((g) => g.items.length);
}

function orderItem(i, key, until) {
  const change = i.price_change_pct;
  const note = key === "first" || key === "split"
    ? `<small>다음 7일 ${change > 0 ? "+" : "−"}${Math.abs(Math.round(change))}%</small>` : "";
  return `<div class="order-item">
    <button class="order-row" type="button" aria-expanded="false" aria-controls="order-${i.item_id}">
      <span class="order-name">${esc(i.item)}${note}</span>
      <b>${i.order_qty > 0 ? qty(i.order_qty, i.unit) : "-"}</b>
      <i class="order-arrow" aria-hidden="true"></i>
    </button>
    <div class="order-detail" id="order-${i.item_id}" hidden>
      <dl>
        <div><dt>내일 필요</dt><dd>${qty(i.need_target, i.unit)}</dd></div>
        <div><dt>${until}</dt><dd>${qty(i.need_until_delivery, i.unit)}</dd></div>
        <div><dt>재고</dt><dd>${qty(i.on_hand, i.unit)}</dd></div>
      </dl>
      <p>${esc(i.reason)}</p>
    </div>
  </div>`;
}

const setOpen = (b, open) => { b.setAttribute("aria-expanded", open); b.nextElementSibling.hidden = !open; };

// 메뉴를 누르면 지난 판매 그래프를 펼침
// 맨 위 버튼은 메뉴 전체를 펴고 접음
$("#menuForecast").onclick = (e) => {
  const rows = [...$("#menuForecast").querySelectorAll(".order-row")];
  const row = e.target.closest(".order-row");
  if (row) setOpen(row, row.getAttribute("aria-expanded") !== "true");
  else if (e.target.closest(".demand-all")) {
    const open = rows.some((b) => b.getAttribute("aria-expanded") !== "true");
    rows.forEach((b) => setOpen(b, open));
  } else return;
  $(".demand-all").textContent = rows.every((b) => b.getAttribute("aria-expanded") === "true") ? "모두 접기" : "모두 보기";
};

// 재료를 누르면 계산 근거를 펼침 · 맨 위 버튼은 전체를 펴고 접음
$("#orderCard").onclick = (e) => {
  const rows = [...$("#orderCard").querySelectorAll(".order-row")];
  const row = e.target.closest(".order-row");
  if (row) setOpen(row, row.getAttribute("aria-expanded") !== "true");
  else if (e.target.closest(".order-all")) {
    const open = rows.some((b) => b.getAttribute("aria-expanded") !== "true");
    rows.forEach((b) => setOpen(b, open));
  } else return;
  $(".order-all").textContent = rows.every((b) => b.getAttribute("aria-expanded") === "true") ? "모두 접기" : "근거 모두 보기";
};

// ---------------------------------------------------------------
// 영수증으로 원가율 (사진 → 읽기 → 확인 · 수정 → 저장 → 원가율)
// ---------------------------------------------------------------
// 식봄 상품: 메인에는 보여 주지 않고 검색과 재료 페이지에서만 씀
let shop = {};             // 재료별 식봄 상품 (검색이 먼저 써도 오류 나지 않게 빈 값으로 시작)
let shopLoaded = false;
async function loadProducts() {
  try {
    shop = (await getJSON("/api/products")).items;
  } catch (e) {
    shop = {};
  }
  shopLoaded = true;
  if (ITEM) renderItemGoods();
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

const DEMO_RECEIPTS = [
  ["receipt_1104_mart_up", "11/4 값 오른 마트 영수증"], ["receipt_1012_statement", "10/12 도매상 명세서"], ["receipt_1019_photo_tilted", "10/19 기울어진 사진"],
  ["receipt_1026_mart", "10/26 마트 영수증"], ["receipt_1102_handwritten", "11/2 손글씨 영수증"],
];
let receipt = null;
const supplierName = (s) => (s || "판매처 모름").replace(/\s*\(시연용\)/g, "");   // { image, mime, data(읽은 결과) }

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
          <label>판매처 <input id="rcSupplier" value="${esc(d.supplier ? supplierName(d.supplier) : "")}"></label>
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
    $("#receiptResult").innerHTML = `<p class="ok">${mmdd(r.date)} 영수증 ${r.saved_items}줄을 저장했어요. 아래 메뉴별 원가율이 새로 계산됐어요.</p>`;
    renderCosts(r, true);
    loadCosts(false);
  } catch (e) {
    btn.disabled = false; btn.textContent = "확인했어요, 저장";
    alert(e.message);
  }
}

const ratioCls = (v) => (v == null ? "" : v > 35 ? "up" : v > 30 ? "warnc" : "down");

function renderCosts(r, withChange) {
  const T = r.target_ratio_pct;
  $("#costCard").innerHTML = `
    <p class="cost-guide">원가율은 <b>한 그릇 값에서 재료비가 차지하는 몫</b>이에요. 낮을수록 한 그릇 팔 때 남는 돈이 많아요.
      식당은 보통 <b>${T}% 아래</b>면 괜찮은 편이에요.</p>
    <div class="cost-cards">${r.menus.map((m) => {
      const v = m.cost_ratio_pct;
      const ch = withChange && m.change_pt
        ? `<small class="${m.change_pt > 0 ? "up" : "down"}">${m.change_pt > 0 ? "▲" : "▼"} ${Math.abs(m.change_pt)}%p</small>` : "";
      const tone = { up: "high", warnc: "tight", down: "ok" }[ratioCls(v)] || "";   // 높음 · 빠듯 · 충분
      return `<article class="cost-card ${tone}">
        <div class="cost-left">
          <b>${esc(m.menu)}</b>
          <strong>${v ?? "-"}<em>%</em></strong>
          <span class="cost-verdict">${esc(m.verdict)}</span>${ch}
        </div>
        <div class="cost-right">
          ${v == null ? "" : `<p class="ratio-label"><span><i class="k-cost"></i>재료비</span><span><i class="k-keep"></i>남는 돈</span><small>판매가 ${won(m.price)}을 100으로 볼 때</small></p>
          <div class="split-bar" role="img" aria-label="판매가 ${won(m.price)} 중 재료비 ${v}%, 남는 돈 ${+(100 - v).toFixed(1)}%">
            <i class="part-cost" style="width:${Math.max(4, Math.min(100, v))}%">${v}%</i>
            <i class="part-keep">남는 돈 ${+(100 - v).toFixed(1)}%</i>
          </div>`}
          <dl class="cost-nums">
            <div><dt>판매가</dt><dd>${won(m.price)}</dd></div>
            <div><dt>1인분 재료비</dt><dd>${won(m.cost_per_serving)}</dd></div>
            <div><dt>남는 돈</dt><dd>${won(m.margin)}</dd></div>
          </dl>
          ${m.tips.length ? `<ul class="cost-tips">${m.tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
        </div>
      </article>`;
    }).join("")}</div>
    <p class="muted small">${esc(r.method)}. 레시피에 주재료만 들어 있어 실제보다 원가율이 조금 낮게 나와요.</p>`;
}

function receiptList(list) {
  return `<h3 class="sub-h">최근 영수증</h3><ul class="ctx-list receipt-list">${list.map((p) => `<li>
    <button class="rc-open" data-rid="${p.id}" title="사진과 품목 보기">${mmdd(p.purchased_on)} · ${esc(supplierName(p.supplier))} · ${p.items}줄 · ${won(p.total_amount)} <i>보기 ›</i></button>
    ${p.source === "ocr" ? `<button class="rc-remove" data-id="${p.id}">지우기</button>` : `<small>기본 데이터</small>`}</li>`).join("")}</ul>`;
}

async function loadCosts(full = true) {
  try {
    const r = await getJSON("/api/costs");
    if (full) renderCosts(r, false);
    $("#receiptList").innerHTML = receiptList(r.receipts);
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

// 카메라로 찍기: 처음 한 번 브라우저가 카메라 권한을 물어봄 → 찍은 사진을 그대로 영수증 읽기로
// (폰은 뒤 카메라, 노트북은 앞 카메라. https 또는 내 컴퓨터 주소에서만 열림)
let camStream = null;
const CAM_GUIDE = `<ol class="cam-guide">
    <li><b>컴퓨터(크롬 · 엣지)</b>: 주소창 왼쪽 <b>자물쇠 · 설정 아이콘</b> → <b>카메라</b> → <b>허용</b> → 새로고침</li>
    <li><b>아이폰</b>: 설정 → Safari(또는 쓰는 브라우저) → <b>카메라</b> → <b>허용</b></li>
    <li><b>안드로이드</b>: 주소창 옆 <b>⋮</b> → 설정 → 사이트 설정 → <b>카메라</b> → 이 사이트 허용</li>
  </ol>`;
function camFail(msg, denied) {
  $("#cameraBody").innerHTML = `<p class="rc-warn">${msg}</p>
    ${denied ? `<p class="small">카메라를 쓰려면 권한을 켜 주세요.</p>${CAM_GUIDE}` : ""}
    <div class="camera-actions">
      <button class="btn" id="camRetry" type="button">다시 시도</button>
      <label class="btn primary" for="receiptFile" id="camGallery">사진첩에서 고르기</label>
    </div>`;
  $("#camRetry").onclick = openCamera;
  $("#camGallery").onclick = () => closeCamera();
}
async function askCamera() {
  return navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false });
}
async function openCamera() {
  $("#cameraModal").hidden = false;
  if (!navigator.mediaDevices?.getUserMedia) return camFail("이 브라우저에서는 카메라를 열 수 없어요. 사진첩에서 골라 주세요.");
  $("#cameraBody").innerHTML = `<div class="reading"><div class="spinner"></div><b>카메라를 여는 중이에요</b>
    <p class="muted small">'카메라 사용 허용' 창이 뜨면 <b>허용</b>을 눌러 주세요</p></div>`;
  try { camStream = await askCamera(); }
  catch (e) {
    const denied = e.name === "NotAllowedError" || e.name === "SecurityError";
    return camFail(denied ? "카메라 권한이 꺼져 있어요." : e.name === "NotFoundError" ? "연결된 카메라가 없어요." : "카메라를 열지 못했어요. 다른 앱이 카메라를 쓰고 있는지 확인해 주세요.", denied);
  }
  if ($("#cameraModal").hidden) return stopCamera();   // 여는 사이에 닫았으면
  $("#cameraBody").innerHTML = `<div class="cam-view"><video id="camVideo" autoplay playsinline muted></video><i class="cam-frame" aria-hidden="true"></i></div>
    <p class="muted small">영수증이 네모 안에 꽉 차게 맞추고 찍어 주세요</p>
    <div class="camera-actions"><button class="upload-btn" id="camShot" type="button">찍기</button></div>`;
  $("#camVideo").srcObject = camStream;
  $("#camShot").onclick = shootCamera;
}
function shootCamera() {
  const v = $("#camVideo");
  if (!v.videoWidth) return;
  const c = document.createElement("canvas");
  c.width = v.videoWidth; c.height = v.videoHeight;
  c.getContext("2d").drawImage(v, 0, 0);
  c.toBlob((b) => { closeCamera(); if (b) readReceipt(b); }, "image/jpeg", 0.92);
}
function stopCamera() { camStream?.getTracks().forEach((t) => t.stop()); camStream = null; }
function closeCamera() { stopCamera(); $("#cameraModal").hidden = true; }
$("#cameraBtn").onclick = openCamera;
$("#cameraClose").onclick = closeCamera;
$("#cameraModal").onclick = (e) => { if (e.target.id === "cameraModal") closeCamera(); };
$("#receiptList").onclick = async (e) => {
  const o = e.target.closest(".rc-open");
  if (o) return openReceipt(o.dataset.rid);
  const b = e.target.closest(".rc-remove");
  if (!b || !confirm("이 영수증을 지울까요? 원가율이 다시 계산돼요.")) return;
  try { renderCosts(await sendJSON(`/api/receipt/${b.dataset.id}`, "DELETE"), false); loadCosts(false); }
  catch (err) { alert(err.message); }
};

// ---------------------------------------------------------------
// 날씨 · 공휴일 · 행사
// ---------------------------------------------------------------
const WX_SUN = `<circle cx="16" cy="16" r="6.5" fill="#F5B02E"/><g stroke="#F5B02E" stroke-width="2.4" stroke-linecap="round"><path d="M16 3.5v3M16 25.5v3M3.5 16h3M25.5 16h3M7.2 7.2l2.1 2.1M22.7 22.7l2.1 2.1M7.2 24.8l2.1-2.1M22.7 9.3l2.1-2.1"/></g>`;
const WX_CLOUD = (fill) => `<path fill="${fill}" d="M9 24a5.5 5.5 0 0 1-.7-11 7.5 7.5 0 0 1 14.4 1.1A5 5 0 0 1 22.5 24Z"/>`;
const WX_ICONS = {
  "맑음": WX_SUN,
  "구름 많음": `<g transform="translate(5 -3) scale(.75)">${WX_SUN}</g><g transform="translate(-1 5) scale(.9)">${WX_CLOUD("#AEB8BF")}</g>`,
  "흐림": WX_CLOUD("#98A4AC"),
  "비": `<g transform="translate(0 -4)">${WX_CLOUD("#98A4AC")}</g><g stroke="#3F8FD8" stroke-width="2.4" stroke-linecap="round"><path d="M11 23.5l-1.5 4M17 23.5l-1.5 4M23 23.5l-1.5 4"/></g>`,
  "눈": `<g transform="translate(0 -4)">${WX_CLOUD("#98A4AC")}</g><g fill="#6FB1E6"><circle cx="10" cy="25.5" r="2"/><circle cx="16" cy="28" r="2"/><circle cx="22" cy="25.5" r="2"/></g>`,
};

// 기상청 하늘 상태 기준: 전운량 0~5 맑음, 6~8 구름 많음, 9~10 흐림. 비는 위 요약과 같이 1mm 이상부터
function sky(d) {
  if (d.snow_cm > 0) return "눈";
  if (d.rain_mm >= 1) return "비";
  if (d.cloud >= 9) return "흐림";
  if (d.cloud >= 6 || d.rain_mm > 0) return "구름 많음";
  return d.cloud == null ? "" : "맑음";
}

function wxIcon(d) {
  const s = sky(d);
  return `<svg class="wx-icon" viewBox="0 0 32 32" role="img" aria-label="${s}"><title>${s}</title>${WX_ICONS[s] || ""}</svg>`;
}

// ---------------------------------------------------------------
// 대형마트 판매가 (한국소비자원 참가격, 음식 재료만): 가장 싼 회사 · 보통 가격 · 2주 전 대비
// ---------------------------------------------------------------
const MART_FIRST = 12;   // 처음에 보여 줄 카드 수 (더보기마다 12개씩 더)
let mart = null, martCat = "전체", martPage = 1;

const martChange = (v) => (v == null ? "" : v > 0
  ? `<span class="mart-chg mart-up">2주 전보다 ▲${v.toFixed(1)}%</span>`
  : v < 0 ? `<span class="mart-chg mart-down">2주 전보다 ▼${Math.abs(v).toFixed(1)}%</span>`
  : `<span class="mart-chg">2주 전과 같아요</span>`);

function martCard(x) {
  const one = x.chains.length === 1;   // 한 회사에서만 조사된 재료는 비교 없이
  const sub = [one ? "" : `보통 ${won(x.typical)}`, x.daegu ? `대구 매장 ${won(x.daegu.price)}` : ""].filter(Boolean).join(" · ");
  return `<article class="mart-item">
    <p class="mart-cat">${esc(x.category)}</p>
    <h3>${esc(x.name)}</h3>
    <p class="mart-low"><small>${one ? "파는 곳" : "가장 싼 곳"} · ${esc(x.low_chain)}</small><b>${won(x.low)}</b></p>
    <p class="mart-sub">${sub || "한 회사에서만 조사됐어요"}</p>
    ${martChange(x.change_pct) || `<span class="mart-chg">2주 전 값 없음</span>`}
    ${one ? `<p class="mart-chains-none">회사별 비교 없음</p>` : `<details class="mart-chains"><summary>회사별 가격 ${x.chains.length}곳</summary>
      <ul>${x.chains.map((c) => `<li><span>${esc(c.chain)}<small>${esc(c.channel)}</small></span><b>${won(c.price)}</b>${
        c.change_pct ? `<em class="${c.change_pct > 0 ? "mart-up" : "mart-down"}">${pct(c.change_pct)}</em>` : "<em></em>"}</li>`).join("")}</ul>
    </details>`}
  </article>`;
}

function renderMart() {
  // 2주 새 오른 재료 → 내린 재료 → 그대로인 재료 순
  const rank = (x) => (x.change_pct > 0 ? 0 : x.change_pct < 0 ? 1 : 2);
  const list = mart.items.filter((x) => martCat === "전체" || x.category === martCat)
    .sort((a, b) => rank(a) - rank(b) || Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0) || a.name.localeCompare(b.name, "ko"));
  $("#martFilter").innerHTML = ["전체", ...mart.categories].map((c) =>
    `<button type="button" data-cat="${esc(c)}" class="${c === martCat ? "active" : ""}" aria-pressed="${c === martCat}">${esc(c)}</button>`).join("");
  const pages = Math.ceil(list.length / MART_FIRST);
  martPage = Math.min(martPage, pages || 1);
  $("#martGrid").innerHTML = list.length ? list.slice(0, martPage * MART_FIRST).map(martCard).join("")
    : `<p class="muted">이 종류는 이번 조사에 없어요</p>`;
  // 12개씩 더 보기: "더보기 지금 몇 번째 | 모두 몇 번" (끝까지 보면 처음으로 접기)
  const btn = $("#martAll");
  btn.hidden = pages <= 1;
  btn.innerHTML = martPage < pages ? `더보기 <b>${martPage}</b> | ${pages}` : "처음으로 접기";
  btn.setAttribute("aria-label", martPage < pages ? `12개 더 보기 (${pages}번 중 ${martPage}번째, ${list.length}개 중 ${martPage * MART_FIRST}개 보는 중)` : "처음 12개만 보기");
}

async function loadMart() {
  try { mart = await getJSON("/api/mart"); }
  catch (e) { $("#martBasis").textContent = "대형마트 판매가를 불러오지 못했어요"; $("#martGrid").innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
  const up = mart.items.filter((x) => x.change_pct > 0).length;
  $("#martBasis").textContent = `한국소비자원 참가격 · ${mmdd(mart.date)} 조사 (2주마다) · 음식 재료 ${mart.items.length}개 중 2주 새 오른 것 ${up}개`;
  renderMart();
}
$("#martFilter").onclick = (e) => {
  const b = e.target.closest("[data-cat]");
  if (b) { martCat = b.dataset.cat; martPage = 1; renderMart(); }
};
// 회사별 가격은 한 번에 하나만 펼침 (다른 카드를 펼치면 앞에 펼친 것은 접힘 — 겹쳐서 가려지지 않게)
$("#martGrid").addEventListener("toggle", (e) => {
  if (!e.target.open) return;
  $("#martGrid").querySelectorAll(".mart-chains[open]").forEach((d) => { if (d !== e.target) d.open = false; });
}, true);
$("#martAll").onclick = () => {
  const pages = Math.ceil(mart.items.filter((x) => martCat === "전체" || x.category === martCat).length / MART_FIRST);
  if (martPage < pages) { martPage += 1; renderMart(); return; }
  martPage = 1;
  renderMart();
  $("#mart").scrollIntoView({ block: "start" });
};

async function loadContext() {
  let c;
  try { c = await getJSON("/api/context"); } catch (e) { return; }
  const w = c.weather;
  $("#weatherCard").innerHTML = `<h3>대구 날씨 (지난 7일)</h3>
    <p class="muted" style="margin-bottom:10px">비 ${w.rain_total_mm}mm (${w.rain_days}일) · 최저 ${w.min_temp}℃ · 최고 ${w.max_temp}℃</p>
    <div class="wx">${(w.daily || []).map((d) => `<div>${mmdd(d.date)}${wxIcon(d)}<b>${Math.round(d.max_temp)}°</b>${d.rain_mm ? `비 ${d.rain_mm}` : "-"}</div>`).join("")}</div>`;
  const fmt = (s) => `${s.slice(4, 6)}.${s.slice(6, 8)}`;
  $("#holidayCard").innerHTML = `<h3>다가오는 공휴일 (30일)</h3>` + (c.holidays.length
    ? `<ul class="ctx-list">${c.holidays.map((x) => `<li>${fmt(x.date)} ${esc(x.name)}<small>도매시장 휴장 전 수요가 몰릴 수 있어요</small></li>`).join("")}</ul>`
    : `<p class="muted">30일 안에 공휴일이 없어요</p>`);
  $("#eventCard").innerHTML = `<h3>이달의 대구 행사 (${c.events.length}개)</h3>` + (c.events.length
    ? `<ul class="ctx-list event-list">${c.events.slice(0, 8).map((x) => {
        const inner = `<b>${esc(x.title)}</b><small>${fmt(x.start)} ~ ${fmt(x.end)} · ${esc((x.addr || "").replace("대구광역시 ", ""))}</small>`;
        return `<li>${x.content_id ? `<button type="button" class="event-link" data-event="${esc(x.content_id)}">${inner}<i aria-hidden="true">›</i></button>` : inner}</li>`;
      }).join("")}</ul>`
    : `<p class="muted">이달에 남은 행사가 없어요</p>`);
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
  markAlertsRead();
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
  if (e.target.closest(".fab-x")) return;   // ×는 끌기 · 채팅 열기와 따로
  const r = fab.getBoundingClientRect();
  drag = { dx: e.clientX - r.left, dy: e.clientY - r.top, sx: e.clientX, sy: e.clientY, moved: false };
  fab.setPointerCapture(e.pointerId);
});
fab.addEventListener("pointermove", (e) => {
  if (!drag || fabHidden()) return;   // 작은 살피는 제자리 고정
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
  } else if (fabHidden()) {
    setFabHidden(false);
  } else {
    chatEl.classList.contains("open") ? closeChat() : openChat();
  }
  drag = null;
});
window.addEventListener("resize", () => { if (fab.style.left && !fabHidden()) placeFab(fab.offsetLeft, fab.offsetTop); });

// 살피 줄이기: 머리 위 ×를 누르면 문장 없이 작게 아래에 있고, 작은 살피를 누르면 돌아옴 (이 브라우저에 기억)
const FAB_HIDE_KEY = "salpi_fab_hidden";
const fabHidden = () => document.body.classList.contains("fab-hidden");
function setFabHidden(on, save = true) {
  document.body.classList.toggle("fab-hidden", on);
  $("#fabMain").setAttribute("aria-label", on ? "살피 다시 크게 보기" : "살피 챗봇 열기 (끌어서 옮길 수 있어요)");
  $("#fabMain").title = on ? "다시 크게 보기" : "누르면 대화, 끌면 이동";
  if (on) closeChat();
  if (save) try { localStorage.setItem(FAB_HIDE_KEY, on ? "1" : "0"); } catch (e) {}
}
$("#fabX").addEventListener("click", () => setFabHidden(true));
// 키보드로 누른 경우 (마우스 · 손가락은 위 pointerup에서 처리)
$("#fabMain").addEventListener("click", (e) => { if (e.detail === 0) fabHidden() ? setFabHidden(false) : openChat(); });
try { if (localStorage.getItem(FAB_HIDE_KEY) === "1") setFabHidden(true, false); } catch (e) {}

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
}
$("#talkClose").addEventListener("click", closeTalk);
$("#talk").addEventListener("click", (e) => {
  if (e.target.id === "talk" || e.target.id === "talkLink") closeTalk();
  const b = e.target.closest("button[data-kind]");
  if (b) { talkKind = b.dataset.kind; renderTalk(); $(`#talkTabs [data-kind="${talkKind}"]`).focus(); }
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#talk").hidden) closeTalk(); });

loadOverview();
loadProducts();
if (STORE_VIEW) {
  loadDemand();
  loadCosts();
} else if (!ITEM) {
  loadContext();
  loadMart();
}
if (location.hash === "#chat") openChat();   // 주소 끝에 #chat 을 붙이면 채팅창이 열린 채로 시작
if (location.hash === "#talk") openTalk();   // 주소 끝에 #talk 을 붙이면 알림톡 시연이 열린 채로 시작
if (location.hash === "#rise") setTimeout(() => goSlide(1, "instant"), 4000);   // 시연용: 첫 야채 대시보드부터

// ---------------------------------------------------------------
// 영수증 한 장 자세히 (사진 + 품목) — '최근 영수증' 목록 · 마이페이지 '나의 영수증'에서 엶
// ---------------------------------------------------------------
async function openReceipt(id) {
  const modal = $("#receiptModal");
  $("#receiptModalBody").innerHTML = `<div class="reading"><div class="spinner"></div><b>영수증을 불러오는 중이에요</b></div>`;
  modal.hidden = false;
  let d;
  try { d = await getJSON(`/api/receipt/${id}`); }
  catch (e) { $("#receiptModalBody").innerHTML = `<p class="rc-warn">${esc(e.message)}</p>`; return; }
  const qtyTxt = (x) => (x.unit ? qty(x.qty_base, x.unit) : "-");
  $("#receiptModalBody").innerHTML = `
    <h3>${mmdd(d.purchased_on)} · ${esc(supplierName(d.supplier))}</h3>
    <p class="muted small">${d.source === "ocr" ? "영수증 읽기로 저장" : "기본 데이터"} · 합계 ${won(d.total_amount)}</p>
    <div class="receipt-view">
      ${d.image_url ? `<a href="${esc(d.image_url)}" target="_blank" rel="noopener" title="크게 보기"><img src="${esc(d.image_url)}" alt="영수증 사진"></a>`
                    : `<div class="no-photo">사진이 없어요</div>`}
      <table class="price-table">
        <thead><tr><th>영수증 품목</th><th>재료</th><th>양</th><th>금액</th><th>kg·모당</th></tr></thead>
        <tbody>${d.items.map((x) => `<tr><td>${esc(x.raw_name)}</td><td>${esc(x.item || "재료 아님")}</td><td>${qtyTxt(x)}</td>
          <td class="price">${won(x.amount)}</td><td>${x.unit_price ? won(x.unit_price) : "-"}</td></tr>`).join("")}</tbody>
      </table>
    </div>`;
}
const closeReceipt = () => { $("#receiptModal").hidden = true; };
$("#receiptModalClose").onclick = closeReceipt;
$("#receiptModal").onclick = (e) => { if (e.target.id === "receiptModal") closeReceipt(); };

// ---------------------------------------------------------------
// 마이페이지 (시연: 로그인했다고 치고 시연용 가게 계정)
// ---------------------------------------------------------------
const ME = { name: "달서구 한식당 사장님", store: "살피 한식당", place: "대구 달서구", type: "한식 · 40석", email: "demo@salpi.example" };
if (STORE_VIEW) $("#storeName").textContent = `나의 가게 · ${ME.store}`;

function openMypage(view = "home") {
  $("#mypage").classList.add("open");
  $("#mypage").setAttribute("aria-hidden", "false");
  $("#backdrop").hidden = false;
  renderMypage(view);
}
function closeMypage() {
  $("#mypage").classList.remove("open");
  $("#mypage").setAttribute("aria-hidden", "true");
  $("#backdrop").hidden = true;
}

async function renderMypage(view) {
  const box = $("#mypageBody");
  $("#mypageBack").hidden = view === "home";
  $("#mypageTitle").textContent = view === "home" ? "마이페이지" : "나의 영수증";
  if (view === "receipts") {
    box.innerHTML = `<p class="muted">불러오는 중이에요</p>`;
    try {
      const { receipts } = await getJSON("/api/receipts");
      box.innerHTML = receipts.length ? `<ul class="my-receipts">${receipts.map((p) => `<li><button data-rid="${p.id}">
        <b>${mmdd(p.purchased_on)} · ${esc(supplierName(p.supplier))}</b>
        <span>${p.items}줄 · ${won(p.total_amount)}${p.source === "ocr" ? " · 영수증 읽기" : " · 기본 데이터"}</span><i>›</i></button></li>`).join("")}</ul>`
        : `<p class="muted">아직 저장한 영수증이 없어요.</p>`;
    } catch (e) { box.innerHTML = `<p class="rc-warn">${esc(e.message)}</p>`; }
    return;
  }
  const prefs = alertPrefs();
  box.innerHTML = `
    <section class="my-card profile">
      <img src="/static/img/owner_face.png" alt="">
      <div><b>${esc(ME.name)}</b><small>${esc(ME.email)}</small></div>
    </section>
    <section class="my-card">
      <h4>내 정보</h4>
      <dl><dt>지역</dt><dd>${esc(ME.place)}</dd><dt>업종</dt><dd>${esc(ME.type)}</dd></dl>
      <a class="my-link" href="/?page=store"><span>나의 가게</span><i>›</i></a>
      <button class="my-link" data-view="receipts"><span>나의 영수증</span><i>›</i></button>
    </section>
    <section class="my-card">
      <h4>알림 설정</h4>
      <p class="muted small">켜 둔 알림은 살피가 챗봇 창으로 보내 드려요.</p>
      ${ALERT_TYPES.map(([k, title, desc]) => `<label class="toggle-row">
        <span><b>${title}</b><small>${desc}</small></span>
        <input type="checkbox" class="switch" data-pref="${k}" ${prefs[k] ? "checked" : ""}></label>`).join("")}
    </section>
    <section class="my-card" id="permCard">
      <h4>권한 설정</h4>
      <p class="muted small">영수증을 카메라로 찍거나, 창을 닫아 둬도 시세 알림을 받으려면 권한이 필요해요.</p>
      <div class="toggle-row"><span><b>카메라</b><small id="camState">확인하는 중</small></span><span id="camAct"></span></div>
      <div class="toggle-row"><span><b>브라우저 알림</b><small id="notiState">확인하는 중</small></span><span id="notiAct"></span></div>
    </section>
    <section class="my-card my-account">
      <button class="my-link" type="button" data-account="logout"><span>로그아웃</span><i>›</i></button>
      <button class="my-link danger" type="button" data-account="leave"><span>회원탈퇴</span><i>›</i></button>
      <p class="muted small" id="accountNote" hidden>로그인 · 회원가입 기능이 생기면 쓸 수 있어요.</p>
    </section>`;
  showCameraPerm();
  showNotiPerm();
}

// 브라우저 알림 권한: 허용하면 새 시세 알림을 화면 밖(작업 표시줄 · 휴대폰 알림)으로도 띄움
function showNotiPerm() {
  if (!$("#notiState")) return;
  const state = "Notification" in window ? Notification.permission : "none";   // granted · denied · default
  $("#notiState").textContent = { granted: "허용됨 · 새 시세 알림을 바로 띄워 드려요", denied: "꺼져 있어요 · 브라우저 주소창 왼쪽 자물쇠에서 켜 주세요",
    default: "아직 허용하지 않았어요", none: "이 브라우저는 알림을 쓸 수 없어요" }[state];
  $("#notiAct").innerHTML = state === "granted" ? `<span class="perm-on">허용됨</span>`
    : state === "default" ? `<button class="btn primary" id="notiAllow" type="button">허용하기</button>` : "";
  const b = $("#notiAllow");
  if (b) b.onclick = async () => { await Notification.requestPermission(); showNotiPerm(); notifyAlerts(); };
}

// 카메라 권한 상태: 허용됨 · 꺼짐 · 아직 안 물어봄 (브라우저가 알려 주지 않으면 '허용하기'로 직접 물어봄)
async function cameraPerm() {
  try { return (await navigator.permissions.query({ name: "camera" })).state; } catch (e) { return "prompt"; }
}
async function showCameraPerm() {
  const state = navigator.mediaDevices?.getUserMedia ? await cameraPerm() : "none";
  if (!$("#camState")) return;
  $("#camState").textContent = { granted: "허용됨 · 영수증을 바로 찍을 수 있어요", denied: "꺼져 있어요 · 아래 방법으로 켜 주세요",
    prompt: "아직 허용하지 않았어요", none: "이 브라우저는 카메라를 쓸 수 없어요" }[state];
  $("#camAct").innerHTML = state === "granted" ? `<span class="perm-on">허용됨</span>`
    : state === "prompt" ? `<button class="btn primary" id="camAllow" type="button">허용하기</button>` : "";
  $("#permCard .cam-guide")?.remove();
  if (state === "denied") $("#permCard").insertAdjacentHTML("beforeend", CAM_GUIDE);
  const b = $("#camAllow");
  if (b) b.onclick = async () => {
    try { (await askCamera()).getTracks().forEach((t) => t.stop()); } catch (e) {}
    showCameraPerm();
  };
}

$("#meBtn").onclick = () => openMypage();
$("#mypageClose").onclick = closeMypage;
$("#mypageBack").onclick = () => renderMypage("home");
$("#backdrop").onclick = closeMypage;
$("#mypageBody").onclick = (e) => {
  if (e.target.closest("[data-account]")) { $("#accountNote").hidden = false; return; }   // 로그인 기능이 생기면 연결
  const v = e.target.closest("[data-view]");
  if (v) return renderMypage(v.dataset.view);
  const r = e.target.closest("[data-rid]");
  if (r) openReceipt(r.dataset.rid);
};
$("#mypageBody").onchange = (e) => {
  const k = e.target.dataset.pref;
  if (!k) return;
  const prefs = alertPrefs();
  prefs[k] = e.target.checked;
  store(ALERT_PREFS_KEY, prefs);
  deliverAlerts();
};
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeReceipt(); closeMypage(); closeEvent(); closeCamera(); } });

// ---------------------------------------------------------------
// 시세 알림: 켜 둔 종류만 살피 말투로 챗봇 창에 보냄 (규칙으로 만든 문장, 숫자는 대시보드 시세 그대로)
// 읽음 여부 · 설정은 이 브라우저에 기억 (로그인이 생기면 Supabase로 옮김)
// ---------------------------------------------------------------
const ALERT_PREFS_KEY = "salpi_alert_prefs", ALERT_READ_KEY = "salpi_alert_read";
const ALERT_TYPES = [
  ["all", "모든 시세가 오르고 내릴 때", "지난주보다 3% 넘게 움직인 야채를 알려 드려요"],
  ["up", "값이 오를 때만", "지난주보다 10% 넘게 오른 야채"],
  ["down", "값이 내렸을 때만", "지난주보다 10% 넘게 내린 야채"],
  ["unusual", "평소랑 다를 때만", "하루 사이에 평소보다 크게 움직인 야채"],
  ["weekly", "주 1회 대시보드 리포트", "한 주 시세를 한 번에 정리해 드려요"],
];
const DEFAULT_PREFS = { all: false, up: true, down: false, unusual: true, weekly: true };
const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } };
function store(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
const alertPrefs = () => ({ ...DEFAULT_PREFS, ...load(ALERT_PREFS_KEY, {}) });
const josa = (w, a, b) => { const c = w.charCodeAt(w.length - 1); return w + (c >= 0xac00 && c <= 0xd7a3 && (c - 0xac00) % 28 ? a : b); };
let delivered = [];   // 지금 챗봇 창에 있는 알림 [{id, text}]

function buildAlerts() {
  if (!overview.length) return [];
  const prefs = alertPrefs();
  const day = overview.map((r) => r.wholesale_date).filter(Boolean).sort().at(-1) || "";
  const tag = mmdd(day);
  const out = [], seen = new Set();
  const push = (id, text, title, item) => { if (!seen.has(id)) { seen.add(id); out.push({ id: `${day}|${id}`, text, title, item, day }); } };
  const moveTitle = (r) => `${josa(r.item, "이", "가")} 지난주보다 ${pct(ch(r))} ${ch(r) > 0 ? "올랐어요" : "내렸어요"}`;
  const ch = (r) => r.wholesale_change_pct ?? 0;
  const move = (r) => {
    const f = expOf(r);
    if (ch(r) > 0) return `사장님, **${josa(r.item, "이", "가")} 지난주보다 ${pct(ch(r))} 올랐어요** (${tag} 도매 kg당 ${won(r.wholesale_kg)}).\n`
      + (f >= 2 ? "다음 주에도 오를 수 있어요. 필요한 만큼은 미리 사 두세요." : f <= -2 ? "다음 주엔 내릴 수 있어요. 급하지 않으면 조금 기다려 보세요." : "다음 주엔 비슷할 것 같아요. 필요한 만큼만 사 두세요.");
    return `사장님, **${josa(r.item, "이", "가")} 지난주보다 ${pct(ch(r))} 내렸어요** (${tag} 도매 kg당 ${won(r.wholesale_kg)}).\n`
      + (f >= 2 ? "다음 주엔 다시 오를 수 있어요. 지금 사 두면 좋아요." : "지금 사기 좋은 때예요.");
  };
  const byAbs = (a, b) => Math.abs(ch(b)) - Math.abs(ch(a));
  const pushMove = (r) => push(`move|${r.item}`, move(r), moveTitle(r), r.item);
  if (prefs.all) overview.filter((r) => Math.abs(ch(r)) >= 3).sort(byAbs).slice(0, 6).forEach(pushMove);
  if (prefs.up) overview.filter((r) => ch(r) >= 10).sort(byAbs).slice(0, 3).forEach(pushMove);
  if (prefs.down) overview.filter((r) => ch(r) <= -10).sort(byAbs).slice(0, 3).forEach(pushMove);
  if (prefs.unusual) {
    overview.map((r) => {
      const h = (r.history || []).map((x) => x.kg_price).filter((v) => v > 0);
      const d = h.slice(1).map((v, i) => (v / h[i] - 1) * 100);
      if (d.length < 6) return null;
      const last = d.at(-1), usual = d.slice(0, -1).reduce((s, v) => s + Math.abs(v), 0) / (d.length - 1);
      return Math.abs(last) >= Math.max(10, usual * 2.5) ? { r, last, usual } : null;
    }).filter(Boolean).sort((a, b) => Math.abs(b.last) - Math.abs(a.last)).slice(0, 3).forEach(({ r, last, usual }) =>
      push(`unusual|${r.item}`, `사장님, **${josa(r.item, "이", "가")} 평소와 달라요.** 직전 거래일보다 ${pct(last)} ${last > 0 ? "올랐는데" : "내렸는데"}, `
        + `보통은 하루 ${usual.toFixed(0)}% 안팎으로 움직여요.\n${last > 0 ? "주문 전에 가격을 한 번 더 확인해 보세요." : "필요하면 지금 사 두는 것도 좋아요."}`,
        `${josa(r.item, "이", "가")} 평소와 달라요 (하루 ${pct(last)})`, r.item));
  }
  if (prefs.weekly && day) {
    const d = new Date(day), monday = new Date(d - ((d.getDay() + 6) % 7) * 864e5).toISOString().slice(0, 10);
    const ups = overview.filter((r) => ch(r) >= 3), downs = overview.filter((r) => ch(r) <= -3), rise = overview.filter((r) => expOf(r) >= 2);
    const top = [...overview].sort((a, b) => ch(b) - ch(a));
    out.push({ id: `week|${monday}`, title: `이번 주 살피 리포트 (${mmdd(monday)} 주)`, item: null, day,
      text: `사장님, **이번 주 살피 리포트**예요 (${mmdd(monday)} 주).\n`
      + `- 지난주보다 오른 야채 ${ups.length}개 · 내린 야채 ${downs.length}개\n`
      + `- 가장 많이 오른 야채: ${top[0].item} ${pct(ch(top[0]))}\n`
      + `- 가장 많이 내린 야채: ${top.at(-1).item} ${pct(ch(top.at(-1)))}\n`
      + `- 다음 주 오를 가능성: ${rise.length}개${rise.length ? ` (${rise.sort((a, b) => expOf(b) - expOf(a)).slice(0, 3).map((r) => r.item).join(", ")} 등)` : ""}\n`
      + "자세한 건 위의 시세 대시보드에서 보세요." });
  }
  return out;
}

function deliverAlerts() {
  const list = buildAlerts();
  document.querySelectorAll("#chatBody .msg.alert").forEach((el) => el.remove());
  if (list.length && !body.children.length) addMsg("bot", "사장님, 오늘 대구 시세 살펴왔어요.\n아래 버튼을 누르거나 편하게 물어보세요.");
  const read = new Set(load(ALERT_READ_KEY, []));
  for (const a of list) {
    const el = addMsg("bot", a.text);
    el.classList.add("alert");
    el.dataset.alertId = a.id;
    el.insertAdjacentHTML("afterbegin", `<span class="alert-tag">시세 알림${read.has(a.id) ? "" : " · 새 알림"}</span>`);
    el.insertAdjacentHTML("beforeend", `<span class="alert-more">${a.item ? `${esc(a.item)} 시세 자세히 보기` : "시세 대시보드 보기"} ›</span>`);
    el.title = "누르면 자세한 시세로 넘어가요";
  }
  delivered = list;
  if (chatEl.classList.contains("open")) markAlertsRead();
  updateBadges();
  renderBell();
  notifyAlerts();
}

// 브라우저 알림을 허용했으면 아직 읽지 않은 새 알림을 한 번씩 띄움 (최대 3개)
const ALERT_NOTIFIED_KEY = "salpi_alert_notified";
function notifyAlerts() {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  const read = new Set(load(ALERT_READ_KEY, [])), shown = new Set(load(ALERT_NOTIFIED_KEY, []));
  const fresh = delivered.filter((a) => !read.has(a.id) && !shown.has(a.id)).slice(0, 3);
  for (const a of fresh) {
    try { new Notification("살피 시세 알림", { body: a.text.split("\n")[0], icon: "/static/img/salpi_face.png", tag: a.id }); } catch (e) {}
    shown.add(a.id);
  }
  if (fresh.length) store(ALERT_NOTIFIED_KEY, [...shown].slice(-200));
}

function unreadCount() {
  const read = new Set(load(ALERT_READ_KEY, []));
  return delivered.filter((a) => !read.has(a.id)).length;
}
function markAlertsRead(ids = delivered.map((a) => a.id)) {
  const read = new Set(load(ALERT_READ_KEY, []));
  ids.forEach((id) => read.add(id));
  store(ALERT_READ_KEY, [...read].slice(-300));
  updateBadges();
}
function updateBadges() {
  const n = unreadCount();
  for (const el of [$("#fabCount"), $("#bellCount")]) { el.hidden = !n; el.textContent = n > 99 ? "99+" : n; }
  $("#fabBubble").textContent = n ? "시세 알림이 있어요" : "살피 챗봇에게 물어보세요";
  $("#fab").classList.toggle("has-alert", n > 0);
  renderBell();
}

// 위쪽 종: 알림만 모아 보기. 누르면 그 알림의 자세한 시세로 넘어감
function renderBell() {
  const read = new Set(load(ALERT_READ_KEY, []));
  $("#bellList").innerHTML = delivered.length ? delivered.map((a) => `<li><button data-aid="${esc(a.id)}" class="${read.has(a.id) ? "" : "unread"}">
      <img src="/static/img/salpi_face.png" alt=""><span><b>${esc(a.title)}</b><small>${mmdd(a.day)} 시세 · ${a.item ? "누르면 재료 페이지" : "누르면 대시보드"}</small></span></button></li>`).join("")
    : `<li class="empty">새 알림이 없어요.<br><button data-open-settings>마이페이지에서 알림 종류 켜기 ›</button></li>`;
}
function toggleBell(open = $("#bellPanel").hidden) {
  $("#bellPanel").hidden = !open;
  $("#bellBtn").setAttribute("aria-expanded", String(open));
}
$("#bellBtn").onclick = (e) => { e.stopPropagation(); toggleBell(); };
$("#bellPanel").onclick = (e) => {
  e.stopPropagation();
  const a = e.target.closest("[data-aid]");
  if (a) { toggleBell(false); return goToAlert(a.dataset.aid); }
  if (e.target.closest("[data-open-settings]")) { toggleBell(false); openMypage(); }
};
$("#bellReadAll").onclick = () => markAlertsRead();
document.addEventListener("click", () => toggleBell(false));

// 알림 → 자세한 시세: 재료 알림은 그 재료 페이지(/?item=재료), 리포트는 첫 화면 전체 대시보드
function goToAlert(id) {
  const a = delivered.find((x) => x.id === id);
  if (!a) return;
  markAlertsRead([id]);
  if (a.item) { location.href = `/?item=${encodeURIComponent(a.item)}`; return; }
  closeChat();
  if (ITEM) { location.href = "/#dashboard"; return; }
  goSlide(0, "auto");
  setPaused(true);   // 보는 동안 다른 야채로 넘어가지 않게 (일시정지 버튼으로 다시 자동)
  $("#dashboard").scrollIntoView({ behavior: "smooth" });
  const s = slides()[0];
  s?.classList.remove("flash"); void s?.offsetWidth; s?.classList.add("flash");
}
body.addEventListener("click", (e) => {
  const m = e.target.closest(".msg.alert");
  if (m) goToAlert(m.dataset.alertId);
});

// ---------------------------------------------------------------
// 행사 정보 창: '시세 영향 정보'의 행사를 누르면 한국관광공사 행사 정보를 보여 줌
// ---------------------------------------------------------------
async function openEvent(id) {
  const box = $("#eventModalBody");
  box.innerHTML = `<div class="reading"><div class="spinner"></div><b>행사 정보를 불러오는 중이에요</b></div>`;
  $("#eventModal").hidden = false;
  let d;
  try { d = await getJSON(`/api/event/${encodeURIComponent(id)}`); }
  catch (e) { box.innerHTML = `<p class="rc-warn">${esc(e.message)}</p>`; return; }
  const day = (s) => (s ? `${s.slice(0, 4)}.${s.slice(4, 6)}.${s.slice(6, 8)}` : "");
  const row = (k, v) => (v ? `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>` : "");
  const map = `https://map.kakao.com/link/search/${encodeURIComponent(d.addr || d.title)}`;
  box.innerHTML = `
    <div class="event-top ${d.image ? "" : "no-img"}">
      ${d.image ? `<a class="event-poster" href="${esc(d.image)}" target="_blank" rel="noopener" title="포스터 크게 보기">
        <img src="${esc(d.image)}" alt="${esc(d.title)} 포스터"></a>` : ""}
      <div class="event-head">
        <h3>${esc(d.title)}</h3>
        <dl class="event-info">
          ${row("기간", d.start ? `${day(d.start)} ~ ${day(d.end)}` : "")}${row("장소", d.place || d.addr)}${row("주소", d.place ? d.addr : "")}
          ${row("시간", d.playtime)}${row("요금", d.fee)}${row("문의", d.tel)}${row("주최", d.sponsor)}
        </dl>
        ${d.overview ? `<p class="event-overview">${esc(d.overview)}</p>` : ""}
      </div>
    </div>
    <div class="event-body">
      <div class="event-links">
        ${(d.homepages || []).map((u, i) => `<a href="${esc(u)}" target="_blank" rel="noopener">${i ? "관련 사이트" : "공식 홈페이지"} →</a>`).join("")}
        <a href="${map}" target="_blank" rel="noopener">지도에서 보기 →</a>
      </div>
      <p class="muted small">출처: 한국관광공사 국문 관광정보</p>
    </div>`;
}
function closeEvent() { $("#eventModal").hidden = true; }
$("#eventModalClose").onclick = closeEvent;
$("#eventModal").onclick = (e) => { if (e.target.id === "eventModal") closeEvent(); };
$("#eventCard").onclick = (e) => {
  const b = e.target.closest("[data-event]");
  if (b) openEvent(b.dataset.event);
};
