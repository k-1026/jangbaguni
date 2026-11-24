"""도매가가 움직이면 대구 소매가가 며칠 뒤에 따라오나? (KAMIS 대구 조사가, 2021 ~ 2026-11-06)

실행 (salpi_agent 폴더에서):  python -m experiments.retail_lag        (API 키 필요 없음, 몇 초)

- 자료: data/raw/1109_5y/1109_price_daily_*.csv — 도매 = 북부도매 중도매 '상품' · 소매 = 대구 소매 '상품'(조사한 곳 평균), 모두 kg당
  포기 · 개로 조사한 소매(무 · 배추 · 양배추 · 오이 · 애호박)는 환산표를 거친 '약' 값
- 날짜 사이 빈 칸은 앞 값으로 3일까지 채움
- 7일 변화율(로그)을 도매 · 소매 모두 구해서, 도매 변화가 있고 k일 뒤 소매 변화와 얼마나 같이 움직이는지(상관) 봄 (k = 0 ~ 28일)
    · 가장 상관이 큰 k = 시차(일) · 그때 상관 = 얼마나 따라오나 · 기울기 = 도매가 1% 움직일 때 소매가 몇 % 움직이나
- '큰 움직임' 적중: 도매가 7일 동안 ±10% 넘게 움직인 날 중, 시차 뒤 소매가 같은 방향으로 ±2% 넘게 움직인 비율
- 결과: experiments/results/retail_lag.json
"""
import csv
import json
import math
import statistics
from datetime import date, timedelta
from pathlib import Path

from price import units

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "data" / "raw" / "1109_5y"
OUT = Path(__file__).resolve().parent / "results" / "retail_lag.json"
FILES = {"양배추": "cabbage", "당근": "carrot", "청양고추": "cheongyang_pepper", "오이": "cucumber", "대파": "green_onion",
         "상추": "lettuce", "배추": "napa_cabbage", "양파": "onion", "깻잎": "perilla_leaf", "감자": "potato", "무": "radish",
         "시금치": "spinach", "토마토": "tomato", "애호박": "zucchini"}
MAX_LAG, WINDOW, FILL = 28, 7, 3
BIG, SMALL = 0.10, 0.02    # 도매 '큰 움직임' · 소매 '움직였다' 기준


def kg_price(item, r):
    try:
        b = units.per_base_price(item, float(r["exmn_dd_prc"]), float(r["unit_sz"] or 1), r["unit"])
    except (TypeError, ValueError):
        return None
    return b["price"] if b["unit"] == "kg" and b["price"] else None


def load(item, fname):
    """날짜(date) → 도매 kg당 · 소매 kg당 (날마다 앞 값으로 3일까지 채움)"""
    whl, ret = {}, {}
    tmp_w, tmp_r = {}, {}
    for r in csv.DictReader(open(DIR / f"1109_price_daily_{fname}.csv", encoding="utf-8-sig")):
        if r["grd_nm"] != "상품":
            continue
        d = date(int(r["exmn_ymd"][:4]), int(r["exmn_ymd"][4:6]), int(r["exmn_ymd"][6:]))
        if r["se_nm"] == "중도매" and r["mrkt_nm"] == "북부도매" and (r["unit"].startswith("kg") or r["unit"] == "g"):
            p = kg_price(item, r)
            if p:
                tmp_w.setdefault(d, []).append(p)
        elif r["se_nm"] == "소매":
            p = kg_price(item, r)
            if p:
                tmp_r.setdefault(d, []).append(p)
    start, end = max(min(tmp_w), min(tmp_r)), min(max(tmp_w), max(tmp_r))
    last_w = last_r = None
    d = start
    while d <= end:
        for tmp, out, name in ((tmp_w, whl, "w"), (tmp_r, ret, "r")):
            if d in tmp:
                out[d] = statistics.mean(tmp[d])
            else:
                prev = max((x for x in out if x < d), default=None)
                if prev and (d - prev).days <= FILL:
                    out[d] = out[prev]
        d += timedelta(1)
    return whl, ret


def changes(series):
    """날짜 → 7일 전 대비 로그 변화율"""
    return {d: math.log(p / series[d - timedelta(WINDOW)]) for d, p in series.items() if d - timedelta(WINDOW) in series}


def analyze(item, fname):
    whl, ret = load(item, fname)
    cw, cr = changes(whl), changes(ret)
    best, curve = None, {}
    for k in range(0, MAX_LAG + 1):
        pairs = [(cw[d], cr[d + timedelta(k)]) for d in cw if d + timedelta(k) in cr]
        if len(pairs) < 100:
            continue
        x, y = [p[0] for p in pairs], [p[1] for p in pairs]
        c = statistics.correlation(x, y)
        curve[k] = round(c, 3)
        if best is None or c > best[1]:
            best = (k, c, statistics.linear_regression(x, y).slope, len(pairs))
    k, corr, slope, n = best
    big = [d for d, v in cw.items() if abs(v) >= math.log(1 + BIG) and d + timedelta(k) in cr]
    hit = [d for d in big if cr[d + timedelta(k)] * cw[d] > 0 and abs(cr[d + timedelta(k)]) >= math.log(1 + SMALL)]
    return {"days": len(whl), "best_lag_days": k, "corr_at_best": round(corr, 2), "corr_same_day": curve.get(0),
            "pass_through": round(slope, 2), "pairs": n, "big_moves": len(big),
            "big_move_followed_pct": round(len(hit) / len(big) * 100) if big else None,
            "corr_by_lag": {str(l): curve[l] for l in (0, 3, 7, 14, 21, 28) if l in curve}}


def main():
    out = {}
    print(f"{'품목':<5}{'시차(일)':>8}{'상관':>6}{'당일상관':>8}{'기울기':>7}{'큰 움직임 수':>10}{'소매가 따라온 비율':>14}")
    for item, fname in FILES.items():
        out[item] = analyze(item, fname)
        r = out[item]
        print(f"{item:<5}{r['best_lag_days']:>8}{r['corr_at_best']:>6.2f}{r['corr_same_day']:>8.2f}{r['pass_through']:>7.2f}"
              f"{r['big_moves']:>10}{(str(r['big_move_followed_pct']) + '%') if r['big_move_followed_pct'] is not None else '-':>14}")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장:", OUT)


if __name__ == "__main__":
    main()
