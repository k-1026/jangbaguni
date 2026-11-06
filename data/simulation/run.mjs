// 실행: node data/simulation/run.mjs
// 1번 판의 기록과 분류 결과를 data/simulation/output/ 에 저장하고, 100판 평균 정답률을 report.md 로 남긴다.

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { PERSONAS } from "./personas.mjs";
import { TUNED, classifyImproved, classifyPpt, weeklyTimeline } from "./classify.mjs";
import { simulate } from "./simulate.mjs";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "output");
const SEEDS = 100;
const ids = PERSONAS.map((p) => p.id);
const lastDay = (days) => days - 1;

const correct = (p, label) => (p.truth === "활동 중" ? label !== "S5" : label === p.truth);
const changes = (list) => list.filter((v, i) => i && v !== list[i - 1]).length;

// 1) 100판 평균
const score = Object.fromEntries(ids.map((id) => [id, { ppt: 0, improved: 0, pptMoves: 0, improvedMoves: 0, s5Week: [] }]));
for (let seed = 1; seed <= SEEDS; seed++) {
  const { events, days } = simulate(seed);
  const a = classifyPpt(events, ids, lastDay(days)), b = classifyImproved(events, ids, lastDay(days));
  const line = weeklyTimeline(events, ids, days);
  for (const p of PERSONAS) {
    if (correct(p, a[p.id].label)) score[p.id].ppt++;
    if (correct(p, b[p.id].label)) score[p.id].improved++;
    score[p.id].pptMoves += changes(line.ppt[p.id]);
    score[p.id].improvedMoves += changes(line.improved[p.id]);
    const firstS5 = line.improved[p.id].indexOf("S5");
    if (firstS5 >= 0) score[p.id].s5Week.push(firstS5 + 8);
  }
}

// 2) 1번 판 상세
const one = simulate(1);
const a = classifyPpt(one.events, ids, lastDay(one.days)), b = classifyImproved(one.events, ids, lastDay(one.days));
const line = weeklyTimeline(one.events, ids, one.days);
const actual = Object.fromEntries(ids.map((id) => [id, one.orders.filter((o) => o.store_id === id).length]));
const n = (v, d = 2) => (v === null || v === undefined ? "-" : (+v).toFixed(d));

const rows = PERSONAS.map((p) => {
  const x = b[p.id].metrics, s = score[p.id];
  return { 사장님: `${p.id} ${p.name}`, 정답: p.truth, 실제발주: actual[p.id], 기록된발주: x.records, 발표기준: a[p.id].label, 보완기준: b[p.id].label,
    발표정답: `${s.ppt}%`, 보완정답: `${s.improved}%`, F: n(x.f), M: Math.round(x.m / 10000), V: x.v, C: n(x.c), A: n(x.a), P: n(x.p), E: n(x.e), 주당소진: n(x.reportsPerWeek), R: x.r,
    발표변동: n(s.pptMoves / SEEDS, 1), 보완변동: n(s.improvedMoves / SEEDS, 1) };
});
console.table(rows);
const total = (key) => PERSONAS.reduce((t, p) => t + score[p.id][key], 0) / PERSONAS.length;
console.log(`10명 평균 정답률 (${SEEDS}판): 발표기준 ${total("ppt").toFixed(0)}% / 보완기준 ${total("improved").toFixed(0)}%`);
const s5 = score["S5-A"].s5Week;
if (s5.length) console.log(`S5-A 이탈 첫 감지: 평균 ${(s5.reduce((x, y) => x + y, 0) / s5.length).toFixed(1)}주차 (${s5.length}/${SEEDS}판)`);

// 3) 조건별 비교: 조정값은 조정에 쓰지 않은 101~200번 판으로 평가
function rate(from, to, classify, allReceipts = false) {
  const hit = Object.fromEntries(ids.map((id) => [id, 0]));
  for (let seed = from; seed <= to; seed++) {
    const { events, days } = simulate(seed, allReceipts);
    const out = classify(events, days);
    for (const p of PERSONAS) if (correct(p, out[p.id].label)) hit[p.id]++;
  }
  const per = ids.map((id) => Math.round((hit[id] / (to - from + 1)) * 100));
  return { per, avg: Math.round(per.reduce((a, b) => a + b, 0) / per.length) };
}
const ppt = (e, d) => classifyPpt(e, ids, lastDay(d));
const better = (e, d) => classifyImproved(e, ids, lastDay(d));
const tuned = (e, d) => classifyImproved(e, ids, lastDay(d), TUNED);
const compare = [
  ["발표 기준", rate(101, 200, ppt)],
  ["보완 기준", rate(101, 200, better)],
  ["보완 + 기준값 조정", rate(101, 200, tuned)],
  ["보완 + 조정 + 영수증 누락 없음", rate(101, 200, tuned, true)],
];
console.log(`
새 100판 (${ids.join(" ")})`);
for (const [name, x] of compare) console.log(`${name}: 평균 ${x.avg}% | ${x.per.join(" ")}`);

const keys = Object.keys(rows[0]);
const table = [`| ${keys.join(" | ")} |`, `|${keys.map(() => "---").join("|")}|`, ...rows.map((r) => `| ${keys.map((k) => r[k]).join(" | ")} |`)].join("\n");
const timeline = PERSONAS.map((p) => `- ${p.id}: 발표 ${line.ppt[p.id].join(" ")}\n- ${p.id}: 보완 ${line.improved[p.id].join(" ")}`).join("\n");

mkdirSync(OUT, { recursive: true });
writeFileSync(join(OUT, "report.md"), `# 시뮬레이션 결과\n\n발표/보완 분류는 1번 판, 정답률은 ${SEEDS}판 평균.\n\n${table}\n\n## 조건별 정답률 (조정에 안 쓴 101~200번 판)\n${compare.map(([name, x]) => `- ${name}: 평균 ${x.avg}% (${ids.map((id, i) => `${id} ${x.per[i]}%`).join(", ")})`).join("\n")}\n\n## 주별 세그먼트 (1번 판, 8주차부터)\n${timeline}\n`);
writeFileSync(join(OUT, "event_logs.csv"), "store_id,event_type,date,payload\n" + one.events.map((e) =>
  [e.store_id, e.event_type, e.date, `"${JSON.stringify(e.payload).replaceAll('"', '""')}"`].join(",")).join("\n"));
console.log(`기록 ${one.events.length}건 저장: ${OUT}`);
