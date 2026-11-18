"""판매량 학습: 시연 가게 더미 판매 기록(data/dummy_store)으로 부스팅을 한 번 학습 → models/demand_demo.json.

순서
  1. dummy_store.py 가 만든 1년 치 판매 기록 · 날짜별 요인(날씨 · 공휴일 · 홈경기 · 축제)을 읽음
  2. 메뉴 × 날짜마다 요인을 계산 (demand_model.make_features — 화면 예측과 같은 계산)
  3. 마지막 6달을 28일씩 굴려 가며 시험: 그 달 앞 기록으로만 학습(마지막 28일은 나무 개수를 정하는 검증) → 그 달 예측
  4. 같은 날들을 지금 규칙(demand.py: 요일 · 최근 2주 흐름 · 공휴일)으로도 예측해 비교 (전체 · 메뉴별 · 특별한 날별)
  5. 시험이 끝나면 전체 기록으로 다시 학습해 저장 (화면은 이 모델로 내일을 예측)

실행:  .venv\\Scripts\\python -m demand.demand_learn
가상 데이터라 '실제 가게에서 이만큼 맞는다'가 아니라 '판매 기록을 넣으면 학습해서 예측하는 구조가 동작한다'를 보여 주는 것
"""
import csv
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from demand import demand_model as DM
from demand import dummy_store as DS
from price.gbdt import GBDT

KST = timezone(timedelta(hours=9))
DATA = DS.OUT
FOLDS = 6   # 마지막 6달(28일씩)을 차례로 시험
PARAMS = {"learning_rate": 0.05, "max_depth": 2, "min_leaf": 20, "objective": "l2", "l2": 5.0}


def read(name):
    with open(DATA / name, encoding="utf-8-sig") as fp:
        return list(csv.DictReader(fp))


def load():
    menus = [r["메뉴"] for r in read("menus.csv")]
    hist = defaultdict(lambda: defaultdict(int))
    for r in read("sales_daily.csv"):
        hist[r["메뉴"]][date.fromisoformat(r["날짜"])] += int(r["그릇수"])
    cal = {}
    for r in read("calendar.csv"):
        t = float(r["평균기온"]) if r["평균기온"] not in ("", "None") else None
        tmax = float(r["최고기온"]) if r["최고기온"] not in ("", "None") else None
        cal[date.fromisoformat(r["날짜"])] = {
            "closed": r["휴무"] == "1", "holiday": bool(r["공휴일"]), "avg_temp": t,
            "rainy": float(r["비mm"] or 0) >= 5, "hot": tmax is not None and tmax >= 33,
            "home_game": r["삼성_홈경기"] == "1", "festival": r["축제"] == "1"}
    return menus, {m: sorted(v.items()) for m, v in hist.items()}, cal


def rows(menus, hist, cal):
    out = []   # (날짜, 메뉴, 요인, 평소 수준, 실제)
    for i, m in enumerate(menus):
        h = hist[m]
        for d, q in h:
            f, level = DM.make_features(i, h, d, cal[d])
            if level:
                out.append((d, m, f, level, q))
    return out


def X(rs):
    return np.array([[r[2][k] for k in DM.FEATURES] for r in rs], dtype=float)


def rule_predict(hist, d, holidays):
    """지금 규칙(demand.py) 으로 d 하루 예측 — d 이전 기록만 씀."""
    from demand import demand
    daily = {x: q for x, q in hist if x < d}
    model = demand._MenuModel(daily, holidays)
    mid, lo, hi, _f = model.predict(d, holidays)
    return mid, lo, hi


def score(pred, act, lo=None, hi=None):
    pred, act = np.asarray(pred, float), np.asarray(act, float)
    out = {"mae_bowls": round(float(np.abs(pred - act).mean()), 2),
           "mape_pct": round(float((np.abs(pred - act) / np.maximum(act, 1)).mean() * 100), 2)}
    if lo is not None:
        out["range_hit_pct"] = round(float(((act >= np.asarray(lo)) & (act <= np.asarray(hi))).mean() * 100), 1)
    return out


def special(d, c):
    """특별한 날 이름 (비교표용)."""
    if c["holiday"]:
        return "공휴일"
    if c["hot"]:
        return "폭염"
    if c["home_game"]:
        return "삼성 홈경기"
    if c["festival"]:
        return "대구 축제"
    if 25 <= d.day <= 28:
        return "월급날 무렵"
    return "보통 날"


def fit(train, val):
    g = GBDT(cat_cols=[DM.FEATURES.index("menu")], n_rounds=4000, **PARAMS)
    yv = lambda s: np.array([r[4] / r[3] for r in s])
    return g.fit(X(train), yv(train), X(val), yv(val), early_stop=300)


def main():
    menus, hist, cal = load()
    rs = rows(menus, hist, cal)
    last = max(r[0] for r in rs)
    holidays = {str(d) for d, c in cal.items() if c["holiday"]}
    # 한 달(28일)씩 굴려 가며 시험: 그 달 앞 기록으로만 학습(마지막 28일은 나무 개수 정하는 검증) → 그 달 예측
    out, ratios, rounds = [], [], []
    for k in range(FOLDS, 0, -1):
        t0, t1 = last - timedelta(28 * k - 1), last - timedelta(28 * (k - 1))
        v0 = t0 - timedelta(28)
        tr = [r for r in rs if r[0] < v0]
        va = [r for r in rs if v0 <= r[0] < t0]
        te = [r for r in rs if t0 <= r[0] <= t1]
        g = fit(tr, va)
        rounds.append(g.best_iteration)
        pv = g.predict(X(va)) * np.array([r[3] for r in va])
        ratios += list(np.array([r[4] for r in va]) / np.maximum(pv, 1))
        pt = g.predict(X(te)) * np.array([r[3] for r in te])
        for r, p in zip(te, pt):
            out.append((r, float(p), rule_predict(hist[r[1]], r[0], holidays)))
        print(f"  {t0} ~ {t1}: 학습 {len(tr):,}건 · 나무 {g.best_iteration}개")
    lo_q, hi_q = float(np.quantile(ratios, 0.10)), float(np.quantile(ratios, 0.90))
    act = [o[0][4] for o in out]
    ai = score([o[1] for o in out], act, [o[1] * lo_q for o in out], [o[1] * hi_q for o in out])
    base = score([o[2][0] for o in out], act, [o[2][1] for o in out], [o[2][2] for o in out])

    def part(sel):
        sub = [o for o in out if sel(o)]
        a = [o[0][4] for o in sub]
        return {"rows": len(sub), "ai": score([o[1] for o in sub], a), "rule": score([o[2][0] for o in sub], a)}

    per_menu = {m: part(lambda o, m=m: o[0][1] == m) for m in menus}
    per_day = {n: part(lambda o, n=n: special(o[0][0], cal[o[0][0]]) == n)
               for n in ("보통 날", "공휴일", "폭염", "삼성 홈경기", "대구 축제", "월급날 무렵")}
    n_rounds = int(np.median(rounds))
    final = GBDT(cat_cols=[DM.FEATURES.index("menu")], n_rounds=n_rounds, **PARAMS).fit(X(rs), np.array([r[4] / r[3] for r in rs]))
    imp = final.importance(len(DM.FEATURES))
    importance = {f: round(float(v / imp.sum() * 100)) for f, v in sorted(zip(DM.FEATURES, imp), key=lambda x: -x[1])}

    period = [str(out[0][0][0]), str(last)]
    print(f"시험 {period[0]} ~ {period[1]} ({len(out):,}건)")
    print(f"지금 규칙  {base}")
    print(f"학습 모델  {ai}")
    for n, s in {**per_menu, **per_day}.items():
        if s["rows"]:
            print(f"  {n:<7} {s['rows']:>4}건  규칙 {s['rule']['mae_bowls']:5.2f}그릇 → 학습 {s['ai']['mae_bowls']:5.2f}그릇")
    print("요인 중요도 %", importance)

    blob = {
        "version": f"demand-demo-{datetime.now(KST):%Y%m%d}", "features": DM.FEATURES, "menus": menus,
        "booster": final.export(), "range_ratio": [round(lo_q, 4), round(hi_q, 4)],
        "metrics": {"test_period": period, "folds": FOLDS, "ai": ai, "rule": base, "per_menu": per_menu,
                    "per_day": per_day, "importance": importance, "n_rounds": n_rounds, "params": PARAMS},
        "home_games": sorted(str(d) for d in DS.load_home_games()),
        "festivals": [[str(a), str(b)] for a, b, _n in DS.load_festivals()],
        "data": f"가상 데이터 (dummy_store.py, {min(r[0] for r in rs)} ~ {last})",
    }
    DM.PATH.parent.mkdir(exist_ok=True)
    DM.PATH.write_text(json.dumps(blob, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"저장: {DM.PATH} ({DM.PATH.stat().st_size // 1024}KB)")


if __name__ == "__main__":
    main()
