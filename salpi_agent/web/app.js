// 살피 시세 대시보드 화면 동작
const $ = (s) => document.querySelector(s);
const won = (v) => (v == null ? "-" : `${Math.round(v).toLocaleString("ko-KR")}원`);
const pct = (v) => (v == null ? "-" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`);
const cls = (v, band = 0) => (v == null ? "" : v > band ? "up" : v < -band ? "down" : "");
const mmdd = (d) => `${d.slice(5, 7)}.${d.slice(8, 10)}`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// 재료 카드 배경색 (사진 대신)
const TILE = {
  양파: "#F6E3C8", 대파: "#DDEFD2", 배추: "#E4F2D5", 무: "#EEF0E8", 양배추: "#DFF0DA", 감자: "#EFE1C6",
  당근: "#FBDCC2", 애호박: "#E2EFC9", 오이: "#D4ECD2", 청양고추: "#D6EBC9", 깻잎: "#CFE6C6",
  상추: "#DDF0D3", 시금치: "#CFE8C9", 토마토: "#F9D3CB", 가지: "#E6DAF0",
};

let overview = [];
let current = null;
let chart = null;

async function getJSON(url) {
  const r = await fetch(url);
  const body = await r.json();
  if (!r.ok) throw new Error(body.detail || "데이터를 불러오지 못했어요");
  return body;
}

// ---------------------------------------------------------------
// 전체 요약 · 재료 탭 · 상품 카드
// ---------------------------------------------------------------
async function loadOverview() {
  try {
    overview = (await getJSON("/api/overview")).items;
  } catch (e) {
    $("#summary").innerHTML = `<div class="error-box">${esc(e.message)}</div>`;
    $("#productGrid").innerHTML = "";
    return;
  }
  const dated = overview.map((r) => r.wholesale_date).filter(Boolean).sort();
  $("#basis").textContent = dated.length ? `대구 북부도매시장 · ${mmdd(dated.at(-1))} 기준` : "";

  const up = overview.filter((r) => (r.wholesale_change_pct ?? 0) >= 3);
  const down = overview.filter((r) => (r.wholesale_change_pct ?? 0) <= -3);
  const rising = overview.filter((r) => (r.forecast.expected_change_pct ?? 0) >= 2);
  const top = [...overview].sort((a, b) => (b.wholesale_change_pct ?? -999) - (a.wholesale_change_pct ?? -999))[0];
  $("#summary").innerHTML = `
    <div class="chip up"><b>${up.length}개</b><small>지난주보다 오른 야채</small></div>
    <div class="chip down"><b>${down.length}개</b><small>지난주보다 내린 야채</small></div>
    <div class="chip warn"><b>${rising.length}개</b><small>다음 주 오를 가능성</small></div>
    ${top ? `<div class="chip up"><b>${esc(top.item)} ${pct(top.wholesale_change_pct)}</b><small>가장 많이 오른 야채</small></div>` : ""}`;

  $("#itemTabs").innerHTML = overview.map((r) => `
    <button data-item="${esc(r.item)}">${esc(r.item)}<span class="pct ${cls(r.wholesale_change_pct, 3)}">${pct(r.wholesale_change_pct)}</span></button>`).join("");
  $("#itemTabs").onclick = (e) => {
    const b = e.target.closest("button[data-item]");
    if (b) selectItem(b.dataset.item);
  };
  renderProducts("default");
  selectItem(top ? top.item : overview[0].item);
}

function renderProducts(sort) {
  const rows = [...overview];
  const key = { up: (r) => -(r.wholesale_change_pct ?? -999), down: (r) => r.wholesale_change_pct ?? 999,
                buy: (r) => -(r.forecast.expected_change_pct ?? -999) }[sort];
  if (key) rows.sort((a, b) => key(a) - key(b));
  $("#productGrid").innerHTML = rows.map((r) => {
    const f = r.forecast || {};
    let flag = "";
    if ((f.expected_change_pct ?? 0) >= 2) flag = `<span class="flag" style="background:var(--up)">다음 주 오를 듯</span>`;
    else if ((f.expected_change_pct ?? 0) <= -2) flag = `<span class="flag" style="background:var(--down)">다음 주 내릴 듯</span>`;
    else if ((r.wholesale_change_pct ?? 0) <= -5) flag = `<span class="flag" style="background:var(--accent)">지금 싸요</span>`;
    return `
      <a class="product" href="${esc(r.foodspring_url)}" target="_blank" rel="noopener">
        <div class="thumb" style="background:${TILE[r.item] || "#EEE"}">${flag}${esc(r.item)}</div>
        <div class="p-body">
          <span class="p-name">국내산 ${esc(r.item)}</span>
          <span class="p-price">${won(r.wholesale_kg)} <small>/kg 도매</small></span>
          <span class="p-meta">1주 <b class="${cls(r.wholesale_change_pct, 3)}">${pct(r.wholesale_change_pct)}</b>
            · 소매 ${won(r.retail_price)}/${esc(r.retail_unit || "kg")}</span>
          <div class="p-row">
            <button class="p-chart" data-chart="${esc(r.item)}">시세 보기</button>
            <span class="p-link">식봄에서 보기 →</span>
          </div>
        </div>
      </a>`;
  }).join("");
}

$("#productGrid").addEventListener("click", (e) => {
  const b = e.target.closest("[data-chart]");
  if (!b) return;           // 카드 나머지 부분은 식봄으로 이동
  e.preventDefault();
  selectItem(b.dataset.chart);
  $("#dashboard").scrollIntoView();
});
document.querySelectorAll(".sort").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".sort").forEach((x) => x.classList.toggle("active", x === b));
  renderProducts(b.dataset.sort);
}));

// ---------------------------------------------------------------
// 재료 하나: 차트 · 날짜별 표 · 예측
// ---------------------------------------------------------------
async function selectItem(name) {
  current = name;
  document.querySelectorAll("#itemTabs button").forEach((b) => b.classList.toggle("active", b.dataset.item === name));
  $("#chartTitle").textContent = `${name} 시세`;
  $("#priceRows").innerHTML = `<tr><td colspan="4">불러오는 중</td></tr>`;
  let d;
  try {
    d = await getJSON(`/api/item/${encodeURIComponent(name)}`);
  } catch (e) {
    $("#priceRows").innerHTML = `<tr><td colspan="4">${esc(e.message)}</td></tr>`;
    return;
  }
  if (current !== name) return;    // 그사이 다른 재료를 눌렀으면 무시
  const h = d.history;
  const last = h.at(-1);
  $("#priceNow").textContent = last ? `${won(last.kg_price)}/kg` : "-";
  const wc = d.trend.wholesale.week_change_pct;
  $("#priceDelta").innerHTML = wc == null ? "" : `<span class="${cls(wc, 3)}">1주 전보다 ${pct(wc)}</span>`;
  drawChart(d);
  renderTable(h);
  renderForecast(d.forecast, d.foodspring_url);
}

function renderTable(h) {
  $("#priceRows").innerHTML = [...h].reverse().map((r) => {
    const diff = r.diff == null ? "" : r.diff > 0 ? `<span class="up">▲ ${won(r.diff)}</span>`
      : r.diff < 0 ? `<span class="down">▼ ${won(-r.diff)}</span>` : "-";
    const wx = r.max_temp == null ? "" : `${r.rain_mm ? `비 ${r.rain_mm}mm · ` : ""}${Math.round(r.min_temp)}~${Math.round(r.max_temp)}℃`;
    const tags = (r.holiday ? `<span class="tag hol">${esc(r.holiday)}</span>` : "")
      + (r.events.length ? `<span class="tag" title="${esc(r.events.join(", "))}">행사 ${r.events.length}</span>` : "");
    return `<tr><td>${mmdd(r.date)}${tags}</td><td class="price">${won(r.kg_price)}</td><td>${diff}</td><td>${wx}</td></tr>`;
  }).join("");
}

function renderForecast(f, link) {
  if (!f || f.error) { $("#forecastCard").innerHTML = ""; return; }
  const maxAbs = Math.max(4, ...f.factors.map((x) => Math.abs(x.effect_pct)));
  $("#forecastCard").innerHTML = `
    <div class="fc-main">
      <span class="badge">다음 7일 예측 · 믿을 만한 정도 ${esc(f.confidence)}</span>
      <p class="dir ${cls(f.expected_change_pct, 2)}">${esc(f.direction)}</p>
      <p class="range">예상 ${won(f.expected_kg_price_range?.[0])} ~ ${won(f.expected_kg_price_range?.[1])} /kg<br>
        <span class="muted">${pct(f.range_pct[0])} ~ ${pct(f.range_pct[1])}</span></p>
      <p class="tip">${esc(f.suggestion)}</p>
      <a class="p-link" href="${esc(link)}" target="_blank" rel="noopener">식봄에서 ${esc(f.item)} 찾아보기 →</a>
    </div>
    <div>
      <h3 style="margin:0 0 8px;font-size:16px">왜 그렇게 봤나요?</h3>
      ${f.factors.map((x) => {
        const w = (Math.abs(x.effect_pct) / maxAbs) * 50;
        const style = x.effect_pct >= 0 ? `left:50%;width:${w}%;background:var(--up)` : `right:50%;width:${w}%;background:var(--down)`;
        return `<div class="factor"><span>${esc(x.factor)}</span><span class="bar"><i style="${style}"></i></span>
          <b class="${cls(x.effect_pct)}">${pct(x.effect_pct)}</b><span class="detail">${esc(x.detail)}</span></div>`;
      }).join("")}
      <p class="muted" style="margin-top:8px">${esc(f.method)}</p>
    </div>`;
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
      ctx.fillRect(x.getPixelForValue(i) - step / 2, a.top, step, 8);
    });
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = "#E2453C";
    ctx.fillStyle = "#E2453C";
    ctx.font = "11px Noto Sans KR";
    (opts.holidays || []).forEach(({ i, name }) => {
      const px = x.getPixelForValue(i);
      ctx.beginPath(); ctx.moveTo(px, a.top + 10); ctx.lineTo(px, a.bottom); ctx.stroke();
      ctx.fillText(name, px + 3, a.top + 22);
    });
    ctx.restore();
  },
};

function drawChart(d) {
  const h = d.history;
  const f = d.forecast;
  const labels = h.map((r) => mmdd(r.date));
  const price = h.map((r) => r.kg_price);
  const fcLine = h.map(() => null), lo = h.map(() => null), hi = h.map(() => null);
  if (h.length && f && !f.error && f.expected_kg_price_range) {
    const base = h.at(-1).kg_price;
    const mid = base * (1 + f.expected_change_pct / 100);
    fcLine[h.length - 1] = lo[h.length - 1] = hi[h.length - 1] = base;
    const start = new Date(h.at(-1).date);
    for (let k = 1; k <= 7; k++) {
      const day = new Date(start.getTime() + k * 864e5).toISOString().slice(0, 10);
      labels.push(mmdd(day));
      price.push(null);
      fcLine.push(k === 7 ? mid : null);
      lo.push(k === 7 ? f.expected_kg_price_range[0] : null);
      hi.push(k === 7 ? f.expected_kg_price_range[1] : null);
    }
  }
  const rain = labels.map((_, i) => h[i]?.rain_mm ?? null);
  const eventCounts = labels.map((_, i) => h[i]?.events.length ?? 0);
  const hols = h.map((r, i) => (r.holiday ? { i, name: r.holiday } : null)).filter(Boolean);

  const ctx = $("#priceChart").getContext("2d");
  const grad = ctx.createLinearGradient(0, 0, 0, 320);
  grad.addColorStop(0, "rgba(91, 194, 54, 0.30)");
  grad.addColorStop(1, "rgba(91, 194, 54, 0.02)");

  if (chart) chart.destroy();
  chart = new Chart(ctx, {
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
        x: { grid: { display: false }, ticks: { maxTicksLimit: 8, color: "#8A918C" } },
        y: { position: "right", grid: { color: "#F0EDE6" }, ticks: { color: "#8A918C", callback: (v) => won(v) } },
        rain: { position: "left", display: false, min: 0, max: Math.max(40, ...rain.filter(Boolean)) * 4 },
      },
    },
    plugins: [overlayPlugin],
  });
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
    <div class="wx">${(w.daily || []).map((d) => `<div>${mmdd(d.date)}<b>${Math.round(d.max_temp)}°</b>${d.rain_mm ? `☂ ${d.rain_mm}` : "-"}</div>`).join("")}</div>`;
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
let sessionId = null;
try { sessionId = sessionStorage.getItem("salpi_sid"); } catch (e) {}

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
  if (!body.children.length) addMsg("bot", "사장님, 오늘 대구 시세 살펴왔어요.\n아래 버튼을 누르거나 편하게 물어보세요.");
  $("#chatText").focus();
}
document.querySelectorAll("[data-open-chat]").forEach((b) => b.addEventListener("click", () =>
  chatEl.classList.contains("open") && b.id === "fab" ? closeChat() : openChat()));
function closeChat() { chatEl.classList.remove("open"); chatEl.setAttribute("aria-hidden", "true"); }
$("#chatClose").addEventListener("click", closeChat);

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
      body: JSON.stringify({ message: text, session_id: sessionId }) });
    const d = await r.json();
    sessionId = d.session_id;
    try { sessionStorage.setItem("salpi_sid", sessionId); } catch (e) {}
    typing.remove();
    addMsg("bot", d.reply);
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
loadContext();
if (location.hash === "#chat") openChat();   // 주소 끝에 #chat 을 붙이면 채팅창이 열린 채로 시작
