// 행동 기록만 보고 세그먼트를 정한다. 정답(personas.mjs)은 읽지 않는다.
// ppt      : 발표자료 그대로 — 최근 8주, 상위 20% 같은 상대 순위
// improved : 보완 기준 — 8주 + 기록 6회 미만이면 최대 6개월, 최소 기록 수, 고정 기준값
// 발표자료에 숫자가 없는 '규칙적', 'V 높음'은 양쪽 다 C <= 0.4, 상위 40% 또는 12품목 이상으로 정했다.

const PRIORITY = ["S5", "S4", "S1", "S3", "S2"];
const LIMITS = { c: 0.4, a: 0.4, p: 0.3, f: 2, m: 2000000, v: 12, e: 0.5, stockout: 1 };   // 보완 기준 고정값 (결과를 보기 전에 정함)
export const TUNED = { ...LIMITS, c: 0.5, f: 1.5, stockout: 0.5 };   // 1차 결과를 보고 조정한 값 (평가는 조정에 안 쓴 판으로)

const mean = (x) => (x.length ? x.reduce((a, b) => a + b, 0) / x.length : null);
const median = (x) => (x.length ? [...x].sort((a, b) => a - b)[Math.floor(x.length / 2)] : null);
const stdev = (x) => { const m = mean(x); return Math.sqrt(mean(x.map((v) => (v - m) ** 2))); };
const gaps = (days) => days.slice(1).map((d, i) => d - days[i]);

const orderDay = (e) => Math.round((Date.parse(e.payload.purchased_on) - Date.parse(e.date)) / 864e5) + e.t;

function metrics(all, today, startDay, spanWeeks) {
  const seen = all.filter((e) => e.t <= today);
  const inWindow = (e) => e.t > startDay;
  const orders = seen.filter((e) => e.event_type === "order_placed" && orderDay(e) > startDay);
  const days = [...new Set(orders.map(orderDay))].sort((a, b) => a - b);
  const count = (type) => seen.filter((e) => e.event_type === type && inWindow(e));

  const allDays = [...new Set(seen.filter((e) => e.event_type === "order_placed").map(orderDay))].sort((a, b) => a - b);
  const lastRecord = allDays.at(-1) ?? null;
  const intervals = gaps(days);
  const shown = count("order_recommend_shown");
  const matched = shown.map((s) => {
    const o = orders.find((e) => orderDay(e) === s.t);
    if (!o) return null;
    const qty = o.payload.items.reduce((a, i) => a + i.qty, 0);
    return Math.abs(qty / (s.payload.rec_total || 1e-9) - 1) <= 0.1;
  }).filter((x) => x !== null);

  const sent = count("alert_sent"), clicked = count("alert_clicked");
  const waits = sent.filter((e) => e.payload.kind === "기다리기");
  const usual = median(intervals);
  const delayed = waits.filter((w) => {
    const before = allDays.filter((d) => d <= w.t).at(-1), after = allDays.find((d) => d > w.t);
    return before != null && after != null && usual != null && after - before > usual * 1.4;
  });
  const clickRate = sent.length ? clicked.length / sent.length : null;
  const delayRate = waits.length ? delayed.length / waits.length : null;

  const reports = count("stockout_report");
  const fast = reports.filter((s) => allDays.some((d) => d >= s.t && d <= s.t + 1));
  const views = (from, to) => seen.filter((e) => e.event_type === "forecast_view" && e.t > from && e.t <= to).length;

  return {
    orders: days.length,
    r: lastRecord === null ? null : today - lastRecord,
    f: days.length / spanWeeks,
    m: orders.reduce((a, e) => a + e.payload.amount, 0) / spanWeeks,
    v: new Set(orders.flatMap((e) => e.payload.items.map((i) => i.item))).size,
    c: intervals.length >= 2 ? stdev(intervals) / mean(intervals) : null,
    a: matched.length ? matched.filter(Boolean).length / matched.length : null,
    aN: matched.length,
    p: clickRate === null ? null : mean([clickRate, delayRate ?? 0]),
    pN: sent.length,
    e: reports.length ? fast.length / reports.length : null,
    eN: reports.length,
    reportsPerWeek: reports.length / spanWeeks,
    usualGap: mean(intervals),
    medianGap: median(gaps(allDays)),
    records: allDays.length,
    viewsDown: views(today - 28, today) < views(today - 56, today - 28),
  };
}

// 상위 share 안에 드는지. 값이 없는 매장은 순위에서 뺀다
function topShare(rows, key, share, id) {
  const ranked = rows.filter((r) => r.x[key] !== null).sort((a, b) => b.x[key] - a.x[key]);
  const cut = Math.max(1, Math.round(ranked.length * share));
  return ranked.slice(0, cut).some((r) => r.id === id);
}
function bottomShare(rows, key, share, id) {
  const ranked = rows.filter((r) => r.x[key] !== null).sort((a, b) => a.x[key] - b.x[key]);
  const cut = Math.max(1, Math.round(ranked.length * share));
  return ranked.slice(0, cut).some((r) => r.id === id);
}

export function classifyPpt(events, ids, today) {
  const rows = ids.map((id) => ({ id, x: metrics(events.filter((e) => e.store_id === id), today, today - 56, 8) }));
  const result = {};
  for (const { id, x } of rows) {
    const hit = {
      S5: x.usualGap !== null && x.r !== null && x.r > x.usualGap * 2 && x.viewsDown,
      S4: topShare(rows, "e", 0.2, id) && x.reportsPerWeek >= 1,
      S1: topShare(rows, "p", 0.2, id) && x.f >= 2,
      S3: topShare(rows, "m", 0.2, id) && x.f <= 1 && (topShare(rows, "v", 0.4, id)),
      S2: x.c !== null && x.c <= LIMITS.c && bottomShare(rows, "a", 0.4, id),
    };
    result[id] = { label: PRIORITY.find((s) => hit[s]) ?? "미분류", metrics: x };
  }
  return result;
}

export function classifyImproved(events, ids, today, limits = LIMITS) {
  const result = {};
  for (const id of ids) {
    const mine = events.filter((e) => e.store_id === id);
    const records = [...new Set(mine.filter((e) => e.event_type === "order_placed" && e.t <= today).map(orderDay))]
      .filter((d) => d > today - 182).sort((a, b) => a - b);
    const in8 = records.filter((d) => d > today - 56);
    const start = in8.length >= 6 ? today - 56 : records.length >= 6 ? records.at(-6) - 1 : today - 182;
    const spanWeeks = Math.max(8, Math.min(26, (today - start) / 7));
    const x = metrics(mine, today, start, spanWeeks);

    if (today < 55 || records.length < 3) {
      const recentlyGone = x.medianGap !== null && x.r !== null && x.r > x.medianGap * 2 && x.records >= 4;
      result[id] = { label: recentlyGone ? "S5" : "판단 보류", metrics: x };
      continue;
    }
    const full = x.orders >= 6;   // 3~5회면 비율 지표는 쓰지 않음
    const ok = (key, n) => full && x[key] !== null && n >= 5;
    const hit = {
      S5: x.records >= 4 && x.r !== null && x.r > x.medianGap * 2,
      S4: ok("e", x.eN) && x.e >= limits.e && x.reportsPerWeek >= limits.stockout,
      S1: ok("p", x.pN) && x.p >= limits.p && x.f >= limits.f,
      S3: x.m >= limits.m && x.f <= 1 && x.v >= limits.v,
      S2: full && x.c !== null && x.c <= limits.c && ok("a", x.aN) && x.a <= limits.a,
    };
    result[id] = { label: PRIORITY.find((s) => hit[s]) ?? "판단 보류", metrics: x };
  }
  return result;
}

// 주 유형 + 보조 유형: 유형별로 기준에 얼마나 가까운지(1 이상이면 충족) 재서 순서를 정한다
const atLeast = (v, limit) => (v === null ? 0 : Math.min(2, v / limit));
const atMost = (v, limit) => (v === null ? 0 : Math.min(2, limit / Math.max(v, 0.01)));
const NEAR = 0.8;   // 보조 유형으로 인정하는 최소 근접도 (결과를 보기 전에 정함)

export function classifyBlend(events, ids, today, limits = TUNED) {
  const base = classifyImproved(events, ids, today, limits);
  const result = {};
  for (const id of ids) {
    const x = base[id].metrics;
    if (base[id].label === "S5") {
      result[id] = { primary: "S5", secondary: null, metrics: x };
      continue;
    }
    const full = x.orders >= 6 && today >= 55;
    const rate = (fit, n) => (full && n >= 5 ? fit : 0);
    const fits = {
      S4: Math.min(rate(atLeast(x.e, limits.e), x.eN), rate(atLeast(x.reportsPerWeek, limits.stockout), x.eN)),
      S1: Math.min(rate(atLeast(x.p, limits.p), x.pN), rate(atLeast(x.f, limits.f), x.pN)),
      S3: x.records >= 3 ? Math.min(atLeast(x.m, limits.m), atMost(x.f, 1), atLeast(x.v, limits.v)) : 0,
      S2: Math.min(full ? atMost(x.c, limits.c) : 0, rate(atMost(x.a, limits.a), x.aN)),
    };
    const ranked = Object.entries(fits).sort((a, b) => b[1] - a[1]);
    const [first, second] = ranked;
    result[id] = {
      primary: first[1] >= 1 ? first[0] : "판단 보류",
      secondary: first[1] >= 1 ? (second[1] >= NEAR ? second[0] : null) : (first[1] >= NEAR ? first[0] : null),
      metrics: x,
    };
  }
  return result;
}

// 주 1회 재계산. 보완 기준은 2번 연속 같을 때만 바꾸되 S5는 바로 반영
export function weeklyTimeline(events, ids, totalDays) {
  const ppt = Object.fromEntries(ids.map((id) => [id, []]));
  const improved = Object.fromEntries(ids.map((id) => [id, []]));
  const held = {}, pending = {};
  for (let today = 55; today < totalDays; today += 7) {
    const a = classifyPpt(events, ids, today), b = classifyImproved(events, ids, today);
    for (const id of ids) {
      ppt[id].push(a[id].label);
      const now = b[id].label;
      if (held[id] === undefined || now === "S5" || now === held[id] || pending[id] === now) held[id] = now;
      pending[id] = now;
      improved[id].push(held[id]);
    }
  }
  return { ppt, improved };
}
