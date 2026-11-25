"""시중 표(tabular) 모델 vs 우리 학습 모델 — 같은 요인 · 같은 학습 자료 · 같은 시험 1년 · 같은 채점.

두 단계 (scikit-learn · CatBoost · TabPFN 은 프로젝트 환경에 없어서 따로 돌림)
  1) 프로젝트 환경:  .venv\\Scripts\\python -m experiments.tabular_compare dump <파일.npz>
  2) 비교 환경:      <scikit-learn · catboost · lightgbm · xgboost · tabpfn 설치한 python> experiments/tabular_compare.py run <파일.npz>
비교: 변화율을 맞히는 모델(회귀)은 ±2% 로 방향을 정하고, 방향을 바로 고르는 모델(분류)은 오를 · 비슷 · 내릴 중 가장 큰 쪽
"""
import json
import sys
import time

import numpy as np

BAND = 2.0


def dump(path):
    from experiments.direction_tune import preds
    from price import forecast_model as FM
    from price import learner as L
    from price import seoul_history as SH
    series, weather, last = L.load_data(upload=False)
    arrs, meta = {}, {"data_end": str(last), "kinds": {}}
    for kind, key in FM.KINDS.items():
        names, rows = L.build_rows(series, weather, kind)
        D = L.Data(names, rows, SH.rows(names) if kind == "야채" else ())
        cfg = dict(L.DEFAULT_CONFIG)
        if kind == "야채":
            cfg = {**cfg, "seoul": True, "features": cfg["features"] + ["src"]}
        pv, pt = preds(D, cfg)
        Xtr, ytr = D.train(D.pre, cfg)
        Xfit, yfit = D.train(D.fit, cfg)
        X = D.X(cfg["features"])
        arrs.update({f"{key}_Xtr": Xtr, f"{key}_ytr": ytr, f"{key}_Xfit": Xfit, f"{key}_yfit": yfit,
                     f"{key}_Xval": X[D.val], f"{key}_yval": D.y[D.val], f"{key}_Xte": X[D.test], f"{key}_yte": D.y[D.test],
                     f"{key}_ai": pt, f"{key}_formula": D.formula[D.test]})
        meta["kinds"][kind] = {"key": key, "features": cfg["features"], "period": D.period, "n_items": len(names)}
        print(f"{kind}: 학습 {len(ytr):,} · 시험 {D.test.sum():,}")
    np.savez_compressed(path, **arrs)
    open(path.replace(".npz", ".json"), "w", encoding="utf-8").write(json.dumps(meta, ensure_ascii=False))


def cls(x):
    return np.where(x >= BAND, 1, np.where(x <= -BAND, -1, 0))


def score(pred_cls, y, p=None):
    b = cls(y)
    return {"n": int(len(y)), "direction_hit_pct": round(float((pred_cls == b).mean() * 100), 1),
            "opposite_pct": round(float(((pred_cls * b) == -1).mean() * 100), 1),
            "mae_pp": round(float(np.abs(p - y).mean()), 2) if p is not None else None}


def run(path, tabpfn_rows=10000):
    from sklearn.compose import make_column_transformer
    from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingClassifier, HistGradientBoostingRegressor, RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.neural_network import MLPRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    A = np.load(path)
    meta = json.load(open(path.replace(".npz", ".json"), encoding="utf-8"))
    res = {"kinds": {}}
    for kind, m in meta["kinds"].items():
        k = m["key"]
        Xtr, ytr, Xte, yte = A[f"{k}_Xtr"], A[f"{k}_ytr"], A[f"{k}_Xte"], A[f"{k}_yte"]
        item = m["features"].index("item")
        num = [i for i in range(Xtr.shape[1]) if i != item]
        prep = lambda: make_column_transformer(   # 선형 · 신경망용: 품목은 한 칸씩, 숫자는 빈 값 채우고 크기 맞춤
            (OneHotEncoder(handle_unknown="ignore"), [item]),
            (make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler()), num))
        imp = lambda: SimpleImputer(strategy="median", add_indicator=True)
        reg = {
            "랜덤 포레스트": lambda: make_pipeline(imp(), RandomForestRegressor(300, min_samples_leaf=50, n_jobs=-1, random_state=7)),
            "엑스트라 트리": lambda: make_pipeline(imp(), ExtraTreesRegressor(300, min_samples_leaf=50, n_jobs=-1, random_state=7)),
            "HistGradientBoosting (절대오차)": lambda: HistGradientBoostingRegressor(loss="absolute_error", categorical_features=[item], random_state=7),
            "MLP 신경망": lambda: make_pipeline(prep(), MLPRegressor(hidden_layer_sizes=(64, 32), alpha=1e-3, early_stopping=True, max_iter=300, random_state=7)),
        }
        clf = {
            "HistGradientBoosting 분류": lambda: HistGradientBoostingClassifier(categorical_features=[item], random_state=7),
            "로지스틱 회귀 분류": lambda: make_pipeline(prep(), LogisticRegression(max_iter=2000)),
        }
        try:
            import lightgbm as lgb
            reg["LightGBM (기본, 절대오차)"] = lambda: lgb.LGBMRegressor(objective="l1", verbose=-1, random_state=7)
        except ImportError:
            pass
        try:
            import xgboost as xgb
            reg["XGBoost (기본, 절대오차)"] = lambda: xgb.XGBRegressor(objective="reg:absoluteerror", random_state=7)
        except ImportError:
            pass
        try:
            from catboost import CatBoostClassifier, CatBoostRegressor
            reg["CatBoost (절대오차)"] = lambda: CatBoostRegressor(loss_function="MAE", iterations=1000, verbose=0, random_seed=7)
            clf["CatBoost 분류"] = lambda: CatBoostClassifier(loss_function="MultiClass", iterations=1000, verbose=0, random_seed=7)
        except ImportError:
            pass
        out = {"우리 AI (gbdt.py)": score(cls(A[f"{k}_ai"]), yte, A[f"{k}_ai"]),
               "고정 공식": score(cls(A[f"{k}_formula"]), yte, A[f"{k}_formula"])}
        print(f"\n[{kind} 시험 {m['period'][0]} ~ {m['period'][1]}, 학습 {len(ytr):,} · 시험 {len(yte):,}건]  방향 맞음 / 정반대 / 평균 오차 / 걸린 시간")
        for name in ("우리 AI (gbdt.py)", "고정 공식"):
            print(f"  {name:<32} {out[name]['direction_hit_pct']}% / {out[name]['opposite_pct']}% / {out[name]['mae_pp']}%p")
        for name, mk in reg.items():
            t = time.time()
            p = mk().fit(Xtr, ytr).predict(Xte)
            out[name] = {**score(cls(p), yte, p), "seconds": round(time.time() - t)}
            print(f"  {name:<32} {out[name]['direction_hit_pct']}% / {out[name]['opposite_pct']}% / {out[name]['mae_pp']}%p / {out[name]['seconds']}초", flush=True)
        for name, mk in clf.items():
            t = time.time()
            p = np.asarray(mk().fit(Xtr, cls(ytr)).predict(Xte)).ravel().astype(int)
            out[name] = {**score(p, yte), "seconds": round(time.time() - t)}
            print(f"  {name:<32} {out[name]['direction_hit_pct']}% / {out[name]['opposite_pct']}% / - / {out[name]['seconds']}초", flush=True)
        try:   # 사전학습 표 모델: 학습 자료가 많으면 느려서 최근 tabpfn_rows 줄만 보여 줌
            from tabpfn import TabPFNClassifier, TabPFNRegressor
            sl = slice(-tabpfn_rows, None)
            for name, mk, target in (("TabPFN 회귀 (최근 1만 줄)", TabPFNRegressor, ytr), ("TabPFN 분류 (최근 1만 줄)", TabPFNClassifier, cls(ytr))):
                t = time.time()
                model = mk(device="cpu", ignore_pretraining_limits=True).fit(Xtr[sl], target[sl])
                p = np.concatenate([model.predict(Xte[s: s + 500]) for s in range(0, len(Xte), 500)])
                out[name] = {**(score(cls(p), yte, p) if target is ytr else score(p.astype(int), yte)), "seconds": round(time.time() - t)}
                print(f"  {name:<32} {out[name]['direction_hit_pct']}% / {out[name]['opposite_pct']}% / {out[name]['mae_pp']} / {out[name]['seconds']}초", flush=True)
        except Exception as e:
            print(f"  TabPFN 건너뜀: {type(e).__name__}: {str(e)[:200]}")
        res["kinds"][kind] = {"period": m["period"], "results": out}
    o = path.replace(".npz", "_result.json")
    open(o, "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"\n저장: {o}")


if __name__ == "__main__":
    {"dump": lambda: dump(sys.argv[2]), "run": lambda: run(sys.argv[2])}[sys.argv[1]]()
