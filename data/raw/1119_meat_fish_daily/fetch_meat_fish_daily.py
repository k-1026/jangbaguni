"""대구 고기 · 수산물 일별 가격의 빈 기간 받기 (aT 일별 도·소매 가격 perDay, KAMIS 조사가) — 고기 · 수산물 AI 학습(M3 · R3)용.
실행 (저장소 맨 위 폴더에서): python data/raw/1119_meat_fish_daily/fetch_meat_fish_daily.py
- 품목: 살피 앱이 쓰는 고기 · 수산물 15개 (salpi_agent/sources/data_sources.py 의 EXTRA_ITEMS 그대로)
- 기간: 육류 2022-05-01 ~ 어제, 수산물 2025-09-01 ~ 어제 (1112 합본 자료에 없는 기간)
- 품목 × 한 달씩 불러 받은 그대로 저장 (소매 · 중도매 · 등급 모두). 호출은 모두 합쳐 약 500번이라 한 번에 끝남
- 끊겨도 다시 실행하면 끝난 달은 건너뛰고, 같은 줄은 두 번 저장하지 않음
- 키는 .env 의 AT_PERDAY_API_KEY (커밋하지 않음)"""
import csv, os, sys, time
from datetime import date, timedelta
from pathlib import Path
import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "salpi_agent"))
for p in (REPO / ".env", REPO.parent / ".env", REPO / "salpi_agent" / ".env"):
    if p.exists(): load_dotenv(p)
from sources.data_sources import EXTRA_ITEMS, DAEGU_SGG   # noqa: E402  (품목 코드를 앱과 같게)

KEY = os.getenv("AT_PERDAY_API_KEY", "").strip()
URL = (os.getenv("AT_PERDAY_ENDPOINT") or "https://apis.data.go.kr/B552845/perDay") + "/price"
STARTS = {"육류": date(2022, 5, 1), "수산물": date(2025, 9, 1)}
END = date.today() - timedelta(1)
OUT = HERE / "1119_meat_fish_daily_daegu.csv"
DONE = HERE / "1119_done_months.txt"   # 다 받은 (품목, 달) — 이번 달은 아직 안 끝나서 적지 않음
COLS = ["date", "group", "name", "ctgry_cd", "item_cd", "item_nm", "vrty_cd", "vrty_nm", "se_nm", "grd_cd", "grd_nm",
        "unit", "unit_sz", "price", "cnvs_price", "mrkt_nm"]


def get(params):
    for t in range(6):
        try:
            r = requests.get(URL, params={"serviceKey": KEY, "returnType": "JSON", **params}, timeout=60)
            if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in r.text: sys.exit("오늘 호출 한도에 걸렸어요. 내일 다시 실행하면 이어서 받아요.")
            if r.status_code == 429 or r.status_code >= 500: raise RuntimeError(f"HTTP {r.status_code}")
            j = r.json(); code = j["response"]["header"].get("resultCode")
            if code not in ("0", "00", None): raise RuntimeError(f"result {code} {j['response']['header'].get('resultMsg')}")
            b = j["response"]["body"]; it = b.get("items")
            it = it.get("item") if isinstance(it, dict) else it
            return int(b.get("totalCount") or 0), (it if isinstance(it, list) else [it] if it else [])
        except SystemExit:
            raise
        except Exception:
            if t == 5: raise
            time.sleep(2 * 2 ** t)


def months(start, end):
    m = start.replace(day=1)
    while m <= end:
        nxt = (m.replace(day=28) + timedelta(4)).replace(day=1)
        yield max(m, start), min(nxt - timedelta(1), end), nxt - timedelta(1) <= end
        m = nxt


def main():
    if not KEY: sys.exit(".env 에 AT_PERDAY_API_KEY 가 없어요")
    done = set(DONE.read_text(encoding="utf-8").split("\n")) if DONE.exists() else set()
    seen = set()
    if OUT.exists():
        with open(OUT, encoding="utf-8-sig") as f:
            seen = {(r["date"], r["name"], r["se_nm"], r["grd_cd"], r["mrkt_nm"]) for r in csv.DictReader(f)}
    else:
        with open(OUT, "w", encoding="utf-8-sig", newline="") as f: csv.writer(f).writerow(COLS)
    total = 0
    for name, cfg in EXTRA_ITEMS.items():
        got = 0
        for s, e, full in months(STARTS[cfg["group"]], END):
            tag = f"{name}|{s:%Y-%m}"
            if tag in done: continue
            base = {"numOfRows": 1000, "cond[exmn_ymd::GTE]": f"{s:%Y%m%d}", "cond[exmn_ymd::LTE]": f"{e:%Y%m%d}",
                    "cond[ctgry_cd::EQ]": cfg["ctgry"], "cond[item_cd::EQ]": cfg["item"], "cond[vrty_cd::EQ]": cfg["vrty"],
                    "cond[sgg_cd::EQ]": DAEGU_SGG}
            n, rows = get({**base, "pageNo": 1})
            for p in range(2, -(-n // 1000) + 1): rows += get({**base, "pageNo": p})[1]
            with open(OUT, "a", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                for r in rows:
                    d = str(r.get("exmn_ymd") or "")
                    d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                    k = (d, name, r.get("se_nm") or "", r.get("grd_cd") or "", r.get("mrkt_nm") or "")
                    if k in seen: continue
                    seen.add(k); got += 1
                    w.writerow([d, cfg["group"], name, r.get("ctgry_cd"), r.get("item_cd"), r.get("item_nm"), r.get("vrty_cd"),
                                r.get("vrty_nm"), r.get("se_nm"), r.get("grd_cd"), r.get("grd_nm"), r.get("unit"), r.get("unit_sz"),
                                r.get("exmn_dd_prc"), r.get("exmn_dd_cnvs_prc"), r.get("mrkt_nm")])
            if full:
                with open(DONE, "a", encoding="utf-8") as f: f.write(tag + "\n")
        total += got
        print(f"{cfg['group']} {name}: 새로 {got}줄", flush=True)
    print(f"끝 — 새로 {total}줄 저장 → {OUT.name}", flush=True)


if __name__ == "__main__":
    main()
