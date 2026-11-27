"""정답률 80% 확인 · '70% 이상 = 예측 정확' 기준 근거 (11/27 발표 피드백 B-1 · B-2).

실전 채점(forecast_log = 화면에 실제로 나간 예측, 7일 뒤 채점)만 씀 — 과거 시험(백테스트)이 아니라 진짜 성적.
- B-1: 예측 폭(|예상 변화율|)이 클 때만 방향을 말하면 몇 % 맞는지 · 그때 말하는 비율 · 정반대 · 품목별 80% 넘는 재료
- B-2: 같은 기록에서 찍기(세 갈래 1/3) · 가장 많은 쪽 찍기 · 늘 '오를'과 비교, 이항 검정으로 "우연이 아닌" 적중률 선
채점 방식은 forecast_log.scorecard 와 같음 (품목 · 기준 날짜마다 처음 저장한 예측 하나, 주 평균 모델이 방향을 말하지 않은 것은 뺌).

실행: python -m experiments.accuracy_80 → experiments/results/accuracy_80.json
"""
import json
from collections import Counter
from math import comb
from pathlib import Path

from price.forecast_log import _direction, _unstated
from sources import supabase_db

OUT = Path(__file__).parent / "results" / "accuracy_80.json"
CUTS = (0, 2, 4, 6, 8, 10, 15)   # 예측 폭 이상일 때만 방향을 말함 (%)
ITEM_MIN = 5                     # 품목별 성적은 5번 이상 채점된 것만


def rows():
    out, page = [], 0
    while True:   # 한 번에 1000줄까지라 나눠 받음
        got = supabase_db.select("forecast_log", actual_price="not.is.null", order="run_date,item", offset=str(page * 1000), limit="1000",
                                 select="item,kind,base_date,run_date,direction,expected_change_pct,actual_change_pct,direction_hit,formula_version")
        out += got
        if len(got) < 1000:
            break
        page += 1
    first = {}
    for r in sorted(out, key=lambda r: r["run_date"]):
        first.setdefault((r["item"], r["base_date"]), r)
    return [r for r in first.values() if not _unstated(r) and r["expected_change_pct"] is not None]


def hit_rate(group):
    n = len(group)
    if not n:
        return {"n": 0}
    opp = sum(1 for r in group if {r["direction"], _direction(float(r["actual_change_pct"]))} == {"up", "down"})
    return {"n": n, "hit_pct": round(sum(bool(r["direction_hit"]) for r in group) / n * 100, 1), "opposite_pct": round(opp / n * 100, 1)}


def by_cut(group):
    """예측 폭이 cut% 이상인 것만 말할 때: 말하는 비율(coverage) · 적중 · 정반대."""
    out = []
    for cut in CUTS:
        said = [r for r in group if abs(float(r["expected_change_pct"])) >= cut]
        out.append({"cut_pct": cut, "coverage_pct": round(len(said) / len(group) * 100, 1) if group else None, **hit_rate(said)})
    return out


def baselines(group):
    """같은 기록에서 머리를 안 쓰고 맞히는 방법들의 적중률."""
    actual = Counter(_direction(float(r["actual_change_pct"])) for r in group)
    n = len(group)
    top, top_n = actual.most_common(1)[0]
    return {"random_3way_pct": 33.3, "majority": top, "majority_pct": round(top_n / n * 100, 1),
            "always_up_pct": round(actual["up"] / n * 100, 1),
            "actual_share_pct": {k: round(v / n * 100, 1) for k, v in actual.items()}}


def binom_tail(n, k, p):
    """P(X >= k), X ~ 이항(n, p) — 찍어서 k번 이상 맞힐 확률."""
    return sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def min_rate(n, p, alpha=0.05):
    """찍기(p)로는 5% 확률로도 나오기 어려운 가장 낮은 적중률 (n번 예측)."""
    k = next(k for k in range(n + 1) if binom_tail(n, k, p) < alpha)
    return round(k / n * 100, 1)


def main():
    data = rows()
    kinds = sorted({r["kind"] for r in data})
    base = baselines(data)
    p0 = base["majority_pct"] / 100
    items = {}
    for r in data:
        items.setdefault(r["item"], []).append(r)
    item_rates = {k: {**hit_rate(v), "kind": v[0]["kind"]} for k, v in items.items() if len(v) >= ITEM_MIN}
    out = {
        "period": [min(r["base_date"] for r in data), max(r["base_date"] for r in data)],
        "all": {**hit_rate(data), "by_cut": by_cut(data)},
        "kinds": {k: {**hit_rate(g), "by_cut": by_cut(g), "baselines": baselines(g)}
                  for k in kinds for g in [[r for r in data if r["kind"] == k]]},
        "baselines": base,
        # 화면은 최근 1주(품목마다 예측 3 ~ 7번), 4주면 품목마다 ~20번: 그 횟수에서 '가장 많은 쪽 찍기'로는 5% 확률로도 못 내는 적중률
        "not_luck_pct": {n: min_rate(n, p0) for n in (5, 7, 10, 20, 50)},
        "items_80": sorted(([k, v["hit_pct"], v["n"], v["kind"]] for k, v in item_rates.items() if v["hit_pct"] >= 80), key=lambda x: -x[1]),
        "items_70": sum(v["hit_pct"] >= 70 for v in item_rates.values()), "items_scored": len(item_rates),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    o = main()
    print(json.dumps({k: o[k] for k in ("period", "all", "baselines", "not_luck_pct", "items_70", "items_scored")}, ensure_ascii=False, indent=1))
