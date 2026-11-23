"""서울 가락시장 야채 경락 결과 받기 (aT 정산정보 katSale/trades) — '가락 값이 먼저 움직이나' 실험(M4 · R4)용.
실행 (저장소 맨 위 폴더에서): python data/raw/1119_garak_veg/fetch_garak_veg.py
- 받는 대분류: 05 서류 · 09 과채류 · 10 엽경채류 · 11 근채류 · 12 조미채소류 · 13 양채류 (2026-11-17 가락 응답으로 코드 확인)
- 기간: 2021-01-01 ~ 어제 (대구 북부도매 1109_5y 자료와 같은 시작일). 일요일은 대부분 휴장이라 뺌
- 날짜 · 대분류 · 품목 · 품종 · 등급별로 합쳐 연도별 파일에 저장 (qty_kg = unit_tot_qty 합, totprc = 금액 합)
- 하루 호출 한도(10,000건)에 걸리면 받은 데까지 저장하고 멈춤 → 다음 날 같은 명령을 다시 실행하면 이어받기
- 키는 .env 의 AT_SALE_API_KEY (커밋하지 않음)"""
import csv, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for p in (REPO / ".env", REPO.parent / ".env", REPO / "salpi_agent" / ".env"):
    if p.exists(): load_dotenv(p)
KEY = os.getenv("AT_SALE_API_KEY", "").strip()
URL = (os.getenv("AT_SALE_ENDPOINT") or "https://apis.data.go.kr/B552845/katSale") + "/trades"
MARKET = "110001"   # 서울가락
LCLSF = ("05", "09", "10", "11", "12", "13")
START, END = date(2021, 1, 1), date.today() - timedelta(1)
CLOSED = HERE / "1119_garak_closed_days.txt"
HEADER = "﻿date,lclsf,mclsf,sclsf,grade,qty_kg,totprc,rows\n"
out_of = lambda day: HERE / f"1119_garak_veg_daily_{day.year}.csv"   # 연도별로 나눔 (파일 하나가 너무 커지지 않게)


class LimitReached(RuntimeError):
    pass


def get(params):
    for t in range(8):
        try:
            r = requests.get(URL, params={"serviceKey": KEY, "returnType": "JSON", **params}, timeout=60)
            if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in r.text: raise LimitReached()
            if r.status_code == 429 or r.status_code >= 500: raise RuntimeError(f"HTTP {r.status_code}")
            j = r.json(); code = j["response"]["header"].get("resultCode")
            if code == "22": raise LimitReached()
            if code not in ("0", "00", None): raise RuntimeError(f"result {code} {j['response']['header'].get('resultMsg')}")
            b = j["response"]["body"]; it = b.get("items")
            it = it.get("item") if isinstance(it, dict) else it
            return int(b.get("totalCount") or 0), (it if isinstance(it, list) else [it] if it else [])
        except LimitReached:
            raise
        except Exception:
            if t == 7: raise
            time.sleep(2 * 2 ** t)


def one(day):
    rows = []
    for lc in LCLSF:
        base = {"numOfRows": 1000, "cond[whsl_mrkt_cd::EQ]": MARKET, "cond[trd_clcln_ymd::EQ]": day.isoformat(), "cond[gds_lclsf_cd::EQ]": lc}
        n, it = get({**base, "pageNo": 1}); rows += it
        for p in range(2, -(-n // 1000) + 1): rows += get({**base, "pageNo": p})[1]
    agg = {}
    for r in rows:
        k = tuple(str(r.get(f) or "").strip() for f in ("gds_lclsf_nm", "gds_mclsf_nm", "gds_sclsf_nm", "grd_nm"))
        a = agg.setdefault(k, [0.0, 0.0, 0])
        a[0] += float(r.get("unit_tot_qty") or 0); a[1] += float(r.get("totprc") or 0); a[2] += 1
    return day, agg


def main():
    if not KEY: sys.exit(".env 에 AT_SALE_API_KEY 가 없어요")
    done = set()
    for f in HERE.glob("1119_garak_veg_daily_*.csv"):
        with open(f, encoding="utf-8-sig") as fh: done |= {r["date"] for r in csv.DictReader(fh)}
    if CLOSED.exists(): done |= set(CLOSED.read_text(encoding="utf-8").split())
    days = [START + timedelta(i) for i in range((END - START).days + 1)]
    days = [d for d in days if d.isoformat() not in done and d.weekday() != 6]
    print(f"이미 받은 날 {len(done)}일 · 이번에 받을 날 {len(days)}일", flush=True)
    fin = 0
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            for day, agg in pool.map(one, days):
                if not agg:
                    with open(CLOSED, "a", encoding="utf-8") as f: f.write(day.isoformat() + "\n")
                else:
                    out = out_of(day)
                    if not out.exists(): out.write_text(HEADER, encoding="utf-8")
                    with open(out, "a", encoding="utf-8", newline="") as f:
                        w = csv.writer(f)
                        for (lc, mc, sc, g), (q, p, n) in agg.items(): w.writerow([day.isoformat(), lc, mc, sc, g, f"{q:.1f}", f"{p:.0f}", n])
                fin += 1
                if fin % 50 == 0: print(f"완료 {fin}/{len(days)}  ({day})", flush=True)
    except LimitReached:
        print(f"\n오늘 호출 한도에 걸렸어요. {fin}일 저장했어요. 내일 같은 명령을 다시 실행하면 이어서 받아요.", flush=True)
        return
    print(f"끝 — {fin}일 저장. 남은 날 없음", flush=True)


if __name__ == "__main__":
    main()
