// 가상 사장님들의 6개월을 하루씩 돌려 행동 기록(event_logs 모양)을 만든다.
// 기본 단가의 채소 5종만 실제 값(2025년 1월 대구 북부도매 평균), 나머지는 전부 가상이다.

import { PERSONAS } from "./personas.mjs";

export const START = "2026-05-04";   // 월요일
export const WEEKS = 26;
const DAYS = WEEKS * 7;

// 채소 5종: data/raw/1103_daegu_bukbu_wholesale_202501.csv 의 kg당 가중 평균
// 나머지: salpi_agent/menu_cost.py 의 시연용 참고 단가
const CATALOG = [
  ["양파", 1261], ["대파", 1682], ["배추", 920], ["무", 1139], ["양배추", 1064],
  ["돼지고기 앞다리", 12800], ["배추김치", 3800], ["고춧가루", 14000], ["쌀", 2750], ["깐마늘", 11000],
  ["두부", 2400], ["콩나물", 3000], ["오징어", 15000], ["어묵", 6000], ["닭고기", 6500], ["햄", 9000],
];
const VOLATILE = 5;   // 앞의 5종만 시세가 크게 움직임

const HOLIDAYS = new Set(["2026-05-05", "2026-05-25", "2026-06-03", "2026-06-06", "2026-08-15", "2026-08-17",
  "2026-09-24", "2026-09-25", "2026-09-26", "2026-10-03", "2026-10-05", "2026-10-09"]);
const RAIN_CHANCE = [0.25, 0.25, 0.35, 0.35, 0.3, 0.2];   // 5~10월 비 올 확률 (가상)
const WEEKDAY_SALES = [0, 0.85, 0.9, 0.95, 1.0, 1.25, 1.2];   // 일~토 (일요일 휴무)

function rng(seed) {
  let a = seed >>> 0;
  const next = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  next.normal = (sd = 1) => Math.sqrt(-2 * Math.log(next() || 1e-9)) * Math.cos(2 * Math.PI * next()) * sd;
  next.chance = (p) => next() < p;
  return next;
}

export function dateOf(t) {
  const d = new Date(`${START}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + t);
  return d.toISOString().slice(0, 10);
}

// 시세: 기준가로 돌아오려는 움직임 + 매일 흔들림. 앞날 전망은 실제 7일 뒤 변화에 오차를 섞은 값
function buildMarket(r) {
  const prices = CATALOG.map(([, base], i) => {
    const sd = i < VOLATILE ? 0.035 : 0.006;
    const series = [];
    let x = 0;
    for (let t = 0; t < DAYS + 8; t++) {
      x = x * 0.93 + r.normal(sd);
      series.push(Math.round(base * Math.exp(x)));
    }
    return series;
  });
  const outlook = prices.map((s) => s.map((p, t) => (t + 7 < s.length ? (s[t + 7] / p - 1) * 100 + r.normal(3) : 0)));
  return { prices, outlook };
}

function simulateStore(p, market, weather, r, allReceipts) {
  const events = [], orders = [];
  const log = (t, event_type, payload = {}) => events.push({ store_id: p.id, event_type, payload, date: dateOf(t), t });

  // 품목 고르기: 채소 앞쪽부터 품목 수만큼, 금액 비중은 고르게
  const picked = CATALOG.map((_, i) => i).slice(0, p.items);
  const dailySpend = p.weekly / 6;
  const avg = picked.map((i) => (dailySpend / p.items) / CATALOG[i][1]);   // 평일 평균 하루 사용량(kg)
  const stock = avg.map((a) => a * 4);
  const gap = p.plan.every ?? 7 / p.plan.days.length;   // 평소 발주 간격

  const nextPlan = (t) => {
    if (p.plan.every) return t + Math.max(1, Math.round(p.plan.every + r.normal(p.plan.spread)));
    for (let k = t + 1; ; k++) {
      if (p.plan.days.includes(new Date(`${dateOf(k)}T00:00:00Z`).getUTCDay())) return k + (r.chance(p.plan.slip) ? 1 : 0);
    }
  };

  let planned = nextPlan(-1);
  let lastAlert = -9;
  const pendingReceipts = [];
  const nextVisitDay = r() * 30 | 0;

  const place = (t, lines, recTotal) => {
    const amount = lines.reduce((s, l) => s + l.amount, 0);
    const order = { store_id: p.id, t, date: dateOf(t), amount, lines };
    orders.push(order);
    let chance = allReceipts ? 1 : p.log;
    if (p.declineWeek && t >= p.declineWeek * 7) chance *= Math.max(0, 1 - (t / 7 - p.declineWeek) / (p.stopWeek - p.declineWeek));
    if (p.stopWeek && t >= p.stopWeek * 7) chance = 0;
    if (p.monthly) pendingReceipts.push({ order, recTotal });
    else if (r.chance(chance)) writeReceipt(t, order);
  };
  const writeReceipt = (t, order) => {
    log(t, "receipt_upload", { ocr_items: order.lines.length, purchased_on: order.date });
    log(t, "order_placed", { purchased_on: order.date, amount: order.amount, supplier: "도매상", source: "receipt",
      items: order.lines.map((l) => ({ item: l.item, qty: +l.qty.toFixed(1), amount: l.amount })) });
  };

  for (let t = 0; t < DAYS; t++) {
    const date = dateOf(t), wd = new Date(`${date}T00:00:00Z`).getUTCDay();
    const open = wd !== 0 && !["2026-09-24", "2026-09-25", "2026-09-26"].includes(date);
    const fade = p.declineWeek && t >= p.declineWeek * 7 ? Math.max(0.05, 1 - (t / 7 - p.declineWeek) / (p.stopWeek - p.declineWeek)) : 1;

    // 접속
    let visited = p.monthly ? t % 30 === nextVisitDay : r.chance(p.visit * fade);

    // 알림: 가게가 쓰는 품목의 전망이 크게 움직이면 하루 1건 (5일 간격)
    if (t - lastAlert >= 5) {
      const hit = picked.filter((i) => i < VOLATILE && Math.abs(market.outlook[i][t]) >= 8);
      if (hit.length) {
        const i = hit[0], up = market.outlook[i][t] > 0;
        lastAlert = t;
        log(t, "alert_sent", { kind: up ? "가격 급등" : "기다리기", item: CATALOG[i][0] });
        if (r.chance(p.click * fade)) {
          visited = true;
          log(t, "alert_clicked", { kind: up ? "가격 급등" : "기다리기", minutes: Math.round(5 + r() * 180) });
          if (!up && planned - t <= 3 && r.chance(p.wait)) planned += 2;
        }
      }
    }

    if (visited) {
      log(t, "app_open");
      log(t, "forecast_view", { menu: "오늘 시세" });
      if (r.chance(0.2)) log(t, "deeplink_click", { seller: "식봄" });
      if (r.chance(0.05)) log(t, "feedback_rating", { stars: 3 + Math.floor(r() * 3) });
      if (p.monthly) {
        const last = pendingReceipts.at(-1);
        if (last) writeReceipt(t, last.order);
        pendingReceipts.length = 0;
      }
    }

    // 계획된 발주
    if (open && t >= planned) {
      const needs = avg.map((a) => a * gap);
      const rec = needs.map((n, k) => Math.max(0, n * 1.1 - stock[k]));
      const recTotal = rec.reduce((a, b) => a + b, 0);
      if (visited) log(t, "order_recommend_shown", { rec_total: +recTotal.toFixed(1) });
      const follow = visited && r.chance(p.accept);
      const lines = [];
      picked.forEach((i, k) => {
        const qty = follow ? rec[k] * (1 + r.normal(0.03)) : Math.max(0, needs[k] * p.cover * (1 + r.normal(0.12)));
        if (qty < 0.05) return;
        stock[k] += qty;
        lines.push({ item: CATALOG[i][0], qty, amount: Math.round(qty * market.prices[i][t]) });
      });
      if (lines.length) place(t, lines, recTotal);
      planned = nextPlan(t);
    }

    // 장사: 재고가 빠지고, 모자라면 소진
    if (open) {
      const mood = WEEKDAY_SALES[wd] * (HOLIDAYS.has(date) ? 0.7 : 1) * (weather[t] ? 0.9 : 1) * (1 + r.normal(0.1));
      const short = [];
      avg.forEach((a, k) => {
        stock[k] -= a * mood;
        if (stock[k] < 0) { short.push(k); stock[k] = 0; }
      });
      if (short.length && r.chance(p.report * fade)) {
        const k = short[0];
        log(t, "stockout_report", { item: CATALOG[picked[k]][0] });
        if (r.chance(p.urgent)) {
          const qty = avg[k] * 2;
          stock[k] += qty;
          place(t + 1 < DAYS ? t + 1 : t, [{ item: CATALOG[picked[k]][0], qty, amount: Math.round(qty * market.prices[picked[k]][t]) }], null);
        }
      }
      // 채소는 일주일 치를 넘게 쌓이면 상해서 폐기
      avg.forEach((a, k) => {
        if (picked[k] < VOLATILE && stock[k] > a * 7) {
          const waste = stock[k] - a * 7;
          stock[k] -= waste;
          if (r.chance(p.report)) log(t, "waste_report", { item: CATALOG[picked[k]][0], kg: +waste.toFixed(1) });
        }
      });
    }
  }
  return { events, orders };
}

// allReceipts: 영수증 누락이 없다고 가정 (누락 영향 비교용)
export function simulate(seed = 1, allReceipts = false) {
  const r = rng(seed);
  const market = buildMarket(r);
  const weather = Array.from({ length: DAYS }, (_, t) => r.chance(RAIN_CHANCE[Math.min(5, Math.floor(t / 30.5))]));
  const events = [], orders = [];
  for (const p of PERSONAS) {
    const out = simulateStore(p, market, weather, rng(seed * 1000 + p.id.charCodeAt(1) * 10 + p.id.charCodeAt(3)), allReceipts);
    events.push(...out.events);
    orders.push(...out.orders);
  }
  return { events, orders, days: DAYS };
}
