"""오답노트 — 학습 모델이 왜 틀렸는지 하나하나 기록하고, 그 패턴을 배워 고친 예측이 덜 틀리는지 확인.

실행:  .venv\\Scripts\\python -m experiments.error_notes      (aT · 기상청 API 로 최근 자료를 받음, 약 5분)
결과:  experiments/results/error_notes.json (요약 · 방법 비교) · experiments/results/error_notes_wrong.csv (틀린 예측 전부, 이유 표시)

1. 해마다 굴려 예측 (모두 "그 전 자료로만 학습"): 2023-11 · 2024-11 · 2025-11 부터 1년씩. 설정은 매일 학습 기본값 + 야채는 서울 10년
2. 틀린 예측마다 이유 표시 (아래 TAGS) → 이유별 · 품목별 · 달별로 얼마나 틀리나
3. 반영: 앞 두 해(2023-11 ~ 2025-10) 오답노트로만 고치는 법을 배움 → 고칠 때 안 본 마지막 1년(2025-11 ~)에서 확인
   ① 다시 예측 (쌓기): 학습 모델 예측 + 요인 → 실제 변화율을 한 번 더 배움 (모델이 어느 상황에서 얼마나 빗나가는지)
   ② 방향 직접 고르기: 학습 모델 예측 + 요인 → 오를 · 비슷 · 내릴 각각의 가능성을 배워 가장 큰 쪽
   ③ 품목 · 방향별 치우침 빼기: 오답노트에서 품목마다 '오른다 했을 때 · 내린다 했을 때' 평균 빗나감을 빼 줌
"""
import csv
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from price import forecast_model as FM
from price import learner as L
from price import seoul_history as SH
from price.gbdt import GBDT

RES = Path(__file__).resolve().parent / "results"
GAP = timedelta(10)
YEARS = [date(2023, 11, 1), date(2024, 11, 1), date(2025, 11, 1)]
TAGS = {   # 이유: (설명, 조건) — 조건은 기준일에 이미 아는 값만 씀 (+ 실제 값은 '무엇을 놓쳤나' 표시에만)
    "비슷이라 했는데 움직임": lambda r: r["pc"] == 0 and r["ac"] != 0,
    "정반대": lambda r: r["pc"] * r["ac"] == -1,
    "큰 움직임 (±15% 넘게)": lambda r: abs(r["y"]) >= 15,
    "급등락 직후 (1주 ±15%)": lambda r: abs(r["chg7"]) >= 15,
    "4주 평균보다 크게 위 · 아래 (±20%)": lambda r: abs(r["dev"]) >= 20,
    "명절 3주 안": lambda r: r["to_major"] <= 21,
    "반입량 급변 (±30%)": lambda r: abs(r["vchg"]) >= 30,
    "궂은 날씨 (비 30mm · 한파 · 폭염)": lambda r: r["rain"] >= 30 or r["cold"] >= 1 or r["hot"] >= 1,
    "작년 이맘때와 반대로 예측": lambda r: r["pc"] != 0 and np.sign(r["season"]) == -r["pc"] and abs(r["season"]) >= 3,
}
NOTE_F = ["dev", "trend", "vchg", "rain", "cold", "hot", "volat", "chg3", "chg7", "season", "to_major", "month"]


def cls(x, t=FM.BAND):
    return np.where(x >= t, 1, np.where(x <= -t, -1, 0))


def score(p, y, t=FM.BAND):
    a, b = cls(p, t), cls(y)
    return {"n": int(len(y)), "direction_hit_pct": round(float((a == b).mean() * 100), 1),
            "opposite_pct": round(float(((a * b) == -1).mean() * 100), 1), "mae_pp": round(float(np.abs(p - y).mean()), 2)}


def oos(D, cfg):
    """해마다: t0 이전으로만 학습(나무 수는 그 전 마지막 1년으로) → [t0, t0+1년) 예측. 돌려줌: 예측 (해당 줄만 채움)."""
    X = D.X(cfg["features"])
    pred = np.full(len(D.y), np.nan)
    for t0 in YEARS:
        pre = D.asof < t0 - GAP
        end = D.asof[pre].max()
        fit, val = pre & (D.asof <= end - timedelta(375)), pre & (D.asof > end - timedelta(365))
        probe = L._gbdt(cfg).fit(*D.train(fit, cfg), X[val], D.y[val])
        m = L._gbdt(cfg, max(probe.best_iteration, 20)).fit(*D.train(pre, cfg))
        te = (D.asof >= t0) & (D.asof < t0 + timedelta(365))
        pred[te] = m.predict(X[te])
        print(f"    {t0} ~ 1년 예측 {te.sum():,}건")
    return pred


def notes(D, pred, kind):
    """예측마다 오답노트 한 줄 (틀린 것만 csv 로)."""
    rows = []
    for k in np.where(np.isfinite(pred))[0]:
        r = {f: float(D.cols[f][k]) for f in NOTE_F}
        r = {f: (0.0 if not np.isfinite(v) else v) for f, v in r.items()}
        r.update(kind=kind, item=D.names[D.item[k]], asof=str(D.asof[k]), p=float(pred[k]), y=float(D.y[k]))
        r["pc"], r["ac"] = int(cls(np.array([r["p"]]))[0]), int(cls(np.array([r["y"]]))[0])
        r["wrong"] = r["pc"] != r["ac"]
        r["tags"] = [t for t, f in TAGS.items() if f(r)]
        rows.append(r)
    return rows


def summarize(rows):
    n = len(rows)
    wrong = sum(r["wrong"] for r in rows)
    out = {"n": n, "wrong_pct": round(wrong / n * 100, 1), "tags": {}, "items": {}, "months": {}, "pred_size": {}}
    for t in TAGS:
        sel = [r for r in rows if t in r["tags"]]
        if sel and t not in ("비슷이라 했는데 움직임", "정반대"):
            out["tags"][t] = {"share_pct": round(len(sel) / n * 100, 1), "wrong_pct": round(sum(r["wrong"] for r in sel) / len(sel) * 100, 1)}
    out["kinds_of_wrong"] = {t: round(sum(t in r["tags"] for r in rows) / n * 100, 1) for t in ("비슷이라 했는데 움직임", "정반대")}
    by = defaultdict(list)
    for r in rows:
        by[("items", r["item"])].append(r)
        by[("months", int(r["month"]))].append(r)
        a = abs(r["p"])
        by[("pred_size", "0~2%" if a < 2 else "2~5%" if a < 5 else "5~10%" if a < 10 else "10%+")].append(r)
    for (g, k), sel in sorted(by.items(), key=lambda kv: str(kv[0])):
        out[g][str(k)] = {"n": len(sel), "wrong_pct": round(sum(r["wrong"] for r in sel) / len(sel) * 100, 1),
                          "opposite_pct": round(sum(r["pc"] * r["ac"] == -1 for r in sel) / len(sel) * 100, 1)}
    return out


def fixes(D, pred, cfg):
    """앞 두 해 오답노트로 배우고 → 마지막 1년 확인."""
    learn = np.isfinite(pred) & (D.asof < YEARS[2] - GAP)
    test = np.isfinite(pred) & (D.asof >= YEARS[2])   # 마지막 1년 (그 뒤 며칠은 예측을 안 만들었음)
    feats = [f for f in cfg["features"] if f != "src"]
    Z = np.column_stack([pred, D.X(feats)])   # 첫 칸 = 학습 모델 예측
    cat = [1 + feats.index("item")]
    y = D.y
    out = {"AI (지금)": score(pred[test], y[test])}
    # ① 쌓기: 마지막 1년(2024-11 ~)으로 나무 수 → 두 해 전부로 다시
    lv = learn & (D.asof >= YEARS[1])
    lf = learn & (D.asof < YEARS[1] - GAP)
    p1 = GBDT(cat_cols=cat, n_rounds=2000, **cfg["params"]).fit(Z[lf], y[lf], Z[lv], y[lv])
    m1 = GBDT(cat_cols=cat, n_rounds=max(p1.best_iteration, 20), **cfg["params"]).fit(Z[learn], y[learn])
    out["① 오답노트로 다시 예측 (쌓기)"] = score(m1.predict(Z[test]), y[test])
    # ② 방향 직접 고르기: 오를 · 비슷 · 내릴 각각 (제곱오차로 가능성 배우기)
    prm = {**cfg["params"], "objective": "l2"}
    probs = []
    for c in (1, 0, -1):
        t = (cls(y) == c).astype(float)
        pc = GBDT(cat_cols=cat, n_rounds=2000, **prm).fit(Z[lf], t[lf], Z[lv], t[lv])
        probs.append(GBDT(cat_cols=cat, n_rounds=max(pc.best_iteration, 20), **prm).fit(Z[learn], t[learn]).predict(Z[test]))
    pick = np.array([1, 0, -1])[np.argmax(np.column_stack(probs), axis=1)]
    out["② 오답노트로 방향 직접 고르기"] = score(pick * 3.0, y[test])   # ±3 → 방향만 (평균 오차는 의미 없음)
    out["② 오답노트로 방향 직접 고르기"]["mae_pp"] = None
    # ③ 품목 · 방향별 치우침 빼기
    corr = np.zeros(len(y))
    for i in range(len(D.names)):
        for s in (1, 0, -1):
            k = learn & (D.item == i) & (cls(pred) == s)
            if k.sum() >= 30:
                corr[(D.item == i) & (cls(pred) == s)] = np.median(y[k] - pred[k])
    out["③ 품목 · 방향별 치우침 빼기"] = score(pred[test] + corr[test], y[test])
    return out


def main():
    series, weather, last = L.load_data(upload=False)
    allnotes, result = [], {"data_end": str(last), "kinds": {}}
    for kind in FM.KINDS:
        print(f"\n===== {kind} =====")
        names, rows = L.build_rows(series, weather, kind)
        D = L.Data(names, rows, SH.rows(names) if kind == "야채" else ())
        cfg = dict(L.DEFAULT_CONFIG)
        if kind == "야채":
            cfg = {**cfg, "seoul": True, "features": cfg["features"] + ["src"]}
        pred = oos(D, cfg)
        nt = notes(D, pred, kind)
        allnotes += nt
        s = summarize(nt)
        f = fixes(D, pred, cfg)
        result["kinds"][kind] = {"notes": s, "fixes": f}
        print(f"  오답노트 {s['n']:,}건 중 틀림 {s['wrong_pct']}% — 비슷이라 했는데 움직임 {s['kinds_of_wrong']['비슷이라 했는데 움직임']}% · 정반대 {s['kinds_of_wrong']['정반대']}%")
        print("  이유별 (해당 비율 → 그때 틀린 비율, 전체 " + f"{s['wrong_pct']}%):")
        for t, v in sorted(s["tags"].items(), key=lambda kv: -kv[1]["wrong_pct"]):
            print(f"    {t:<28} {v['share_pct']:5.1f}% → 틀림 {v['wrong_pct']}%")
        print("  예측 폭별: " + " · ".join(f"{k} {v['n']}건 틀림 {v['wrong_pct']}%" for k, v in s["pred_size"].items()))
        worst = sorted(s["items"].items(), key=lambda kv: -kv[1]["wrong_pct"])[:5]
        print("  많이 틀린 품목: " + " · ".join(f"{k} {v['wrong_pct']}%" for k, v in worst))
        worst_m = sorted(s["months"].items(), key=lambda kv: -kv[1]["wrong_pct"])[:3]
        print("  많이 틀린 달: " + " · ".join(f"{k}월 {v['wrong_pct']}%" for k, v in worst_m))
        print("  [반영 → 마지막 1년 확인] 방향 맞음 / 정반대 / 평균 오차")
        for k, v in f.items():
            print(f"    {k:<26} {v['direction_hit_pct']}% / {v['opposite_pct']}% / {v['mae_pp']}")
    (RES / "error_notes.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(RES / "error_notes_wrong.csv", "w", encoding="utf-8-sig", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["종류", "품목", "기준일", "예측 %", "실제 %", "예측 방향", "실제 방향", "틀린 이유"])
        dirs = {1: "오를", 0: "비슷", -1: "내릴"}
        for r in allnotes:
            if r["wrong"]:
                w.writerow([r["kind"], r["item"], r["asof"], round(r["p"], 1), round(r["y"], 1), dirs[r["pc"]], dirs[r["ac"]], " · ".join(r["tags"])])
    print(f"\n저장: {RES / 'error_notes.json'} · {RES / 'error_notes_wrong.csv'}")


if __name__ == "__main__":
    main()
