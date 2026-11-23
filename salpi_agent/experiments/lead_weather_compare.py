"""야채 7일 예측에 새 요인을 넣으면 나아지나: ① 가락시장 선행 ② 주산지 날씨 ③ 앞으로 7일 날씨(예보).

실행 (salpi_agent 폴더에서):
  .venv\\Scripts\\python -m experiments.lead_weather_compare
  .venv\\Scripts\\python -m experiments.lead_weather_compare --garak 경로 --prod 경로 --seeds 7 11 23 --garak-source auction
  .venv\\Scripts\\python -m experiments.lead_weather_compare      (기본: 가락 조사 가격, dev 자료만으로 돌아감)

자료
  - 대구 북부도매 · 대구 날씨: data/raw/1109_5y (학습 모델과 같음)
  - 가락시장 야채 경락: data/raw/1119_garak_veg (윤가언, 2021 ~ 2026-11)  ← --garak-source auction
  - 가락시장 조사 가격(KAMIS 가락도매 상품): data/raw/1112_*.csv.xz 서울 (~ 2025-08-29) + data/raw/1124_garak_veg_recent (윤가언, 2025-08-30 ~)
    ← --garak-source kamis (기본). 두 파일은 같은 단위로 이어짐 (11/23 확인)
  - 주산지 관측소 · 일자료: data/raw/1123_production_weather (윤가언, 품목별 산지 관측소 · 2021 ~)

넣어 보는 요인 (기준일까지의 값만 씀 — 예보 실험만 예외)
  가락   g_chg3 · g_chg7 : 가락 kg당 값의 3거래일 · 1주 변화(%)
         g_gap           : (대구 ÷ 가락) 값 비율이 지난 28일 평균보다 얼마나 벌어졌나(%) — 가락이 먼저 움직이면 대구가 따라오나
  주산지 p_rain7 · p_rain28 · p_cold7 · p_hot7 : 품목 산지 관측소들의 지난 7 · 28일 비(mm) · 한파(최저 ≤ −3℃) · 폭염(최고 ≥ 33℃) 일수 평균
  예보   pf_rain7 · pf_cold7 · pf_hot7 : 산지의 **앞으로 7일 실제 날씨** = 예보가 완벽했다고 치면 (예보 자료는 지난 것이 없어서)
         → 이 실험에서도 안 나아지면 실제 예보(더 부정확)로는 더 안 나아짐. 나아지면 "예보를 붙일 가치가 있다"의 상한

판정: 학습 모델 교체 기준과 같음 (learner.better) — 정반대 0.3%p 이상 ↓ 그리고 평균 오차 같거나 ↓
      나무를 만들 때 요인을 무작위로 고르므로, 씨앗(seed) 여러 개로 돌려 평균
"""
import argparse
import csv
import glob
import json
import math
import statistics
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from price import backtest as B
from price import learner as L
from sources.data_sources import ITEMS

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "results" / "lead_weather_compare.json"

GARAK = ["g_chg3", "g_chg7", "g_gap"]
PROD = ["p_rain7", "p_rain28", "p_cold7", "p_hot7"]
FCST = ["pf_rain7", "pf_cold7", "pf_hot7"]


def load_garak(folder):
    """가락 일별 품목 kg당 값 (등급 · 품종 합쳐 물량 가중) — 대구 load_veg 와 같은 품목 고르기."""
    agg = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for path in sorted(glob.glob(str(Path(folder) / "*_daily_*.csv"))):
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                for name, cfg in ITEMS.items():
                    if r["mclsf"] == cfg["sale_name"] and (not cfg["sale_sub"] or cfg["sale_sub"] in r["sclsf"]):
                        a = agg[name][r["date"]]
                        a[0] += float(r["qty_kg"] or 0)
                        a[1] += float(r["totprc"] or 0)
    return {n: sorted((date.fromisoformat(d), v[1] / v[0]) for d, v in m.items() if v[0] > 0 and v[1] > 0)
            for n, m in agg.items()}


# KAMIS 품목 코드 · 품종 (이름에 이 글자가 든 품종만, None = 모든 품종) — 가지는 가락 조사 가격 없음
KAMIS_GARAK = {"감자": ("152", "수미"), "배추": ("211", None), "양배추": ("212", None), "시금치": ("213", None),
               "상추": ("214", None), "오이": ("223", "다다기"), "애호박": ("224", "애호박"), "토마토": ("225", None),
               "무": ("231", None), "당근": ("232", "무세척"), "청양고추": ("242", "청양"), "양파": ("245", "양파"),
               "대파": ("246", "대파"), "깻잎": ("253", None)}


def load_garak_kamis(root):
    """가락도매 상품 조사 가격 → 품목별 [(날짜, 단위당 값)] (같은 날 품종이 여럿이면 평균)."""
    import lzma
    by_code = {c: (n, v) for n, (c, v) in KAMIS_GARAK.items()}
    acc = defaultdict(lambda: defaultdict(list))

    def put(code, vrty, ymd, prc, size):
        if code not in by_code:
            return
        name, want = by_code[code]
        if (want is None or want in vrty) and prc and size:
            acc[name][date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))].append(float(prc) / float(size))

    with lzma.open(glob.glob(str(root / "data" / "raw" / "1112_*.csv.xz"))[0], "rt", encoding="cp949", errors="replace") as fh:
        rows = csv.reader(fh)
        next(rows)
        for r in rows:   # 2: 시장 코드 (110211 = 가락도매) · 15: 등급 · 16: 값 · 19: 도매 단위 크기
            if r[2] == "110211" and r[15] == "상품":
                put(r[8], r[11], r[0], r[16], r[19])
    for path in glob.glob(str(root / "data" / "raw" / "1124_garak_veg_recent" / "*.csv")):
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r["mrkt_nm"] == "가락도매" and r["grd_nm"] == "상품":
                    put(r["item_cd"], r["vrty_nm"], r["exmn_ymd"], r["exmn_dd_prc"], r["unit_sz"])
    return {n: sorted((d, statistics.mean(v)) for d, v in m.items()) for n, m in acc.items()}


def load_prod(folder):
    """→ ({품목: [관측소]}, {관측소: {날짜: (비, 최저, 최고)}})"""
    stations = defaultdict(list)
    with open(Path(folder) / "1123_production_stations.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            stations[r["item"]].append(r["stn_id"])
    wx = defaultdict(dict)
    num = lambda v: float(v) if v not in ("", None) else None
    with open(Path(folder) / "1123_production_weather_daily.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            wx[r["stn_id"]][date.fromisoformat(r["date"])] = (num(r["rain_mm"]) or 0.0, num(r["min_temp"]), num(r["max_temp"]))
    return dict(stations), dict(wx)


def _pct(a, b):
    return (a / b - 1) * 100 if a and b else math.nan


def garak_feats(g, daegu_pts, asof):
    if not g:
        return {k: math.nan for k in GARAK}
    days = [p[0] for p in g]
    i = bisect_right(days, asof) - 1
    if i < 4 or days[i] < asof - timedelta(4):   # 가락 값이 너무 오래됨
        return {k: math.nan for k in GARAK}
    j = bisect_right(days, asof - timedelta(7)) - 1
    out = {"g_chg3": _pct(g[i][1], g[i - 3][1]), "g_chg7": _pct(g[i][1], g[j][1]) if j >= 0 else math.nan}
    gmap = dict(g)
    ratios = [p[1] / gmap[p[0]] for p in daegu_pts if p[0] > asof - timedelta(28) and p[0] in gmap]
    out["g_gap"] = _pct(ratios[-1], statistics.mean(ratios)) if len(ratios) >= 8 else math.nan
    return out


def wx_feats(stns, wx, asof, ahead=False):
    """산지 관측소들의 지난 (또는 앞으로) 날씨 평균."""
    keys = FCST if ahead else PROD
    if not stns:
        return {k: math.nan for k in keys}
    vals = defaultdict(list)
    for s in stns:
        w = wx.get(s, {})
        rng = [asof + timedelta(k) for k in range(1, 8)] if ahead else [asof - timedelta(k) for k in range(7)]
        d7 = [w[d] for d in rng if d in w]
        if len(d7) < 5:
            continue
        p = "pf_" if ahead else "p_"
        vals[p + "rain7"].append(sum(x[0] for x in d7))
        vals[p + "cold7"].append(sum(1 for x in d7 if x[1] is not None and x[1] <= -3))
        vals[p + "hot7"].append(sum(1 for x in d7 if x[2] is not None and x[2] >= 33))
        if not ahead:
            vals["p_rain28"].append(sum(w[d][0] for d in (asof - timedelta(k) for k in range(28)) if d in w))
    return {k: (statistics.mean(vals[k]) if vals[k] else math.nan) for k in keys}


def build(garak_dir, prod_dir, source="kamis"):
    series, weather = B.load_veg()
    names, rows = L.build_rows(series, weather, "야채")
    D = L.Data(names, rows)
    garak = load_garak_kamis(ROOT) if source == "kamis" else load_garak(garak_dir)
    stations, wx = load_prod(prod_dir) if Path(prod_dir, "1123_production_stations.csv").exists() else ({}, {})
    extra = defaultdict(list)
    for asof, idx in zip(D.asof, D.item):
        name = names[idx]
        f = {**garak_feats(garak.get(name), series[name], asof),
             **wx_feats(stations.get(name), wx, asof), **wx_feats(stations.get(name), wx, asof, ahead=True)}
        for k in GARAK + PROD + FCST:
            extra[k].append(f[k])
    for k, v in extra.items():
        D.cols[k] = np.array(v, dtype=float)
    cover = {k: round(float(np.isfinite(D.cols[k][D.test]).mean() * 100), 1) for k in GARAK + PROD + FCST}
    no_garak = sorted(n for n in names if n not in garak)
    no_station = sorted(n for n in names if n not in stations)
    return D, cover, no_garak, no_station


def run(D, base, add, seeds):
    feats = base["features"] + [f for f in add if f not in base["features"]]
    ms, imps, items = [], defaultdict(list), defaultdict(list)
    for s in seeds:
        r = L.evaluate(D, {"features": feats, "params": {**base["params"], "seed": s}})
        ms.append(r["metrics"])
        for f, v in r["importance"].items():
            imps[f].append(v)
        for n, m in r["items"].items():
            items[n].append(m["opposite_pct"])
    avg = {k: round(statistics.mean(m[k] for m in ms), 2) for k in ("opposite_pct", "mae_pp", "range_hit_pct", "direction_hit_pct")}
    avg["n"] = ms[0]["n"]
    return {"features": feats, "metrics": avg, "by_seed": ms,
            "importance": {f: round(statistics.mean(v)) for f, v in sorted(imps.items(), key=lambda x: -statistics.mean(x[1]))},
            "items_opposite": {n: round(statistics.mean(v), 1) for n, v in items.items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--garak", default=str(ROOT / "data" / "raw" / "1119_garak_veg"))
    ap.add_argument("--prod", default=str(ROOT / "data" / "raw" / "1123_production_weather"))
    ap.add_argument("--seeds", type=int, nargs="+", default=[7, 11, 23])
    ap.add_argument("--garak-source", choices=["kamis", "auction"], default="kamis")
    a = ap.parse_args()
    D, cover, no_garak, no_station = build(a.garak, a.prod, a.garak_source)
    print("가락 자료:", "KAMIS 조사 가격 (가락도매 상품)" if a.garak_source == "kamis" else "가락 경락 결과")
    print(f"야채 {len(D.names)}품목 · 기준일 {len(D.y):,}건 · 시험 {D.period[0]} ~ {D.period[1]} ({int(D.test.sum()):,}건)")
    print("시험 기간 요인 채워진 비율(%):", cover)
    print("가락 자료 없는 품목:", no_garak, "· 산지 관측소 없는 품목:", no_station)
    base = L.DEFAULT_CONFIG
    plans = [("지금 요인", []), ("+ 가락 선행", GARAK)]
    if np.isfinite(D.cols["p_rain7"]).any():   # 주산지 날씨 자료가 있을 때만
        plans += [("+ 주산지 날씨 (지난 7 · 28일)", PROD), ("+ 앞으로 7일 산지 날씨 (완벽한 예보)", FCST),
                  ("+ 가락 + 주산지 날씨", GARAK + PROD)]
    res = {}
    for label, add in plans:
        res[label] = run(D, base, add, a.seeds)
        m = res[label]["metrics"]
        print(f"{label:28s} 정반대 {m['opposite_pct']:5.2f}% · 평균 오차 {m['mae_pp']:.3f}%p · 범위 적중 {m['range_hit_pct']:.1f}%", flush=True)
    b = res["지금 요인"]["metrics"]
    for label in res:
        res[label]["better_than_base"] = label != "지금 요인" and L.better(res[label]["metrics"], b)
    formula = L.formula_metrics(D)
    OUT.parent.mkdir(exist_ok=True)
    out = OUT.with_name(f"lead_weather_compare_{a.garak_source}.json") if a.garak_source == "kamis" else OUT
    out.write_text(json.dumps({"kind": "야채", "garak_source": a.garak_source, "period": D.period, "n_test": int(D.test.sum()), "seeds": a.seeds,
                               "coverage_pct": cover, "no_garak": no_garak, "no_station": no_station,
                               "formula": formula, "results": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("고정 공식:", formula)
    print("저장:", out)


if __name__ == "__main__":
    main()
