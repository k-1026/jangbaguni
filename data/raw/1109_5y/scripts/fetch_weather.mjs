// 기상청 ASOS 일자료 (대구 143). 실행: node fetch_weather.mjs 20210101 20261108
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "../../../..");
const ENV_PATH = [path.join(REPO, ".env"), path.join(REPO, "../.env")].find((p) => fs.existsSync(p));

const env = {};
for (const l of fs.readFileSync(ENV_PATH, "utf8").split(/\r?\n/)) {
  const m = l.match(/^([A-Z0-9_]+)=(.*)$/); if (m) env[m[1]] = m[2].trim();
}
const OUT = path.resolve(HERE, "../1109_weather_daegu_daily.csv");
const [START, END] = [process.argv[2], process.argv[3]]; // YYYYMMDD
const url = env.KMA_ASOS_ENDPOINT + "/getWthrDataList";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function get(params) {
  const qs = new URLSearchParams({ serviceKey: env.KMA_ASOS_API_KEY, dataType: "JSON", dataCd: "ASOS", dateCd: "DAY",
    stnIds: env.KMA_ASOS_STN_ID || "143", numOfRows: 999, ...params });
  for (let t = 0; t < 6; t++) {
    try {
      const res = await fetch(`${url}?${qs}`, { signal: AbortSignal.timeout(60000) });
      const j = JSON.parse(await res.text());
      const h = j.response.header;
      if (h.resultCode !== "00") throw new Error(`${h.resultCode} ${h.resultMsg}`);
      return j.response.body;
    } catch (e) { console.error("retry", String(e)); await sleep(2000 * 2 ** t); if (t === 5) throw e; }
  }
}

const rows = [];
// 1년씩 끊어서 요청 (한 번에 최대 999줄)
for (let y = Number(START.slice(0, 4)); y <= Number(END.slice(0, 4)); y++) {
  const s = y === Number(START.slice(0, 4)) ? START : `${y}0101`;
  const e = y === Number(END.slice(0, 4)) ? END : `${y}1231`;
  for (let p = 1; ; p++) {
    const b = await get({ startDt: s, endDt: e, pageNo: p });
    const it = b.items?.item ?? [];
    rows.push(...it);
    if (p * 999 >= Number(b.totalCount) || !it.length) break;
  }
  console.log(y, "누적", rows.length);
}
const cols = Object.keys(rows[0]);
const esc = (v) => { const s = String(v ?? ""); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
fs.writeFileSync(OUT, "\uFEFF" + [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n"));
console.log("saved", rows.length, "days", rows[0].tm, "~", rows.at(-1).tm, "cols", cols.length);
