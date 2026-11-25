"""고기 7일 시세: AI 학습 모델 vs 지금 쓰는 고정 공식 — 1119 일별 자료(2022-05 ~ )로 같은 시험.

실행 (salpi_agent 폴더에서): python -m experiments.meat_eval
fish_eval.py 와 같은 시험 · 같은 교체 기준 (learner.py 것을 가져다 씀). 채점만 하고 모델을 저장 · 교체하지 않음.
자료: data/raw/1119_meat_fish_daily (앱이 쓰는 품목 · 등급 그대로, 대구 소매). 5년 파일의 육류는 가게 단위 · 2022-04까지라 값 기준이 달라 잇지 않음
"""
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

from experiments import fish_eval as F
from price import learner as L
from sources.data_sources import EXTRA_ITEMS

CSV = F.REPO / "data" / "raw" / "1119_meat_fish_daily" / "1119_meat_fish_daily_daegu.csv"
OUT = Path(__file__).resolve().parent / "results" / "meat_eval.json"


def load():
    cfgs = {n: c for n, c in EXTRA_ITEMS.items() if c["group"] == "육류"}
    acc = defaultdict(lambda: defaultdict(list))
    with open(CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            c = cfgs.get(r["name"])
            if c and r["se_nm"] == c["se"] and (c["grd"] is None or r["grd_cd"] == c["grd"]) and r["price"]:
                acc[r["name"]][r["date"]].append(float(r["price"]))
    return {n: [(date.fromisoformat(d), sum(v) / len(v), 0.0) for d, v in sorted(days.items())] for n, days in acc.items()}


def main():
    series = load()
    names, rows = F.build(series)
    D = L.Data(names, rows)
    print("품목", {n: (series[n][0][0].isoformat(), len(series[n])) for n in names})
    print(f"기준일 {len(rows)}건 · 시험 {D.period[0]} ~ {D.period[1]} ({int(D.test.sum())}건)")
    formula = L.formula_metrics(D)
    model = L.evaluate(D, F.CFG)
    n = int(D.test.sum())
    zero = L.score(np.zeros(n), D.y[D.test], np.full(n, 1.0))
    ai = model["metrics"]
    pred_big = None
    per = {}
    for i, name in enumerate(names):
        k = D.item[D.test] == i
        if k.sum() < 20:
            continue
        f = L.score(D.formula[D.test][k], D.y[D.test][k], np.full(int(k.sum()), 1e9))
        per[name] = {"n": int(k.sum()), "formula": {x: f[x] for x in ("opposite_pct", "mae_pp", "direction_hit_pct")},
                     "model": {x: model["items"][name][x] for x in ("opposite_pct", "mae_pp", "direction_hit_pct")} if name in model["items"] else None,
                     "actual_flat_pct": round(float((np.abs(D.y[D.test][k]) < 0.05).mean() * 100)),
                     "actual_move2_pct": round(float((np.abs(D.y[D.test][k]) >= 2).mean() * 100))}
    res = {"period": D.period, "n_test": n, "features": F.CFG["features"], "n_rounds": model["n_rounds"], "formula": formula, "model": ai,
           "no_change_baseline": {x: zero[x] for x in ("opposite_pct", "mae_pp", "direction_hit_pct")},
           "replace_by_team_rule": bool(L.better(ai, formula)), "rule": f"정반대 {L.PROMOTE_OPP}%p 이상 ↓ 그리고 평균 오차 같거나 ↓",
           "importance": model["importance"], "items": per}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("formula", "model", "no_change_baseline", "replace_by_team_rule", "n_rounds", "importance")}, ensure_ascii=False, indent=1))
    for k, v in per.items():
        print(k, v)


if __name__ == "__main__":
    main()
