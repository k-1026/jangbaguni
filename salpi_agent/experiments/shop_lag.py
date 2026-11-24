"""식봄 판매가가 도매가를 따라 움직이는지 · 며칠 늦게 따라오는지 (읽기만 함, 저장 · 수정 없음).

실행 (salpi_agent 폴더에서):  python -m experiments.shop_lag        (.env 의 SUPABASE_* 필요, 몇 초)

- 식봄: Supabase price_snapshots (하루 한 번 저장한 상품별 판매가). 같은 상품(같은 주소)의 변화만 봄
        품목마다 상품 여러 개의 가운데 값(중앙값) 변화를 품목 변화로 씀
- 도매: Supabase forecast_log 의 base_date · base_price (대구 도매 kg당). 품목 · 기준 날짜마다 처음 것 하나
- 비교: 식봄 기록 날짜 사이 구간마다 도매 변화(그 날짜 이하 가장 가까운 도매 값)와 식봄 변화
- "따라옴": 도매가 ±2% 넘게 움직인 구간에서, 같은 방향으로 식봄 중앙값이 ±2% 넘게 움직임 (같은 구간 또는 이어진 구간 안)
- 결과: experiments/results/shop_lag.json  (11/26 2주 결과는 같은 명령으로 다시 돌리면 됨)
"""
import json
import statistics
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sources import supabase_db   # noqa: E402

OUT = Path(__file__).resolve().parent / "results" / "shop_lag.json"
BAND = 2.0


def pct(a, b):
    return (b / a - 1) * 100


def load():
    shop = supabase_db.select("price_snapshots", source="eq.식봄", select="snap_date,item,url,sale_price")
    by_url = defaultdict(dict)       # 상품 주소 → {날짜: (품목, 가격)}
    for r in shop:
        by_url[r["url"]][r["snap_date"]] = (r["item"], float(r["sale_price"]))
    fl = supabase_db.select("forecast_log", select="run_date,item,base_date,base_price")
    wholesale = defaultdict(dict)    # 품목 → {기준 날짜: 도매 kg당}
    for r in sorted(fl, key=lambda r: r["run_date"]):
        wholesale[r["item"]].setdefault(r["base_date"], float(r["base_price"]))
    return by_url, wholesale


def wholesale_at(series, day):
    ks = [k for k in sorted(series) if k <= day]
    return series[ks[-1]] if ks else None


def main():
    by_url, wholesale = load()
    dates = sorted({d for v in by_url.values() for d in v})
    items = sorted({i for v in by_url.values() for i, _ in v.values()})
    changed = [u for u, v in by_url.items() if len({p for _, p in v.values()}) > 1]
    print(f"식봄 기록 날짜 {len(dates)}일 ({dates[0]} ~ {dates[-1]}) · 상품 {len(by_url)}개 · 값이 바뀐 상품 {len(changed)}개")

    windows, rows = list(zip(dates, dates[1:])), []
    for item in items:
        for d0, d1 in windows:
            w0, w1 = wholesale_at(wholesale[item], d0), wholesale_at(wholesale[item], d1)
            moves = [pct(v[d0][1], v[d1][1]) for v in by_url.values()
                     if d0 in v and d1 in v and v[d0][0] == item]
            if not w0 or not w1 or not moves:
                continue
            rows.append({"item": item, "from": d0, "to": d1, "wholesale_pct": round(pct(w0, w1), 1),
                         "shop_median_pct": round(statistics.median(moves), 1)})

    big = [r for r in rows if abs(r["wholesale_pct"]) >= BAND]
    followed = []
    for r in big:
        later = [x for x in rows if x["item"] == r["item"] and x["from"] >= r["from"]]   # 같은 구간 + 이어진 구간
        if any(abs(x["shop_median_pct"]) >= BAND and (x["shop_median_pct"] > 0) == (r["wholesale_pct"] > 0) for x in later):
            followed.append(r)
    summary = {"snapshot_dates": dates, "shop_products": len(by_url), "shop_products_changed": len(changed),
               "wholesale_moves_over_2pct": len(big), "followed_by_shop": len(followed)}
    print(f"도매가가 ±{BAND:.0f}% 넘게 움직인 (품목 · 구간) {len(big)}건 중 식봄이 같은 방향으로 따라온 것 {len(followed)}건")

    span = {}
    for item in items:   # 첫 기록일 → 마지막 기록일 전체 변화
        w0, w1 = wholesale_at(wholesale[item], dates[0]), wholesale_at(wholesale[item], dates[-1])
        moves = [pct(v[dates[0]][1], v[dates[-1]][1]) for v_ in [0] for v in by_url.values()
                 if dates[0] in v and dates[-1] in v and v[dates[0]][0] == item]
        if w0 and w1 and moves:
            span[item] = {"wholesale_pct": round(pct(w0, w1), 1), "shop_median_pct": round(statistics.median(moves), 1)}
    print(f"\n{dates[0]} → {dates[-1]} 전체 변화 (도매 / 식봄 중앙값)")
    for item, s in sorted(span.items(), key=lambda kv: kv[1]["wholesale_pct"]):
        print(f"  {item:<6} {s['wholesale_pct']:>+6.1f}%  /  {s['shop_median_pct']:>+5.1f}%")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"summary": summary, "whole_span": span, "windows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
