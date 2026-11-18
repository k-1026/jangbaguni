"""13개 예측 기법을 품목마다 돌려 보고, 실제 값과 가장 비슷한 기법을 품목별로 고름 (기법 매칭).

실행:  .venv\\Scripts\\python -m experiments.method_match            (보관함 자료 + 5년 치 파일, 몇 분)
       .venv\\Scripts\\python -m experiments.method_match --save     (결과를 보관함 models/forecast/matching.json 에 저장)

왜: 품목마다 맞는 기법이 다를 수 있음 (예: 배추는 계절 모델, 양파는 부스팅). 어떤 기법이 맞는지 미리 모르니
    전부 돌려 보고 실제와 가장 가까운 것을 데이터로 고른다.

어떻게 (연도별로 굴려 검증, 학습 기간 길이도 비교)
  시험 2023 ← 그 전 자료로 학습 · 시험 2024 ← 그 전 · 시험 2025-01 ~ 지금 ← 그 전
  학습 기간: 최근 2년 / 최근 3년 / 전부 (대구 경락가가 2021-01부터라 최대 약 4년)
  매칭: 2023 · 2024 시험 성적으로 품목마다 기법을 고르고 → 고를 때 안 본 2025~26 에서 그 선택이 맞았는지 확인
       (고른 기간과 확인 기간을 나눠야 "운 좋게 맞은 기법"을 걸러냄)

13개 기법 (예측 대상은 모두 같음: 기준일 → 7일 뒤 첫 거래일 가격 변화율 %)
  단순     ① 그대로  ② 작년 같은 때(계절 그대로)  ③ 4주 이동평균  ④ 가중 이동평균
  평활     ⑤ 지수평활  ⑥ 홀트(추세)  ⑦ 계절 홀트(주별 계절 지수 + 홀트)
  시계열   ⑧ 자기회귀(AR, 지난 1 · 2 · 3주 변화)  ⑨ 계절 자기회귀(AR + 작년 같은 때)
  회귀     ⑩ 선형회귀(요인 6개)  ⑪ 우리 공식 + 학습 보정 가중치(절대오차 회귀)  ⑫ 우리 고정 공식
  머신러닝 ⑬ 부스팅 (매일 학습 모델과 같은 설정)
"""
import argparse
import json
import math
import time
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

from price import forecast_model as FM
from price import learner as L
from price.gbdt import GBDT

METHODS = ["그대로", "작년 같은 때", "4주 이동평균", "가중 이동평균", "지수평활", "홀트", "계절 홀트",
           "자기회귀", "계절 자기회귀", "선형회귀", "공식+보정", "고정 공식", "부스팅"]
FOLDS = [("2023", date(2023, 1, 1), date(2024, 1, 1)), ("2024", date(2024, 1, 1), date(2025, 1, 1)),
         ("2025~26", date(2025, 1, 1), date(2100, 1, 1))]
WINDOWS = {"2년": 730, "3년": 1095, "전부": 99999}
GAP = timedelta(10)   # 학습 자료의 7일 뒤 값이 시험 기간과 겹치지 않게
SES_GRID = [0.1, 0.2, 0.3, 0.5, 0.7]
HOLT_GRID = [(a, b) for a in (0.1, 0.3, 0.5) for b in (0.05, 0.1, 0.2)]


# ---------------------------------------------------------------
# 품목 하나의 자료 · 기법별 재료
# ---------------------------------------------------------------

def _holt(logp, a, b):
    """지난 값만 써서 매 시점의 수준 · 기울기 (로그 가격)."""
    n = len(logp)
    lv, tr = np.empty(n), np.empty(n)
    l, t = logp[0], 0.0
    for k in range(n):
        if k:
            nl = a * logp[k] + (1 - a) * (l + t)
            t = b * (nl - l) + (1 - b) * t
            l = nl
        lv[k], tr[k] = l, t
    return lv, tr


def _ses(logp, a):
    out = np.empty(len(logp))
    l = logp[0]
    for k, x in enumerate(logp):
        l = a * x + (1 - a) * l if k else x
        out[k] = l
    return out


class Item:
    def __init__(self, name, series, rows):
        self.name = name
        s = series[name]
        self.days = [p[0] for p in s]
        self.logp = np.log([p[1] for p in s])
        pos = {d: k for k, d in enumerate(self.days)}
        self.rows = rows                                    # learner.build_rows 의 이 품목 줄
        self.asof = np.array([r[0] for r in rows])
        self.k = np.array([pos[r[0]] for r in rows])        # 기준일의 거래일 번호
        from bisect import bisect_right
        self.h = np.array([bisect_right(self.days, d + timedelta(6)) - pos[d] for d in self.asof])   # 몇 거래일 뒤
        self.y = np.array([r[4] for r in rows])
        f = lambda key: np.array([r[2][key] for r in rows], dtype=float)
        self.f = {key: f(key) for key in FM.ALL_FEATURES}
        self.formula = np.array([r[3] for r in rows])
        self.ses = {a: _ses(self.logp, a)[self.k] for a in SES_GRID}
        self.holt = {}
        for a, b in HOLT_GRID:
            lv, tr = _holt(self.logp, a, b)
            self.holt[(a, b)] = lv[self.k] + self.h * tr[self.k]
        # 지난 1 · 2 · 3주 변화 (기준일까지 이미 아는 값)
        lp = self.logp
        def back(weeks):
            out = np.full(len(self.k), np.nan)
            for i, (d, k) in enumerate(zip(self.asof, self.k)):
                j = k
                while j > 0 and self.days[j] > d - timedelta(7 * weeks):
                    j -= 1
                j2 = j
                while j2 > 0 and self.days[j2] > d - timedelta(7 * (weeks + 1)):
                    j2 -= 1
                if self.days[j] <= d - timedelta(7 * weeks) and j2 < j:
                    out[i] = (np.exp(lp[j] - lp[j2]) - 1) * 100
            return out
        ma, wma = np.empty(len(self.k)), np.empty(len(self.k))
        for i, (d, k) in enumerate(zip(self.asof, self.k)):
            j = k
            while j > 0 and self.days[j - 1] > d - timedelta(28):
                j -= 1
            seg = np.exp(lp[j: k + 1])
            w = np.arange(1, len(seg) + 1)
            ma[i], wma[i] = seg.mean(), (seg * w).sum() / w.sum()
        last = np.exp(lp[self.k])
        self.ma, self.wma = (ma / last - 1) * 100, (wma / last - 1) * 100
        self.trail = np.array([lp[max(0, k - 250): k + 1].mean() for k in range(len(lp))])
        self.woy = np.array([min(d.isocalendar()[1], 52) for d in self.days])
        self.tgt_w = np.array([min((d + timedelta(7)).isocalendar()[1], 52) for d in self.asof])
        self.r1 = np.array([(np.exp(lp[k] - lp[max(0, k - 6)]) - 1) * 100 for k in self.k])
        self.r2, self.r3 = back(1), back(2)

    def pct(self, logpred):
        return (np.exp(logpred - self.logp[self.k]) - 1) * 100


# ---------------------------------------------------------------
# 기법별 예측 (train 마스크로 맞추고, 전체 시점의 예측을 돌려줌)
# ---------------------------------------------------------------

def _ols(X, y, ridge=1.0):
    Z = np.column_stack([np.ones(len(X)), X])
    A = Z.T @ Z + ridge * np.eye(Z.shape[1])
    A[0, 0] -= ridge
    return np.linalg.solve(A, Z.T @ y)


def _apply(b, X):
    return np.column_stack([np.ones(len(X)), X]) @ b


def _clean(X):
    return np.nan_to_num(X, nan=0.0)


def _lad(X, y, iters=40):
    b = _ols(X, y)
    Z = np.column_stack([np.ones(len(X)), X])
    for _ in range(iters):
        w = 1 / np.maximum(np.abs(y - Z @ b), 1e-3)
        Wz = Z * w[:, None]
        b = np.linalg.solve(Z.T @ Wz + 1e-6 * np.eye(Z.shape[1]), Wz.T @ y)
    return b


def stat_methods(it, train):
    """부스팅을 뺀 12개 기법의 예측 (%)."""
    P, f = {}, it.f
    P["그대로"] = np.zeros(len(it.y))
    P["작년 같은 때"] = np.nan_to_num(f["season"])
    P["4주 이동평균"], P["가중 이동평균"] = it.ma, it.wma
    mae = lambda p: np.abs(p[train] - it.y[train]).mean()
    P["지수평활"] = min((it.pct(it.ses[a]) for a in SES_GRID), key=mae)
    P["홀트"] = min((it.pct(it.holt[g]) for g in HOLT_GRID), key=mae)
    # 계절 홀트: 로그 가격 − 최근 1년 평균 → 주(週)별 계절 지수 (학습 기간에서만 계산) → 계절을 뺀 값에 홀트 → 다시 더함
    lp = it.logp
    first = it.asof[train].min() if train.any() else None
    lastd = it.asof[train].max() if train.any() else None
    in_tr = np.array([first is not None and first <= d <= lastd for d in it.days])
    dev = lp - it.trail
    si = np.zeros(53)
    for w in range(1, 53):
        m = (it.woy == w) & in_tr
        si[w] = dev[m].mean() if m.sum() >= 3 else 0.0
    des = lp - si[it.woy]
    tgt_w = it.tgt_w
    best = None
    for a, b in HOLT_GRID:
        lv, trd = _holt(des, a, b)
        p = it.pct(lv[it.k] + it.h * trd[it.k] + si[tgt_w])
        if best is None or mae(p) < mae(best):
            best = p
    P["계절 홀트"] = best
    # 자기회귀: 지난 1 · 2 · 3주 변화 → 다음 7일 변화
    Xar = _clean(np.column_stack([it.r1, it.r2, it.r3]))
    P["자기회귀"] = _apply(_ols(Xar[train], it.y[train]), Xar)
    Xsar = np.column_stack([Xar, _clean(f["season"])])
    P["계절 자기회귀"] = _apply(_ols(Xsar[train], it.y[train]), Xsar)
    Xlr = _clean(np.column_stack([f[k] for k in ("dev", "vchg", "wx", "chg3", "season", "to_major")]))
    P["선형회귀"] = _apply(_ols(Xlr[train], it.y[train], ridge=5.0), Xlr)
    Xf = _clean(np.column_stack([f["dev"], f["vchg"], f["wx"]]))
    lo, hi = np.percentile(Xf[train], 1, axis=0), np.percentile(Xf[train], 99, axis=0)
    Xf = np.clip(Xf, lo, hi)
    P["공식+보정"] = _apply(_lad(Xf[train], it.y[train]), Xf)
    P["고정 공식"] = it.formula
    return {k: np.clip(v, -60, 60) for k, v in P.items()}


# ---------------------------------------------------------------
# 채점 · 매칭
# ---------------------------------------------------------------

def score(p, y):
    cls = lambda x: np.where(x >= FM.BAND, 1, np.where(x <= -FM.BAND, -1, 0))
    return {"n": int(len(y)), "mae_pp": round(float(np.abs(p - y).mean()), 3),
            "opposite_pct": round(float(((cls(p) * cls(y)) == -1).mean() * 100), 2)}


def run(kinds, save=False):
    t0 = time.time()
    series, weather, last = L.load_data(upload=False)
    out = {"made": str(date.today()), "data_end": str(last), "kinds": {}}
    for kind in kinds:
        names, rows = L.build_rows(series, weather, kind)
        D = L.Data(names, rows)
        cfg = (L.load_json(f"forecast/{FM.KINDS[kind]}.json", None) or {}).get("config") or L.DEFAULT_CONFIG
        Xb = D.X(cfg["features"])
        by_item = defaultdict(list)
        for r in rows:
            by_item[r[1]].append(r)
        items = {i: Item(names[i], series, rs) for i, rs in by_item.items()}
        # preds[fold][window][method] = 전체 줄 순서의 예측 (해당 시험 줄만 채움)
        res = {}   # (fold, window, item, method) → score
        pooled = defaultdict(lambda: ([], []))   # (fold, window, method) → (예측들, 실제들)
        for fname, start, end in FOLDS:
            test_all = (D.asof >= start) & (D.asof < end)
            for wname, wdays in WINDOWS.items():
                trw = (D.asof < start - GAP) & (D.asof >= start - timedelta(wdays))
                if wname != "전부" and (start - timedelta(wdays)) < date(2021, 3, 1):
                    continue   # 자료가 그만큼 길지 않으면 같은 결과라 건너뜀
                gb = GBDT(cat_cols=[cfg["features"].index("item")], n_rounds=400, **cfg["params"]).fit(Xb[trw], D.y[trw])
                gbp = gb.predict(Xb)
                for i, it in items.items():
                    tr = (it.asof < start - GAP) & (it.asof >= start - timedelta(wdays))
                    te = (it.asof >= start) & (it.asof < end)
                    if tr.sum() < 100 or te.sum() < 20:
                        continue
                    P = stat_methods(it, tr)
                    P["부스팅"] = gbp[D.item == i]
                    for m in METHODS:
                        res[(fname, wname, it.name, m)] = score(P[m][te], it.y[te])
                        pooled[(fname, wname, m)][0].append(P[m][te])
                        pooled[(fname, wname, m)][1].append(it.y[te])
            print(f"  [{kind}] 시험 {fname} 끝 ({round(time.time() - t0)}초)")
        out["kinds"][kind] = summarize(kind, names, res, pooled)
    print(f"\n끝 ({round(time.time() - t0)}초)")
    if save:
        L.save_json("forecast/matching.json", out)
        print("보관함에 저장: models/forecast/matching.json")
    return out


def summarize(kind, names, res, pooled):
    print(f"\n===== {kind} =====")
    # 1) 학습 기간 길이 비교 (2025~26 시험, 품목 전체)
    print("\n[학습 기간 길이 · 2025~26 시험 · 평균 오차 %p / 정반대 %]")
    win_table = {}
    for m in METHODS:
        cells = {}
        for w in WINDOWS:
            k = ("2025~26", w, m)
            if k in pooled:
                cells[w] = score(np.concatenate(pooled[k][0]), np.concatenate(pooled[k][1]))
        win_table[m] = cells
        print(f"  {m:<10}" + "".join(f"  {w} {c['mae_pp']:6.2f} / {c['opposite_pct']:5.1f}" for w, c in cells.items()))
    # 2) 기간별 기법 성적 (전부 기간 학습)
    print("\n[연도별 시험 · 전부 학습 · 평균 오차 %p]")
    fold_table = {}
    for m in METHODS:
        fold_table[m] = {f: score(np.concatenate(pooled[(f, '전부', m)][0]), np.concatenate(pooled[(f, '전부', m)][1]))
                         for f, _, _ in FOLDS if (f, "전부", m) in pooled}
        print(f"  {m:<10}" + "".join(f"  {f} {c['mae_pp']:6.2f}" for f, c in fold_table[m].items()))
    # 3) 매칭: 2023 · 2024 평균 오차로 품목마다 (기법, 학습 기간) 고름 → 2025~26 에서 확인
    #    단 '그대로'보다 평균 오차가 작아야 후보 (그대로는 정반대가 늘 0%라 정반대로는 못 고름)
    match, check = {}, {}
    for name in names:
        cand = []
        for m in METHODS:
            for w in WINDOWS:
                s = [res.get((f, w, name, m)) for f in ("2023", "2024")]
                if all(s):
                    cand.append((np.mean([x["mae_pp"] for x in s]), m, w))
        if not cand:
            continue
        mae, m, w = min(cand)
        later = res.get(("2025~26", w, name, m))
        if not later:
            continue
        match[name] = {"method": m, "window": w, "select_mae_pp": round(float(mae), 3)}
        check[name] = {"matched": later, "boost": res[("2025~26", "전부", name, "부스팅")],
                       "formula": res[("2025~26", "전부", name, "고정 공식")], "naive": res[("2025~26", "전부", name, "그대로")]}
    def agg(key):
        n = sum(c[key]["n"] for c in check.values())
        return {"mae_pp": round(sum(c[key]["mae_pp"] * c[key]["n"] for c in check.values()) / n, 3),
                "opposite_pct": round(sum(c[key]["opposite_pct"] * c[key]["n"] for c in check.values()) / n, 2), "n": n}
    total = {k: agg(k) for k in ("matched", "boost", "formula", "naive")}
    print("\n[품목별 매칭: 2023 · 2024로 고름 → 고를 때 안 본 2025~26 결과 (평균 오차 %p / 정반대 %)]")
    for name in names:
        if name in match:
            c = check[name]
            print(f"  {name:<6} → {match[name]['method']:<8}({match[name]['window']})  "
                  f"매칭 {c['matched']['mae_pp']:6.2f} / {c['matched']['opposite_pct']:5.1f}   "
                  f"부스팅 {c['boost']['mae_pp']:6.2f} / {c['boost']['opposite_pct']:5.1f}   "
                  f"공식 {c['formula']['mae_pp']:6.2f} / {c['formula']['opposite_pct']:5.1f}")
    print(f"\n  전체  품목별 매칭 {total['matched']['mae_pp']:.2f} / {total['matched']['opposite_pct']:.1f}%   "
          f"부스팅 하나 {total['boost']['mae_pp']:.2f} / {total['boost']['opposite_pct']:.1f}%   "
          f"고정 공식 {total['formula']['mae_pp']:.2f} / {total['formula']['opposite_pct']:.1f}%   "
          f"그대로 {total['naive']['mae_pp']:.2f}")
    cnt = defaultdict(int)
    for v in match.values():
        cnt[v["method"]] += 1
    print("  매칭된 기법: " + " · ".join(f"{k} {v}개" for k, v in sorted(cnt.items(), key=lambda x: -x[1])))
    return {"windows_2025": win_table, "folds_all_window": fold_table, "match": match, "check_2025": check, "total_2025": total}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--kinds", nargs="*", default=list(FM.KINDS))
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args()
    run(a.kinds, a.save)
