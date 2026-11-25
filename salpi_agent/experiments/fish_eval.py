"""수산물 7일 시세: AI 학습 모델 vs 지금 쓰는 고정 공식 — 합친 자료(2020~2026)로 같은 시험.

실행 (salpi_agent 폴더에서): python -m experiments.fish_eval
자료: data/raw/1125_fish_merged/1125_fish_daily_merged_daegu.csv (merge_fish.py 결과)
시험 · 교체 기준은 매일 학습(price/learner.py)과 똑같이 가져다 씀 — 새 기준을 만들지 않음
  시험 = 최근 1년 (모델이 학습 때 못 본 기간), 교체 기준 = 정반대 0.3%p 이상 ↓ 그리고 평균 오차 같거나 ↓
고정 공식 = analysis.extra_forecast 의 "한 달 평균과의 차이"(EXTRA_REVERSION). 공휴일 · 행사는 과거 자료가 없어 뺌 (backtest.py 와 같음)
이 파일은 채점만 함. 모델을 저장 · 교체하지 않음.
"""
import csv
import json
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from price import forecast_model as FM
from price import learner as L
from price.analysis import EXTRA_REVERSION, reversion_factor

REPO = Path(__file__).resolve().parents[2]
CSV = REPO / "data" / "raw" / "1125_fish_merged" / "1125_fish_daily_merged_daegu.csv"
OUT = Path(__file__).resolve().parent / "results" / "fish_eval.json"
# 수산물에는 반입량 · 날씨 자료가 없어 그 요인은 뺌 (값이 비어 있어 학습에 도움이 안 됨)
CFG = {"features": ["item", "dev", "trend", "volat", "chg3", "season", "to_major", "month"], "params": L.DEFAULT_CONFIG["params"]}


def load():
    s = defaultdict(list)
    with open(CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            s[r["item"]].append((date.fromisoformat(r["date"]), float(r["price"]), 0.0))
    return {k: sorted(v) for k, v in s.items()}


def build(series):
    """learner.build_rows 와 같은 방식 (기준일마다 요인 · 고정 공식 예측 · 7~10일 안 첫 거래일의 실제 변화)."""
    names = sorted(series)
    rows = []
    for idx, name in enumerate(names):
        s = series[name]
        days = [p[0] for p in s]
        prices = [p[1] for p in s]
        for i in range(30, len(s)):
            asof = days[i]
            j = bisect_right(days, asof + timedelta(6))
            if asof < date(2021, 3, 1) or j >= len(s) or days[j] > asof + timedelta(10):
                continue
            pts = s[max(0, i - 40): i + 1]
            f = FM.make_features(name, idx, pts, {}, asof, FM.season_value(days, prices, asof))
            win = [p[1] for p in pts if p[0] > asof - timedelta(28)]
            rev = reversion_factor(win, *EXTRA_REVERSION)
            rows.append((asof, idx, f, rev["effect_pct"] if rev else 0.0, (prices[j] / prices[i] - 1) * 100))
    return names, rows


def main():
    series = load()
    names, rows = build(series)
    D = L.Data(names, rows)
    print(f"품목 {len(names)}개 · 기준일 {len(rows)}건 · 시험 기간 {D.period[0]} ~ {D.period[1]} ({int(D.test.sum())}건)")
    formula = L.formula_metrics(D)
    model = L.evaluate(D, CFG)
    zero = L.score(np.zeros(int(D.test.sum())), D.y[D.test], np.full(int(D.test.sum()), 1.0))
    ai = model["metrics"]
    win = L.better(ai, formula)
    per = {}
    for i, name in enumerate(names):
        k = D.item[D.test] == i
        if k.sum() < 20:
            continue
        f = L.score(D.formula[D.test][k], D.y[D.test][k], np.full(int(k.sum()), 1e9))
        per[name] = {"n": int(k.sum()), "formula": {x: f[x] for x in ("opposite_pct", "mae_pp", "direction_hit_pct")},
                     "model": {x: model["items"][name][x] for x in ("opposite_pct", "mae_pp", "direction_hit_pct")} if name in model["items"] else None}
    res = {"period": D.period, "n_test": int(D.test.sum()), "features": CFG["features"], "n_rounds": model["n_rounds"],
           "formula": formula, "model": ai, "no_change_baseline": {x: zero[x] for x in ("opposite_pct", "mae_pp", "direction_hit_pct")},
           "replace_by_team_rule": bool(win), "rule": f"정반대 {L.PROMOTE_OPP}%p 이상 ↓ 그리고 평균 오차 같거나 ↓",
           "importance": model["importance"], "items": per}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("formula", "model", "no_change_baseline", "replace_by_team_rule", "importance")}, ensure_ascii=False, indent=1))
    for n, v in per.items():
        print(n, v)


if __name__ == "__main__":
    main()
