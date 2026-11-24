"""'어디서 살까' 추천 평가: 도매가 예측 → 시장 · 식봄 중 어디가 더 쌌나 (가상 구매 기록 사용).

실행 (salpi_agent 폴더에서):  python -m experiments.where_to_buy        (.env 의 SUPABASE_* · AT_PERDAY_API_KEY 필요)

- 가상 구매 기록 (A안): 사장님이 시장에서 산 값 = 그날 대구 북부도매 중도매 '상품' 조사가 × (1 + 웃돈)
    웃돈 0% = 중도매가 그대로 (기본). 20% · 50%는 '소매에 가까울수록' 어떻게 달라지는지 보는 용도 (plan/forecast/1124_retail_wholesale_ratio.md 5절)
- 식봄 값: Supabase price_snapshots 의 kg당 값(품목마다 상품들의 가운데 값). 도매 기록 날짜에 가장 가까운 앞 기록을 씀
- 추천 규칙: 예측이 '내릴' → 시장 · '오를' → 식봄 · '비슷할' → 비교에서 뺌
- 값 차이 10% 안(비슷해요)은 채점에서 뺌 — 결과에 tie 0.0(안 뺌) · 0.1(뺌) 둘 다 냄
- 정답: 예측한 기준 날짜 + 7일 이후 사흘 안 첫 시세(forecast_log.score 와 같음)에서 더 싼 쪽
- 결과: experiments/results/where_to_buy.json · where_to_buy_purchases.csv (가상 구매 기록)
"""
import csv
import json
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from price import units   # noqa: E402
from price.forecast_log import LOOK_AHEAD   # noqa: E402
from sources import supabase_db   # noqa: E402
from sources.data_sources import ITEMS, perday_prices   # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
MARKUPS = (0.0, 0.2, 0.5)
TIE = 0.10   # 시장 · 식봄 값 차이가 이 안이면 '비슷해요'로 보고 채점에서 뺌 (units.py 와 같은 10%)
# 도매 '상품' 중도매 조사가가 없는 가지는 뺌
SKIP = {"가지"}


def market_series(item):
    """날짜 → 북부도매 중도매 상품 kg당 조사가 (최근 35일)"""
    by_day = defaultdict(list)
    for r in perday_prices(item, 35):
        if r.get("se_nm") != "중도매" or r.get("grd_nm") != "상품" or r.get("mrkt_nm") != "북부도매":
            continue
        if not (r.get("unit", "").startswith("kg") or r.get("unit") == "g"):
            continue
        try:
            b = units.per_base_price(item, float(r["exmn_dd_prc"]), float(r["unit_sz"] or 1), r["unit"])
        except (TypeError, ValueError):
            continue
        if b["unit"] == "kg" and b["price"]:
            by_day[f"{r['exmn_ymd'][:4]}-{r['exmn_ymd'][4:6]}-{r['exmn_ymd'][6:]}"].append(b["price"])
    return {d: statistics.mean(v) for d, v in by_day.items()}


def shop_series():
    """품목 → {날짜: 식봄 kg당 값의 가운데}"""
    by = defaultdict(lambda: defaultdict(list))
    for r in supabase_db.select("price_snapshots", source="eq.식봄", select="snap_date,item,price_per_kg"):
        if r["price_per_kg"]:
            by[r["item"]][r["snap_date"]].append(float(r["price_per_kg"]))
    return {i: {d: statistics.median(v) for d, v in days.items()} for i, days in by.items()}


def forecasts():
    rows = supabase_db.select("forecast_log", select="run_date,item,base_date,direction,formula_version")
    first = {}
    for r in sorted(rows, key=lambda r: r["run_date"]):
        first.setdefault((r["item"], r["base_date"]), r)
    return list(first.values())


def evaluate(market, shop, fc, markup, tie=0.0):
    rows = []
    for f in fc:
        item = f["item"]
        if item not in market or item not in shop:
            continue
        target = date.fromisoformat(f["base_date"]) + timedelta(7)
        hit = next((d for d in sorted(market[item]) if target <= date.fromisoformat(d) <= target + timedelta(LOOK_AHEAD)), None)
        snaps = [d for d in sorted(shop[item]) if d <= (hit or "")]
        if not hit or not snaps:
            continue
        m, s = market[item][hit] * (1 + markup), shop[item][snaps[-1]]
        rows.append({"item": item, "base_date": f["base_date"], "date": hit, "direction": f["direction"],
                     "market": round(m), "shop": round(s), "cheaper": "시장" if m < s else "식봄"})
    near = [r for r in rows if abs(r["market"] - r["shop"]) <= tie * min(r["market"], r["shop"])]   # 값이 비슷한 건 뺌
    used = [r for r in rows if r["direction"] != "flat" and r not in near]
    if not used:
        return {"markup": markup, "tie": tie, "n_all": len(rows), "n": 0}
    pick = lambda r: "시장" if r["direction"] == "down" else "식봄"   # noqa: E731
    cost = lambda r, where: r["market"] if where == "시장" else r["shop"]   # noqa: E731
    n = len(used)
    avg = lambda f: round(statistics.mean(f(r) for r in used))   # noqa: E731
    return {"markup": markup, "tie": tie, "n_all": len(rows), "n_flat_skipped": sum(r["direction"] == "flat" for r in rows),
            "n_near_skipped": sum(r["direction"] != "flat" for r in near), "n": n,
            "market_cheaper_pct": round(sum(r["cheaper"] == "시장" for r in used) / n * 100, 1),
            "rule_correct_pct": round(sum(pick(r) == r["cheaper"] for r in used) / n * 100, 1),
            "always_shop_correct_pct": round(sum(r["cheaper"] == "식봄" for r in used) / n * 100, 1),
            "always_market_correct_pct": round(sum(r["cheaper"] == "시장" for r in used) / n * 100, 1),
            "avg_cost_rule": avg(lambda r: cost(r, pick(r))), "avg_cost_always_shop": avg(lambda r: r["shop"]),
            "avg_cost_always_market": avg(lambda r: r["market"]),
            "avg_cost_best_possible": avg(lambda r: min(r["market"], r["shop"]))}


def main():
    items = [i for i in ITEMS if i not in SKIP and i in {r["item"] for r in forecasts()}]
    market = {i: market_series(i) for i in items}
    shop = shop_series()
    fc = forecasts()
    results = [evaluate(market, shop, fc, m, t) for t in (0.0, TIE) for m in MARKUPS]
    for r in results:
        print(r)

    OUT.mkdir(exist_ok=True)
    with open(OUT / "where_to_buy_purchases.csv", "w", newline="", encoding="utf-8-sig") as f:   # 가상 구매 기록 (웃돈 0%)
        w = csv.writer(f)
        w.writerow(["날짜", "품목", "시장에서 산 값(원/kg, 중도매 조사가)", "식봄 값(원/kg, 가장 가까운 앞 기록)"])
        for item in items:
            for d, p in sorted(market[item].items()):
                snaps = [x for x in sorted(shop.get(item, {})) if x <= d]
                w.writerow([d, item, round(p), round(shop[item][snaps[-1]]) if snaps else ""])
    (OUT / "where_to_buy.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
