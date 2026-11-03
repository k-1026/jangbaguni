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
    </article>` + slideOrder().map((r) => {
      const f = r.forecast || {};
      const v = verdict(f);
      const reasons = [...(f.factors || [])].filter((x) => x.effect_pct !== 0)
        .sort((a, b) => Math.abs(b.effect_pct) - Math.abs(a.effect_pct)).slice(0, 2);
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
        <span class="verdict">${v.text}</span>
        <span class="range">예상 ${pct(f.range_pct?.[0])} ~ ${pct(f.range_pct?.[1])}
          <small>(${won(f.expected_kg_price_range?.[0])} ~ ${won(f.expected_kg_price_range?.[1])}/kg · 믿을 만한 정도 ${esc(f.confidence || "-")})</small></span>
        <a class="shop" href="${esc(r.foodspring_url)}" target="_blank" rel="noopener">식봄에서 보기 →</a>
        <ul>${reasons.map((x) => `<li><b>${esc(x.factor)}</b> ${pct(x.effect_pct)} — ${esc(x.detail)}</li>`).join("")
          || "<li>뚜렷하게 오르거나 내릴 이유가 적어요</li>"}<li><b>살피 제안</b> — ${esc(f.suggestion || "-")}</li></ul>
      </div>
    </article>`;
    }).join("");
}

// 슬라이드 넘기기: 손가락 스와이프는 브라우저 스크롤, 화살표는 끝에서 처음으로(처음에서 끝으로) 돌아감
const slider = $("#slider");
const slides = () => [...slider.querySelectorAll(".slide")];
function slideIndex() { return Math.round(slider.scrollLeft / (slider.clientWidth + 14)); }
function goSlide(i, behavior = "smooth") {
  const s = slides();
  if (!s.length) return;
  i = ((i % s.length) + s.length) % s.length;
  slider.scrollTo({ left: s[i].offsetLeft - slider.offsetLeft, behavior });
  if (behavior !== "smooth") onSlideChange();
}
let lastSlide = -1;
function onSlideChange() {
  const s = slides(), i = Math.min(slideIndex(), s.length - 1);
  $("#dots").textContent = s.length > 1 ? `${i + 1} / ${s.length}` : "";
  $("#slideTitle").textContent = s[i]?.dataset.title || "야채 시세";
  if (i === lastSlide || !overview.length) return;
  lastSlide = i;
  drawSlideChart(i);
  renderDetail(s[i]?.dataset.item || slideOrder()[0]?.item);
}
slider.addEventListener("scroll", () => requestAnimationFrame(onSlideChange));
$("#prevSlide").onclick = () => goSlide(slideIndex() - 1);
$("#nextSlide").onclick = () => goSlide(slideIndex() + 1);

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
        x: { grid: { display: false }, ticks: { color: "#4C524E", font: { size: 11 }, autoSkip: false, maxRotation: 0 } },
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
// 살피 AI 채팅
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
if (location.hash === "#chat") openChat();   // 주소 끝에 #chat 을 붙이면 채팅창이 열린 채로 시작
if (location.hash === "#rise") setTimeout(() => goSlide(1, "instant"), 4000);   // 시연용: 첫 야채 대시보드부터
