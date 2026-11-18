"""우리 부스팅(gbdt.py) vs 진짜 LightGBM · XGBoost — 같은 자료 · 같은 시험 기간 · 같은 지표로 비교.

실행: GitHub 자동 실행 컴퓨터에서 (.github/workflows/lgbm-compare.yml) — 이 PC는 보안 정책으로 LightGBM 설치 파일이 막힘
결과: 보관함 models/forecast/lightgbm_compare.json + 실행 화면 요약표

비교 조건 (learner.py 매일 학습과 똑같이)
  자료: 5년 치 파일 + 그 뒤 API 자료, 시험 = 최근 1년 (모델이 안 본 기간)
  나무 수: 시험 전 마지막 1년으로 고름 (early stopping) → 시험 전 전체로 다시 학습 → 최근 1년 시험
  지표: 정반대 · 평균 오차 · 범위 적중 (범위 폭도 검증 기간 오차로 같은 방식)
  설정: 오늘 매일 학습의 챔피언 설정(요인 · 학습 속도 · 깊이 · 잎 최소 건수 · 규제)을 각 라이브러리 이름으로 옮김
        + 라이브러리 기본 설정 그대로도 한 번 (우리에게 유리하게 맞춘 게 아닌지 확인)
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import numpy as np

from price import forecast_model as FM
from price import learner as L

KST = timezone(timedelta(hours=9))


def run_lgbm(D, cfg, params):
    import lightgbm as lgb
    X = D.X(cfg["features"])
    ci = [cfg["features"].index("item")]
    mk = lambda m: lgb.Dataset(X[m], D.y[m], categorical_feature=ci, free_raw_data=False)
    probe = lgb.train(params, mk(D.fit), 2000, valid_sets=[mk(D.val)], callbacks=[lgb.early_stopping(100, verbose=False)])
    n = max(probe.best_iteration, 20)
    m = lgb.train(params, mk(D.pre), n)
    return probe.predict(X[D.val]), m.predict(X[D.test]), n


def run_xgb(D, cfg, params):
    import xgboost as xgb
    X = D.X(cfg["features"])
    mk = lambda m: xgb.DMatrix(X[m], D.y[m], missing=np.nan)
    probe = xgb.train(params, mk(D.fit), 2000, evals=[(mk(D.val), "val")], early_stopping_rounds=100, verbose_eval=False)
    n = max(probe.best_iteration + 1, 20)
    m = xgb.train(params, mk(D.pre), n)
    return (probe.predict(mk(D.val), iteration_range=(0, n)), m.predict(xgb.DMatrix(X[D.test], missing=np.nan)), n)


def scored(D, val_pred, test_pred):
    half_val, _ = D.half_by_item(np.abs(D.y[D.val] - val_pred), D.val)
    half = np.array([half_val[D.names[i]] for i in D.item[D.test]])
    return L.score(test_pred, D.y[D.test], half)


def main():
    series, weather, last = L.load_data(upload=False)
    out = {"made": datetime.now(KST).isoformat(timespec="seconds"), "data_end": str(last), "kinds": {}}
    lines = ["# 우리 부스팅 vs LightGBM · XGBoost", "",
             f"자료 끝: {last} · 시험 = 최근 1년 (모델이 안 본 기간) · 지표: 정반대(↓) · 평균 오차(↓) · 범위 적중", ""]
    for kind in FM.KINDS:
        names, rows = L.build_rows(series, weather, kind)
        D = L.Data(names, rows)
        cfg = (L.load_json(f"forecast/{FM.KINDS[kind]}.json", None) or {}).get("config") or L.DEFAULT_CONFIG
        p = cfg["params"]
        res = {"고정 공식": {"metrics": L.formula_metrics(D)}}
        t = time.time()
        ours = L.evaluate(D, cfg)
        res["우리 부스팅 (gbdt.py)"] = {"metrics": ours["metrics"], "trees": ours["n_rounds"], "seconds": round(time.time() - t, 1)}
        same = {"objective": "l1" if p["objective"] == "l1" else "l2", "learning_rate": p["learning_rate"], "max_depth": p["max_depth"],
                "num_leaves": 2 ** p["max_depth"], "min_child_samples": p["min_leaf"], "lambda_l2": p["l2"],
                "bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "max_bin": 32, "seed": 7, "verbose": -1}
        for label, params in (("LightGBM (같은 설정)", same),
                              ("LightGBM (기본 설정)", {"objective": "l1", "seed": 7, "verbose": -1})):
            t = time.time()
            v, te, n = run_lgbm(D, cfg, params)
            res[label] = {"metrics": scored(D, v, te), "trees": n, "seconds": round(time.time() - t, 1)}
        try:
            t = time.time()
            v, te, n = run_xgb(D, cfg, {"objective": "reg:absoluteerror" if p["objective"] == "l1" else "reg:squarederror",
                                        "eta": p["learning_rate"], "max_depth": p["max_depth"], "min_child_weight": p["min_leaf"],
                                        "lambda": p["l2"], "subsample": 0.8, "colsample_bytree": 0.8, "tree_method": "hist",
                                        "max_bin": 32, "seed": 7})
            res["XGBoost (같은 설정)"] = {"metrics": scored(D, v, te), "trees": n, "seconds": round(time.time() - t, 1)}
        except Exception as e:
            print(f"XGBoost 건너뜀: {e}")
        out["kinds"][kind] = {"test_period": D.period, "n_test": int(D.test.sum()), "config": cfg, "results": res}
        lines += [f"## {kind} (시험 {D.period[0]} ~ {D.period[1]}, {int(D.test.sum()):,}건)", "",
                  "| 방법 | 정반대 | 평균 오차 | 범위 적중 | 방향 맞음 (참고) | 나무 수 | 걸린 시간 |", "|---|---|---|---|---|---|---|"]
        for k, r in res.items():
            m = r["metrics"]
            lines.append(f"| {k} | {m['opposite_pct']:.1f}% | {m['mae_pp']:.2f}%p | {m['range_hit_pct']:.1f}% | {m['direction_hit_pct']:.1f}% | "
                         f"{r.get('trees', '-')} | {r.get('seconds', '-')}{'초' if 'seconds' in r else ''} |")
        lines.append("")
    text = "\n".join(lines)
    print(text)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(text)
    L.save_json("forecast/lightgbm_compare.json", out)
    print("보관함에 저장: models/forecast/lightgbm_compare.json")


if __name__ == "__main__":
    main()
