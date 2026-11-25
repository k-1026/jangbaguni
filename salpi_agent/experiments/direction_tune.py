"""방향 맞음(오를 · 비슷 · 내릴) 올리기 실험 — 학습 모델 예측을 방향으로 바꾸는 기준을 다시 맞추면 나아지나.

실행:  .venv\\Scripts\\python -m experiments.direction_tune      (aT · 기상청 API 로 최근 자료를 받음, 약 3분)
결과:  experiments/results/direction_tune.json

왜: 실전 채점(사이트 /api/forecast-score, 11/25) 방향 맞음 58.5% (217건 중 127건), 야채 52.2% · 과일 55.0%.
    학습 모델은 '몇 % 변할지'를 절대오차(L1)로 배워 예측이 0 쪽으로 작게 나옴 → ±2% 로 자르면 '비슷'이 너무 많을 수 있음
어떻게: 매일 학습과 같은 자료 · 같은 시험(최근 1년) · 같은 설정. 방향 기준 t 를 시험 전 1년(검증)에서 골라 시험에서 확인
    실제 방향은 늘 ±2% (채점 기준은 그대로). 바꾸는 것은 "예측 몇 % 부터 오른다고 말할지" 하나
"""
import json
from pathlib import Path

import numpy as np

from price import forecast_model as FM
from price import learner as L
from price import seoul_history as SH

OUT = Path(__file__).resolve().parent / "results" / "direction_tune.json"
GRID = [round(x, 2) for x in np.arange(0, 4.01, 0.25)]


def cls(x, t):
    return np.where(x >= t, 1, np.where(x <= -t, -1, 0))


def score(p, y, t=FM.BAND):
    a, b = cls(p, t), cls(y, FM.BAND)
    return {"n": int(len(y)), "direction_hit_pct": round(float((a == b).mean() * 100), 1),
            "opposite_pct": round(float(((a * b) == -1).mean() * 100), 1), "mae_pp": round(float(np.abs(p - y).mean()), 2),
            "said_flat_pct": round(float((a == 0).mean() * 100), 1), "actual_flat_pct": round(float((b == 0).mean() * 100), 1)}


def preds(D, cfg):
    """learner.evaluate 와 같은 학습: 검증 예측(시험 전 1년, 그 앞으로 학습) · 시험 예측(시험 전 전부로 학습)."""
    X = D.X(cfg["features"])
    probe = L._gbdt(cfg).fit(*D.train(D.fit, cfg), X[D.val], D.y[D.val])
    m = L._gbdt(cfg, max(probe.best_iteration, 20)).fit(*D.train(D.pre, cfg))
    return probe.predict(X[D.val]), m.predict(X[D.test])


def preds_sign(D, cfg, clip=None):
    """방향만 배우는 모델: 목표를 오를 +1 · 비슷 0 · 내릴 −1 (clip 이 있으면 ±clip% 로 자른 변화율)로 바꿔 제곱오차로 학습."""
    tgt = (lambda y: np.clip(y, -clip, clip)) if clip else (lambda y: cls(y, FM.BAND).astype(float))
    c = {**cfg, "params": {**cfg["params"], "objective": "l2"}}
    X = D.X(c["features"])
    Xf, yf = D.train(D.fit, c)
    probe = L._gbdt(c).fit(Xf, tgt(yf), X[D.val], tgt(D.y[D.val]))
    Xp, yp = D.train(D.pre, c)
    m = L._gbdt(c, max(probe.best_iteration, 20)).fit(Xp, tgt(yp))
    return probe.predict(X[D.val]), m.predict(X[D.test])


def same_opposite(pv, yv, pt, yt, target_opp, grid):
    """검증에서 정반대가 target_opp 이하인 기준 중 방향 맞음이 가장 높은 것 → 시험 성적 (같은 정반대에서 비교하려고)."""
    ok = [t for t in grid if score(pv, yv, t)["opposite_pct"] <= target_opp] or [max(grid)]
    t = max(ok, key=lambda t: score(pv, yv, t)["direction_hit_pct"])
    return t, score(pt, yt, t)


def main():
    series, weather, last = L.load_data(upload=False)
    out = {"data_end": str(last), "kinds": {}}
    for kind in FM.KINDS:
        names, rows = L.build_rows(series, weather, kind)
        D = L.Data(names, rows, SH.rows(names) if kind == "야채" else ())
        cfg = dict(L.DEFAULT_CONFIG)
        if kind == "야채":   # 11/25 매일 학습에 넣은 서울 10년 (교체 기준 통과)
            cfg = {**cfg, "seoul": True, "features": cfg["features"] + ["src"]}
        pv, pt = preds(D, cfg)
        yv, yt = D.y[D.val], D.y[D.test]
        # 방향 기준 t: 검증에서 방향 맞음이 가장 높은 값 (정반대가 검증에서 1%p 넘게 늘면 후보에서 뺌)
        base_v = score(pv, yv)
        curve = {t: (score(pv, yv, t), score(pt, yt, t)) for t in GRID}
        ok = [t for t in GRID if curve[t][0]["opposite_pct"] <= base_v["opposite_pct"] + 1.0]
        best = max(ok, key=lambda t: curve[t][0]["direction_hit_pct"])
        f = D.formula[D.test]
        res = {
            "test_period": D.period, "n_test": int(D.test.sum()), "chosen_t": best,
            "고정 공식": score(f, yt),
            "그대로 (늘 비슷)": score(np.zeros(len(yt)), yt),
            "최근 1주 흐름 그대로": score(np.nan_to_num(D.cols["chg7"][D.test]), yt),
            "AI (지금, ±2%)": score(pt, yt),
            f"AI (기준 ±{best}%)": score(pt, yt, best),
            "curve": {str(t): {"valid": v, "test": te} for t, (v, te) in curve.items()},
        }
        # 확신 있는 예측만: |예측| 이 클수록 맞나 (보여 줄 범위를 줄이면 몇 % 까지)
        conf = {}
        for c in (2, 4, 6, 8):
            k = np.abs(pt) >= c
            if k.sum() >= 50:
                conf[str(c)] = {**score(pt[k], yt[k], best), "share_pct": round(float(k.mean() * 100), 1)}
        res["confident"] = conf
        # 다른 학습 방법: 같은 정반대 수준(검증에서 지금 AI 정반대 이하)에서 방향을 더 맞히나
        opp_v = base_v["opposite_pct"]
        res["same_opposite"] = {"AI (지금 모델, 기준 다시)": same_opposite(pv, yv, pt, yt, opp_v, GRID)}
        for label, clip in (("방향만 배우기 (+1 · 0 · −1)", None), ("변화율 ±5%로 잘라 배우기", 5), ("변화율 ±10%로 잘라 배우기", 10)):
            sv, st = preds_sign(D, cfg, clip)
            grid = [round(x, 3) for x in np.linspace(0, float(np.percentile(np.abs(sv), 90)), 41)]
            res["same_opposite"][label] = same_opposite(sv, yv, st, yt, opp_v, grid)
        print(f"  [같은 정반대(검증 {opp_v}% 이하)에서 비교] " + " · ".join(
            f"{k}: 방향 {r['direction_hit_pct']}% · 정반대 {r['opposite_pct']}% (기준 {t})" for k, (t, r) in res["same_opposite"].items()))
        out["kinds"][kind] = res
        print(f"\n===== {kind} · 시험 {D.period[0]} ~ {D.period[1]} ({len(yt):,}건) =====")
        print(f"  {'방법':<22}{'방향 맞음':>8}{'정반대':>8}{'평균 오차':>10}{'비슷이라 말함':>12}{'실제 비슷':>9}")
        for k2 in ("고정 공식", "그대로 (늘 비슷)", "최근 1주 흐름 그대로", "AI (지금, ±2%)", f"AI (기준 ±{best}%)"):
            r = res[k2]
            print(f"  {k2:<22}{r['direction_hit_pct']:>7.1f}%{r['opposite_pct']:>7.1f}%{r['mae_pp']:>9.2f}p{r['said_flat_pct']:>11.1f}%{r['actual_flat_pct']:>8.1f}%")
        print("  방향 기준별 (검증 → 시험 방향 맞음 / 정반대): " + " · ".join(
            f"±{t}: {v['direction_hit_pct']}→{te['direction_hit_pct']}/{te['opposite_pct']}" for t, (v, te) in curve.items() if t in (0, 0.5, 1, 1.5, 2, 3)))
        print("  확신 있는 예측만 (|예측| ≥ c%): " + " · ".join(
            f"{c}%↑ {v['share_pct']}%의 예측 → 방향 {v['direction_hit_pct']}% · 정반대 {v['opposite_pct']}%" for c, v in conf.items()))
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
