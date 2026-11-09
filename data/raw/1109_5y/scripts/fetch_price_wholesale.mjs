// 5년 치 가격·반입량 받기: node fetch_price_wholesale.mjs perday|sale
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "../../../..");
// .env는 저장소 루트(없으면 한 단계 위 폴더)에서 읽음. 키는 커밋하지 않음
const ENV_PATH = [path.join(REPO, ".env"), path.join(REPO, "../.env")].find((p) => fs.existsSync(p));
const OUT = path.resolve(HERE, "..");

const START = "2021-01-01", END = "2026-11-08";

const env = {};
for (const line of fs.readFileSync(ENV_PATH, "utf8").split(/\r?\n/)) {
  const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
  if (m) env[m[1]] = m[2].trim();
}
fs.mkdirSync(OUT, { recursive: true });

const ITEMS = { 양파: ["200","245"], 대파: ["200","246"], 배추: ["200","211"], 무: ["200","231"], 양배추: ["200","212"],
  감자: ["100","152"], 당근: ["200","232"], 애호박: ["200","224"], 오이: ["200","223"], 청양고추: ["200","242"],
  깻잎: ["200","253"], 상추: ["200","214"], 시금치: ["200","213"], 토마토: ["200","225"], 가지: ["200","251"],
  쌀: ["100","111"] };

const EN = { 양파: "onion", 대파: "green_onion", 배추: "napa_cabbage", 무: "radish", 양배추: "cabbage", 감자: "potato", 당근: "carrot", 애호박: "zucchini", 오이: "cucumber", 청양고추: "cheongyang_pepper", 깻잎: "perilla_leaf", 상추: "lettuce", 시금치: "spinach", 토마토: "tomato", 가지: "eggplant", 쌀: "rice" };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function getJson(url, params, key) {
  const qs = new URLSearchParams({ serviceKey: key, ...params });
  for (let t = 0; t < 8; t++) {
    try {
      const res = await fetch(`${url}?${qs}`, { signal: AbortSignal.timeout(60000) });
      const txt = await res.text();
      if (res.status === 429 || res.status >= 500) throw new Error(`HTTP ${res.status}`);
      const j = JSON.parse(txt);
      const code = j?.response?.header?.resultCode;
      if (code && code !== "0" && code !== "00") throw new Error(`result ${code} ${j.response.header.resultMsg}`);
      return j.response.body;
    } catch (e) {
      if (String(e).includes("LIMITED") || String(e).includes("22")) console.error("quota?", String(e));
      await sleep(2000 * 2 ** t);
      if (t === 7) throw e;
    }
  }
}
const items = (b) => { const it = b?.items?.item; return !it ? [] : Array.isArray(it) ? it : [it]; };
const csvEsc = (v) => { const s = String(v ?? "").trim(); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
const ymd = (d) => d.toISOString().slice(0, 10);

async function perday() {
  const url = env.AT_PERDAY_ENDPOINT + "/price";
  const cols = ["exmn_ymd","ctgry_nm","item_cd","item_nm","vrty_cd","vrty_nm","grd_nm","se_nm","mrkt_nm","unit","unit_sz","exmn_dd_prc"];
  for (const [name, [ctgry, item]] of Object.entries(ITEMS)) {
    const file = path.join(OUT, `1109_price_daily_${EN[name]}.csv`);
    if (fs.existsSync(file)) { console.log("skip", name); continue; }
    const rows = [];
    for (let y = 2021; y <= 2026; y++) {
      const s = `${y}0101`, e = y === 2026 ? END.replace(/-/g, "") : `${y}1231`;
      for (let p = 1; ; p++) {
        const b = await getJson(url, { returnType: "JSON", numOfRows: 1000, pageNo: p, "cond[exmn_ymd::GTE]": s,
          "cond[exmn_ymd::LTE]": e, "cond[ctgry_cd::EQ]": ctgry, "cond[item_cd::EQ]": item, "cond[sgg_cd::EQ]": env.AT_PERDAY_SGG_CD || "2200" },
          env.AT_PERDAY_API_KEY);
        const it = items(b); rows.push(...it);
        if (p * 1000 >= Number(b.totalCount || 0) || it.length === 0) break;
      }
    }
    fs.writeFileSync(file, "\uFEFF" + [cols.join(","), ...rows.map((r) => cols.map((c) => csvEsc(r[c])).join(","))].join("\n"));
    console.log(name, rows.length, "rows");
  }
}

// 반입량: 날짜별 전체 정산 → 품목(중분류·소분류)별 합계만 저장. 이어받기 가능
async function sale() {
  const url = env.AT_SALE_ENDPOINT + "/trades";
  const file = path.join(OUT, "1109_wholesale_qty_daily.csv");
  const done = new Set();
  if (fs.existsSync(file)) {
    for (const l of fs.readFileSync(file, "utf8").split("\n").slice(1)) if (l) done.add(l.slice(0, 10));
  } else fs.writeFileSync(file, "\uFEFFdate,lclsf,mclsf,sclsf,qty_kg,totprc,rows\n");
  const doneEmpty = path.join(OUT, "1109_wholesale_closed_days.txt");
  if (fs.existsSync(doneEmpty)) for (const l of fs.readFileSync(doneEmpty, "utf8").split("\n")) if (l) done.add(l);

  const days = [];
  for (let d = new Date(START); ymd(d) <= END; d.setUTCDate(d.getUTCDate() + 1)) if (!done.has(ymd(d))) days.push(ymd(d));
  console.log("days to fetch", days.length);

  const one = async (day) => {
    const page = (n) => getJson(url, { returnType: "JSON", numOfRows: 1000, pageNo: n,
      "cond[whsl_mrkt_cd::EQ]": env.AT_WHSL_MRKT_CD || "220001", "cond[trd_clcln_ymd::EQ]": day }, env.AT_SALE_API_KEY);
    const first = await page(1);
    const all = items(first);
    const pages = Math.ceil(Number(first.totalCount || 0) / 1000);
    for (let n = 2; n <= pages; n++) all.push(...items(await page(n)));
    if (!all.length) { fs.appendFileSync(doneEmpty, day + "\n"); return; }
    const agg = new Map();
    for (const r of all) {
      const k = [r.gds_lclsf_nm, r.gds_mclsf_nm, r.gds_sclsf_nm].map((s) => String(s ?? "").trim()).join("|");
      const a = agg.get(k) || { q: 0, p: 0, n: 0 };
      // unit_tot_qty는 단위(unit_nm)가 kg일 때 kg. 그 외 단위는 그대로 합산(행 수로 구분 가능)
      a.q += Number(r.unit_tot_qty || 0); a.p += Number(r.totprc || 0); a.n++;
      agg.set(k, a);
    }
    const lines = [...agg].map(([k, a]) => [day, ...k.split("|"), a.q.toFixed(1), a.p.toFixed(0), a.n].map(csvEsc).join(","));
    fs.appendFileSync(file, lines.join("\n") + "\n");
  };

  let i = 0, fin = 0;
  const worker = async () => { while (i < days.length) { const d = days[i++]; await one(d); if (++fin % 50 === 0) console.log("done", fin, d); } };
  await Promise.all([worker(), worker(), worker()]);
  console.log("sale finished");
}

const mode = process.argv[2];
await (mode === "perday" ? perday() : sale());
