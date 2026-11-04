// 실행: node simulation/blend.mjs
// 한 유형만 고르는 방식과 주 유형 + 보조 유형 방식을 어떤 조정에도 쓰지 않은 201~300번 판으로 비교한다.

import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { PERSONAS } from "./personas.mjs";
import { TUNED, classifyBlend, classifyImproved } from "./classify.mjs";
import { simulate } from "./simulate.mjs";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "output", "blend_report.md");
const FROM = 201, TO = 300, N = TO - FROM + 1;
const ids = PERSONAS.map((p) => p.id);
const stat = Object.fromEntries(ids.map((id) => [id, { single: 0, primary: 0, either: 0, hold: 0, second: 0, wrongTwo: 0 }]));

for (let seed = FROM; seed <= TO; seed++) {
  const { events, days } = simulate(seed);
  const one = classifyImproved(events, ids, days - 1, TUNED);
  const two = classifyBlend(events, ids, days - 1);
  for (const p of PERSONAS) {
    const s = stat[p.id], { primary, secondary } = two[p.id];
    const away = p.truth === "활동 중";
    const labels = [primary, secondary].filter(Boolean);
    const inside = away ? !labels.includes("S5") : labels.includes(p.truth);
    if (away ? one[p.id].label !== "S5" : one[p.id].label === p.truth) s.single++;
    if (away ? primary !== "S5" : primary === p.truth) s.primary++;
    if (inside) s.either++;
    if (primary === "판단 보류" && !secondary) s.hold++;
    if (secondary) s.second++;
    if (!inside && primary !== "판단 보류") s.wrongTwo++;
  }
}

const rows = PERSONAS.map((p) => {
  const s = stat[p.id];
  return { 사장님: p.id, 정답: p.truth, "한 유형": s.single, "주 유형": s.primary, "주+보조 안에 정답": s.either, "보조 있음": s.second, "완전 보류": s.hold, "확실히 틀림": s.wrongTwo };
});
const keys = Object.keys(rows[0]);
const sum = (k) => Math.round(rows.reduce((a, r) => a + r[k], 0) / rows.length);
console.table(rows);
const summary = keys.slice(2).map((k) => `${k} ${sum(k)}%`).join(" / ");
console.log(`평균: ${summary}`);
writeFileSync(OUT, `# 주 유형 + 보조 유형 비교\n\n${FROM}~${TO}번 판 ${N}회, 단위 %.\n\n| ${keys.join(" | ")} |\n|${keys.map(() => "---").join("|")}|\n${rows.map((r) => `| ${keys.map((k) => r[k]).join(" | ")} |`).join("\n")}\n\n평균: ${summary}\n`);
