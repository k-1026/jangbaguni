"""대구 소매가 ÷ 도매가 비율을 품목별로 계산 (가상 구매 기록의 '시장에서 산 값' 마진율 근거).

실행 (salpi_agent 폴더에서):  python -m experiments.retail_wholesale_ratio   (경락가 연결은 .env 의 AT_SALE_* 필요, 없으면 건너뜀)

- 자료: data/raw/1109_5y/1109_price_daily_*.csv (aT 일별 도·소매가 = KAMIS 조사, 대구, 2021-01 ~ 2026-11-06)
- 도매 = 북부도매 중도매 '상품' · 소매 = 대구 소매 '상품'(조사한 곳 평균, analysis.retail_series 와 같은 방식)
- 모두 units.per_base_price 로 kg당으로 바꿈. 포기 · 개로 파는 소매는 환산표(units.PIECE_KG)를 거치므로 '약'
- 날짜마다 소매 ÷ 중도매를 구하고 품목마다 중앙값 · 4분위를 냄
- 경락가 연결: 중도매 조사가 ÷ 북부도매 경락가를 겹치는 날(최근 35일 안)로 구해 곱함 (소매 ÷ 경락 = 소매 ÷ 중도매 × 중도매 ÷ 경락)
- 결과: experiments/results/retail_wholesale_ratio.json
"""
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "salpi_agent" / ".env")

from price import units   # noqa: E402

DIR = ROOT / "data" / "raw" / "1109_5y"
OUT = Path(__file__).resolve().parent / "results" / "retail_wholesale_ratio.json"
# 품목 → 파일 이름 (가지는 도매 '상품' 조사가가 없어 뺌, 쌀 · 친환경은 대상 아님)
FILES = {"양배추": "cabbage", "당근": "carrot", "청양고추": "cheongyang_pepper", "오이": "cucumber", "대파": "green_onion",
         "상추": "lettuce", "배추": "napa_cabbage", "양파": "onion", "깻잎": "perilla_leaf", "감자": "potato", "무": "radish",
         "시금치": "spinach", "토마토": "tomato", "애호박": "zucchini"}


def kg_price(item, r):
    try:
        b = units.per_base_price(item, float(r["exmn_dd_prc"]), float(r["unit_sz"] or 1), r["unit"])
    except (TypeError, ValueError):
        return None, None
    return (b["price"], b["how"]) if b["unit"] == "kg" and b["price"] else (None, None)


def daily(item, fname):
    """날짜 → (소매 평균 kg당, 도매 kg당, 소매 환산이 '약'인가)"""
    whl, ret, approx = defaultdict(list), defaultdict(list), set()
    for r in csv.DictReader(open(DIR / f"1109_price_daily_{fname}.csv", encoding="utf-8-sig")):
        if r["grd_nm"] != "상품":
            continue
        if r["se_nm"] == "중도매" and r["mrkt_nm"] == "북부도매" and (r["unit"].startswith("kg") or r["unit"] == "g"):
            p, _ = kg_price(item, r)
            if p:
                whl[r["exmn_ymd"]].append(p)
        elif r["se_nm"] == "소매":
            p, how = kg_price(item, r)
            if p:
                ret[r["exmn_ymd"]].append(p)
                if how == "약":
                    approx.add(r["exmn_ymd"])
    return {d: (statistics.mean(ret[d]), statistics.mean(whl[d]), d in approx) for d in ret if d in whl}


def q(v, p):
    return statistics.quantiles(v, n=100, method="inclusive")[p - 1] if len(v) >= 2 else v[0]


def stats(ratios):
    return {"n": len(ratios), "median": round(statistics.median(ratios), 2), "p25": round(q(ratios, 25), 2), "p75": round(q(ratios, 75), 2)}


def auction_bridge(item, whl_by_day):
    """중도매 조사가 ÷ 북부도매 경락가 (겹치는 최근 날짜). 키가 없거나 못 받으면 None."""
    try:
        from price import analysis
        series = analysis.wholesale_series(item, 35)
    except Exception:   # noqa: BLE001 - 키 없음 · 네트워크 오류는 건너뜀
        return None
    r = [whl_by_day[s["date"].replace("-", "")] / s["kg_price"] for s in series if s["date"].replace("-", "") in whl_by_day]
    return {"n": len(r), "median": round(statistics.median(r), 2)} if len(r) >= 5 else None


def main():
    out = {}
    for item, fname in FILES.items():
        d = daily(item, fname)
        days = sorted(d)
        ratios = [d[x][0] / d[x][1] for x in days]
        recent = [d[x][0] / d[x][1] for x in days if x >= "20251107"]
        nov = [d[x][0] / d[x][1] for x in days if x[4:6] == "11"]
        res = {"days": len(days), "first": days[0], "last": days[-1], "approx_units": any(d[x][2] for x in days),
               "all": stats(ratios), "last_12m": stats(recent) if recent else None, "november": stats(nov) if nov else None,
               "bridge": auction_bridge(item, {x: d[x][1] for x in days})}
        if res["bridge"]:
            res["retail_over_auction_median"] = round(res["all"]["median"] * res["bridge"]["median"], 2)
        out[item] = res
        print(f"{item:<5} {res['days']:>5}일 전체 {res['all']['median']:.2f} (4분위 {res['all']['p25']:.2f}~{res['all']['p75']:.2f}) "
              f"최근12개월 {res['last_12m']['median'] if res['last_12m'] else '-'} 11월 {res['november']['median'] if res['november'] else '-'} "
              f"중도매/경락 {res['bridge']['median'] if res['bridge'] else '-'}{' (포기·개 환산 약)' if res['approx_units'] else ''}")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장:", OUT)


if __name__ == "__main__":
    main()
