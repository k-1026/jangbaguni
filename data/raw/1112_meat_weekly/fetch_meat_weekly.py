"""한우 등심 · 양지 · 돼지 앞다리 · 삼겹살: 주간 도매 경락가(협신식품 · 대구) + 대구 소매가 (2021-01 ~ 2026-11)

실행 (저장소 맨 위에서):  salpi_agent\\.venv\\Scripts\\python data/raw/1112_meat_weekly/fetch_meat_weekly.py
- 경락가: 축산물품질평가원 축산물경락가격정보 (.env 의 EKAPE_API_KEY). 기간을 넣으면 그 기간 평균 하나가 와서
  1주(월~금)씩 부름 → 요청 종류마다 약 310번 (하루 1,000번 한도 안). 이미 받은 주는 건너뜀 (중간에 끊겨도 다시 실행)
- 소매가: aT 일별 도·소매가 perDay (.env 의 AT_PERDAY_API_KEY), 대구 · 1등급(한우) — 화면과 같은 기준
- 결과: 1112_meat_weekly_2021-2026.csv  (week, item, auction_price, auction_count, retail_price)
  채점은 salpi_agent/backtest.py 가 이 파일을 읽음
"""
import csv
import os
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
load_dotenv(ROOT / ".env")
OUT = HERE / "1112_meat_weekly_2021-2026.csv"
CACHE = HERE / "_ekape_weeks.csv"            # 경락가 원본 주간 기록 (주 · 칸 · 가격 · 물량). 다시 실행하면 받은 주는 건너뜀
START, END = date(2021, 1, 4), date(2026, 11, 6)
MARKET = "0302"                               # 협신식품 (대구)
EKAPE = os.getenv("EKAPE_ENDPOINT", "http://data.ekape.or.kr/openapi-data/service/user/grade").rstrip("/")
PERDAY = os.getenv("AT_PERDAY_ENDPOINT", "https://apis.data.go.kr/B552845/perDay") + "/price"

# 품목 → (경락가 칸, 소매 perDay 품목 · 품종 · 등급)
ITEMS = {
    "한우 등심":       {"auction": ("beef", "등심"), "retail": ("500", "4301", "22", "3")},
    "한우 양지":       {"auction": ("beef", "양지"), "retail": ("500", "4301", "40", "3")},
    "돼지고기 앞다리": {"auction": ("pig", "등외제외"), "retail": ("500", "4304", "25", None)},
    "돼지고기 삼겹살": {"auction": ("pig", "등외제외"), "retail": ("500", "4304", "27", None)},
}


def get(url, params, xml=False):
    for t in range(6):
        try:
            r = requests.get(url, params=params, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(str(r.status_code))
            if xml:
                root = ET.fromstring(r.content)
                code = root.findtext(".//resultCode")
                if code not in (None, "00"):
                    sys.exit(f"축산물품질평가원 오류 {code} {root.findtext('.//resultMsg')} (하루 한도면 내일 다시 실행)")
                return [{c.tag: c.text for c in it} for it in root.iter("item")]
            return r.json()["response"]["body"]
        except (requests.RequestException, ET.ParseError, ValueError, KeyError):
            time.sleep(2 ** (t + 1))
    sys.exit(f"호출 실패: {url.rsplit('/', 1)[-1]}")


def num(v):
    try:
        return float(v) if v not in (None, "", "0") else None
    except ValueError:
        return None


def fetch_auction():
    done = {}
    if CACHE.exists():
        with open(CACHE, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                done[(r["week"], r["key"])] = (num(r["price"]), num(r["count"]))
    key = os.getenv("EKAPE_API_KEY", "").strip() or sys.exit(".env 의 EKAPE_API_KEY 가 비어 있어요")
    new = not CACHE.exists()
    with open(CACHE, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["week", "key", "price", "count"])
        week, n = START, 0
        while week <= END:
            wk = week.isoformat()
            if (wk, "pig|등외제외") not in done:
                p = {"serviceKey": key, "startYmd": week.strftime("%Y%m%d"), "endYmd": (week + timedelta(4)).strftime("%Y%m%d")}
                for x in get(f"{EKAPE}/auct/beefGrade", {**p, "abattCd": MARKET}, xml=True):
                    if x.get("cutmeatName") in ("등심", "양지"):
                        row = (num(x.get("hanAvg_2")), num(x.get("hanBoxCnt")))
                        done[(wk, f"beef|{x['cutmeatName']}")] = row
                        w.writerow([wk, f"beef|{x['cutmeatName']}", *row])
                for x in get(f"{EKAPE}/auct/pigGrade", p, xml=True):
                    if x.get("gradeNm") == "등외제외":
                        row = (num(x.get(f"c_{MARKET}Amt")), num(x.get(f"c_{MARKET}Cnt")))
                        done[(wk, "pig|등외제외")] = row
                        w.writerow([wk, "pig|등외제외", *row])
                done.setdefault((wk, "pig|등외제외"), (None, None))
                f.flush()
                n += 1
                if n % 20 == 0:
                    print(f"  경락가 {wk} 까지", flush=True)
                time.sleep(0.2)
            week += timedelta(7)
    return done


def fetch_retail():
    """주(월요일)별 소매 평균 kg당."""
    key = os.getenv("AT_PERDAY_API_KEY", "").strip() or sys.exit(".env 의 AT_PERDAY_API_KEY 가 비어 있어요")
    by = defaultdict(list)
    for item in sorted({c["retail"][1] for c in ITEMS.values()}):
        for y in range(START.year, END.year + 1):
            for page in range(1, 50):
                b = get(PERDAY, {"serviceKey": key, "returnType": "JSON", "numOfRows": 1000, "pageNo": page,
                                 "cond[exmn_ymd::GTE]": f"{y}0101", "cond[exmn_ymd::LTE]": f"{y}1231",
                                 "cond[ctgry_cd::EQ]": "500", "cond[item_cd::EQ]": item, "cond[sgg_cd::EQ]": "2200"})
                it = (b.get("items") or {}).get("item") or []
                it = [it] if isinstance(it, dict) else it
                for r in it:
                    if r.get("se_nm") != "소매":
                        continue
                    for name, cfg in ITEMS.items():
                        _, ic, vrty, grd = cfg["retail"]
                        if r.get("item_cd") == ic and r.get("vrty_cd") == vrty and (not grd or r.get("grd_cd") == grd):
                            d = date(int(r["exmn_ymd"][:4]), int(r["exmn_ymd"][4:6]), int(r["exmn_ymd"][6:]))
                            size = float(r.get("unit_sz") or 100)
                            by[(name, (d - timedelta(d.weekday())).isoformat())].append(float(r["exmn_dd_prc"]) / size * 1000)
                if page * 1000 >= int(b.get("totalCount") or 0):
                    break
            print(f"  소매 {item} {y}", flush=True)
    return {k: statistics.mean(v) for k, v in by.items()}


if __name__ == "__main__":
    print("경락가(주간) 받는 중 …")
    auction = fetch_auction()
    print("소매가 받는 중 …")
    retail = fetch_retail()
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["week", "item", "auction_price", "auction_count", "retail_price"])
        week = START
        while week <= END:
            wk = week.isoformat()
            for name, cfg in ITEMS.items():
                a = auction.get((wk, "|".join(cfg["auction"])), (None, None))
                r = retail.get((name, wk))
                w.writerow([wk, name, round(a[0]) if a[0] else "", round(a[1]) if a[1] else "", round(r) if r else ""])
            week += timedelta(7)
    print(f"저장: {OUT}")
