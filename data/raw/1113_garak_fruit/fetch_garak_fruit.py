"""서울 가락시장 과일 경락 결과 받기 (aT 정산정보 katSale/trades) — 과일 예측에 '가락 값이 먼저 움직이나' 채점용.
실행: salpi_agent/.venv/Scripts/python.exe data/raw/1113_garak_fruit/fetch_garak_fruit.py
- 대분류 06 과실류 · 08 과일과채류만 받음 (하루 3번 호출 정도)
- 날짜 · 대분류 · 품목 · 품종 · 등급별로 합쳐 저장 (qty_kg = unit_tot_qty 합, totprc = 금액 합). 끊겨도 이어받기
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
START, END = date(2023, 1, 1), date(2026, 11, 12)
OUT = HERE / "1113_garak_fruit_daily.csv"
CLOSED = HERE / "1113_garak_closed_days.txt"

def get(params):
    for t in range(8):
        try:
            r = requests.get(URL, params={"serviceKey": KEY, "returnType": "JSON", **params}, timeout=60)
            if r.status_code == 429 or r.status_code >= 500: raise RuntimeError(f"HTTP {r.status_code}")
            j = r.json(); code = j["response"]["header"].get("resultCode")
            if code not in ("0", "00", None): raise RuntimeError(f"result {code} {j['response']['header'].get('resultMsg')}")
            b = j["response"]["body"]; it = b.get("items")
            it = it.get("item") if isinstance(it, dict) else it
            return int(b.get("totalCount") or 0), (it if isinstance(it, list) else [it] if it else [])
        except Exception as e:
            if t == 7: raise
            time.sleep(2 * 2 ** t)

def one(day):
    rows = []
    for lc in ("06", "08"):
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
    if OUT.exists():
        with open(OUT, encoding="utf-8-sig") as f: done |= {r["date"] for r in csv.DictReader(f)}
    else:
        OUT.write_text("\ufeffdate,lclsf,mclsf,sclsf,grade,qty_kg,totprc,rows\n", encoding="utf-8")
    if CLOSED.exists(): done |= set(CLOSED.read_text(encoding="utf-8").split())
    days = [START + timedelta(i) for i in range((END - START).days + 1)]
    days = [d for d in days if d.isoformat() not in done and d.weekday() != 6]   # 일요일은 대부분 휴장
    print("받을 날짜", len(days), flush=True)
    fin = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        for day, agg in pool.map(one, days):
            if not agg:
                with open(CLOSED, "a", encoding="utf-8") as f: f.write(day.isoformat() + "\n")
            else:
                with open(OUT, "a", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    for (lc, mc, sc, g), (q, p, n) in agg.items(): w.writerow([day.isoformat(), lc, mc, sc, g, f"{q:.1f}", f"{p:.0f}", n])
            fin += 1
            if fin % 50 == 0: print("완료", fin, day, flush=True)
    print("끝", flush=True)

if __name__ == "__main__":
    main()
