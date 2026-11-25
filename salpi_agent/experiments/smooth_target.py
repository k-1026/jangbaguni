"""맞히는 대상 바꾸기 — '7일 뒤 하루 경락가' 대신 '다음 주 평균값 vs 이번 주 평균값'.

실행:  .venv\\Scripts\\python -m experiments.smooth_target      (aT · 기상청 API 로 최근 자료를 받음, 약 3분)
결과:  experiments/results/smooth_target.json

왜: 하루 경락가는 그날 반입량에 따라 크게 출렁여(야채 7일 변화가 ±2% 안에 남는 날 9%뿐) 방향 맞음이 54% 근처에서 막힘
    사장님은 보통 일주일 단위로 장을 봄 → "다음 주(기준일 다음 날 ~ 7일) 평균이 이번 주(기준일까지 7일) 평균보다 오르나"가 더 쓸모 있고 덜 출렁임
같게 둔 것: 요인 · 학습 설정 · 시험 기간(최근 1년) · 방향 기준 ±2% · 야채는 서울 10년 (서울 줄도 같은 목표로 다시 계산)
"""
import json
from bisect import bisect_left, bisect_right
from datetime import timedelta
from pathlib import Path

import numpy as np

from experiments.direction_tune import preds, score
from price import forecast_model as FM
from price import learner as L
from price import seoul_history as SH

OUT = Path(__file__).resolve().parent / "results" / "smooth_target.json"


def week_target(series_by_name, names, rows):
    """줄마다 목표를 '다음 7일 평균 / 지난 7일 평균 − 1' (%)로 바꿈. 다음 7일에 거래일이 2일 미만이면 뺌."""
    out = []
    cache = {}
    for r in rows:
        name = names[r[1]]
        if name not in cache:
            s = series_by_name[name]
            cache[name] = ([p[0] for p in s], np.array([p[1] for p in s]))
        days, pr = cache[name]
        a = bisect_right(days, r[0])
        past = pr[bisect_left(days, r[0] - timedelta(6)): a]
        nxt = pr[a: bisect_right(days, r[0] + timedelta(7))]
        if len(past) >= 2 and len(nxt) >= 2:
            out.append((r[0], r[1], r[2], r[3], (nxt.mean() / past.mean() - 1) * 100))
    return out


def two_way(p, y):
    m = np.abs(y) >= FM.BAND
    return round(float((np.sign(p[m]) == np.sign(y[m])).mean() * 100), 1)


def main():
    series, weather, last = L.load_data(upload=False)
    seoul = SH.load()
    out = {"data_end": str(last), "kinds": {}}
    for kind in FM.KINDS:
        names, rows = L.build_rows(series, weather, kind)
        extra = SH.rows(names, seoul) if kind == "야채" else []
        cfg = dict(L.DEFAULT_CONFIG)
        if kind == "야채":
            cfg = {**cfg, "seoul": True, "features": cfg["features"] + ["src"]}
        res = {}
        for label, rs, ex in (("7일 뒤 하루 값 (지금)", rows, extra),
                              ("다음 주 평균 vs 이번 주 평균", week_target(series, names, rows), week_target(seoul, names, extra))):
            D = L.Data(names, rs, ex)
            _, pt = preds(D, cfg)
            y = D.y[D.test]
            conf = {}
            for c in (4, 8):
                k = np.abs(pt) >= c
                conf[f"{c}%↑"] = {**score(pt[k], y[k]), "share_pct": round(float(k.mean() * 100), 1)}
            res[label] = {**score(pt, y), "two_way_pct": two_way(pt, y), "naive_up_pct": round(float((y >= FM.BAND).mean() * 100), 1),
                          "confident": conf, "period": D.period}
        out["kinds"][kind] = res
        print(f"\n===== {kind} =====")
        for label, r in res.items():
            print(f"  {label:<20} 방향 맞음 {r['direction_hit_pct']}% · 정반대 {r['opposite_pct']}% · 평균 오차 {r['mae_pp']}%p · "
                  f"움직인 날 오를/내릴 {r['two_way_pct']}% · 실제 비슷 {r['actual_flat_pct']}% (늘 '오를'이면 {r['naive_up_pct']}%)")
            print("      확신 있을 때만: " + " · ".join(f"{c} (예측의 {v['share_pct']}%) 방향 {v['direction_hit_pct']}% · 정반대 {v['opposite_pct']}%"
                                          for c, v in r["confident"].items()))
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
