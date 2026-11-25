"""시중 시계열 모델(Amazon Chronos-Bolt, 공개 · 무료) vs 우리 학습 모델 — 같은 시험 1년 · 같은 채점.

두 단계 (Chronos 는 torch 가 필요해 프로젝트 환경과 따로 돌림)
  1) 프로젝트 환경:  .venv\\Scripts\\python -m experiments.chronos_compare dump <파일.json>
     → 품목별 대구 경락가 · 시험 줄(기준일 · 몇 거래일 뒤 · 실제 변화) · 우리 AI 예측을 파일로
  2) Chronos 환경:   <torch · chronos-forecasting 설치한 python> experiments/chronos_compare.py run <파일.json> [모델 이름]
     → 기준일까지의 값만 보고 h 거래일 뒤 값을 예측(가운데 값) → 변화율 → 방향 맞음 · 정반대 · 평균 오차
     모델 이름 기본 amazon/chronos-bolt-small (약 4,800만 개 숫자, CPU 로 몇 분). 처음 한 번 Hugging Face 에서 내려받음
Chronos 는 값의 흐름만 봄 (반입량 · 날씨 · 명절은 모름) — "아무 정보 없이 값만으로" 얼마나 맞히는지의 기준
"""
import json
import sys
from bisect import bisect_right
from datetime import date, timedelta

import numpy as np

BAND = 2.0


def dump(path):
    from experiments.direction_tune import preds
    from price import forecast_model as FM
    from price import learner as L
    from price import seoul_history as SH
    series, weather, last = L.load_data(upload=False)
    out = {"data_end": str(last), "kinds": {}}
    for kind in FM.KINDS:
        names, rows = L.build_rows(series, weather, kind)
        D = L.Data(names, rows, SH.rows(names) if kind == "야채" else ())
        cfg = dict(L.DEFAULT_CONFIG)
        if kind == "야채":
            cfg = {**cfg, "seoul": True, "features": cfg["features"] + ["src"]}
        _, pt = preds(D, cfg)
        test = []
        for k, p in zip(np.where(D.test)[0], pt):
            name = names[D.item[k]]
            days = [x[0] for x in series[name]]
            i = days.index(D.asof[k])
            j = bisect_right(days, D.asof[k] + timedelta(6))
            test.append([name, i, j - i, float(D.y[k]), float(p), float(D.formula[k])])
        out["kinds"][kind] = {"period": D.period, "series": {n: [x[1] for x in series[n]] for n in names}, "test": test}
        print(f"{kind}: 시험 {len(test):,}건")
    open(path, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False))


def score(p, y):
    c = lambda x: np.where(x >= BAND, 1, np.where(x <= -BAND, -1, 0))
    a, b = c(p), c(y)
    return {"n": int(len(y)), "direction_hit_pct": round(float((a == b).mean() * 100), 1),
            "opposite_pct": round(float(((a * b) == -1).mean() * 100), 1), "mae_pp": round(float(np.abs(p - y).mean()), 2)}


def run(path, model="amazon/chronos-bolt-small", ctx=512, batch=256):
    import torch
    from chronos import BaseChronosPipeline
    pipe = BaseChronosPipeline.from_pretrained(model, device_map="cpu", torch_dtype=torch.float32)
    data = json.load(open(path, encoding="utf-8"))
    res = {"model": model, "kinds": {}}
    for kind, d in data["kinds"].items():
        T = d["test"]
        hmax = max(t[2] for t in T)
        chron = np.empty(len(T))
        for s in range(0, len(T), batch):
            part = T[s: s + batch]
            contexts = [torch.tensor(np.log(d["series"][n][max(0, i - ctx + 1): i + 1]), dtype=torch.float32) for n, i, *_ in part]
            q, mean = pipe.predict_quantiles(contexts, prediction_length=hmax, quantile_levels=[0.5])
            for r, (n, i, h, *_rest) in enumerate(part):
                chron[s + r] = (np.exp(float(q[r, h - 1, 0]) - np.log(d["series"][n][i])) - 1) * 100
            print(f"  {kind} {min(s + batch, len(T)):,}/{len(T):,}", flush=True)
        y = np.array([t[3] for t in T])
        ai = np.array([t[4] for t in T])
        res["kinds"][kind] = {"period": d["period"], "Chronos (값만)": score(chron, y), "우리 AI": score(ai, y),
                              "고정 공식": score(np.array([t[5] for t in T]), y), "Chronos + AI 평균": score((chron + ai) / 2, y)}
        print(f"\n[{kind} 시험 {d['period'][0]} ~ {d['period'][1]}, {len(T):,}건]  방향 맞음 / 정반대 / 평균 오차")
        for k, v in res["kinds"][kind].items():
            if k != "period":
                print(f"  {k:<18} {v['direction_hit_pct']}% / {v['opposite_pct']}% / {v['mae_pp']}%p")
    out = path.replace(".json", "_result.json")
    open(out, "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"\n저장: {out}")


if __name__ == "__main__":
    {"dump": lambda: dump(sys.argv[2]), "run": lambda: run(sys.argv[2], *sys.argv[3:4])}[sys.argv[1]]()
