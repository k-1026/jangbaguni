"""10년 치 서울 도매가로 학습 기간 늘리기 실험 (계획 M9).

실행:  .venv\\Scripts\\python -m experiments.train_length_10y      (파일 자료만 씀, API 호출 없음, 몇 분)
결과:  experiments/results/train_length_10y.json · 정리 plan/forecast/1125_train_length_10y.md

왜: 대구 북부도매 경락가가 2021-01부터라 학습 기간이 최대 약 4년. 11/16 실험에서 "길수록 조금씩 좋아짐"이 보였는데
    (부스팅 야채 2년 18.85 → 3년 18.69 → 전부 18.40%p) 4년 너머도 그런지 몰랐음.

자료: 서울 가락 중도매 '상품' 조사가 (aT 일별 도·소매 = KAMIS) 2016-01 ~ 2025-08, 약 10년
      2016~2019 = data/raw/1124_veg_past_seoul_daegu/seoul_1101 · 2020~2025-08 = data/raw/1112_*.csv.xz (서울 · 도매)
      두 파일의 2019-12 · 2020-01 품종별 kg당 값이 이어지는 것을 확인함 (같은 품목 코드 · 품종 코드)

실험 1 (서울 안에서): 학습 기간 2 · 3 · 4 · 5 · 6년 · 전부 → 같은 1년 시험 (2023-09~2024-08, 2024-09~2025-08 두 번)
    요인은 값으로만 만든 것 (반입량 · 대구 날씨는 서울에 없음): 품목 · 4주 평균 차이 · 2주 기울기 · 변동성 · 3거래일 · 1주 변화
    · 지난 해 같은 때 · 명절까지 남은 날 · 월
실험 2 (대구 시험, 실제 서비스 모델): 대구 최근 1년 시험에서
    ① 대구만 (지금 매일 학습과 같은 요인 · 설정) ② + 서울 2016~ 자료를 학습에 섞기 ③ + 서울 2021~ 만 섞기 (기간 효과 vs 자료 양 효과 구분)
    서울 줄의 반입량 · 날씨 요인은 빈 값(부스팅이 빈 값 칸으로 따로 다룸)
실험 3 (서울을 섞어 나빠진 품목 줄이기): 출처 요인 · 두 모델 평균 · 품목별 고르기 — 고르기는 시험 전 1년(검증)으로만
실험 4 (시험 해 바꾸기): 2023-11 · 2024-11 · 2025-11 부터 1년씩, 대구만 · + 서울 · + 출처 요인 · 두 모델 평균
채점: 7일 뒤 변화율 예측의 평균 오차(%p) · 정반대(±2% 기준) — learner.py · method_match.py 와 같음
"""
import json
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from price import backtest as B
from price import forecast_model as FM
from price import learner as L
from price.gbdt import GBDT
from price import seoul_history as SH

OUT = Path(__file__).resolve().parent / "results" / "train_length_10y.json"
PRICE_FEATS = ["item", "dev", "trend", "volat", "chg3", "chg7", "season", "to_major", "month"]
GAP = timedelta(10)   # 학습 자료의 7일 뒤 값이 시험 기간과 겹치지 않게
TESTS = [("2023-09~2024-08", date(2023, 9, 1), date(2024, 9, 1)), ("2024-09~2025-08", date(2024, 9, 1), date(2025, 9, 1))]
WINDOWS = [("2년", 2), ("3년", 3), ("4년", 4), ("5년", 5), ("6년", 6), ("전부", 99)]


load_seoul = SH.load


def seoul_rows(series, names):
    return SH.rows(names, series)


def arrays(rows, feats):
    return (np.array([r[0] for r in rows]), np.array([r[1] for r in rows]),
            np.array([[r[2][k] for k in feats] for r in rows], dtype=float), np.array([r[4] for r in rows]))


def score(p, y):
    cls = lambda x: np.where(x >= FM.BAND, 1, np.where(x <= -FM.BAND, -1, 0))
    return {"n": int(len(y)), "mae_pp": round(float(np.abs(p - y).mean()), 3),
            "opposite_pct": round(float(((cls(p) * cls(y)) == -1).mean() * 100), 2)}


def fit_predict(X, y, asof, train, val_mask, Xt, params, cat):
    """학습 자료 안 마지막 1년(val_mask 가 고른 줄)으로 나무 수를 고르고 → 학습 자료 전체로 다시 학습 → 시험 예측."""
    last = asof[train].max()
    fit = train & (asof <= last - timedelta(375))
    val = train & val_mask & (asof > last - timedelta(365))
    probe = GBDT(cat_cols=cat, n_rounds=2000, **params).fit(X[fit], y[fit], X[val], y[val])
    n = max(probe.best_iteration, 20)
    return GBDT(cat_cols=cat, n_rounds=n, **params).fit(X[train], y[train]).predict(Xt), n


def exp_seoul(series, names, params):
    asof, _, X, y = arrays(seoul_rows(series, names), PRICE_FEATS)
    print(f"\n[실험 1 · 서울 안에서] 자료 {asof.min()} ~ {asof.max()} · {len(y):,}줄 · 품목 {len(series)}개")
    out = {}
    for tname, start, end in TESTS:
        te = (asof >= start) & (asof < end)
        out[tname] = {"그대로": score(np.zeros(te.sum()), y[te])}
        for wname, yrs in WINDOWS:
            tr = (asof < start - GAP) & (asof >= start - timedelta(int(365.25 * yrs)))
            if wname != "전부" and asof.min() > start - timedelta(int(365.25 * yrs)):
                continue   # 자료가 그만큼 길지 않으면 '전부'와 같음
            p, n = fit_predict(X, y, asof, tr, np.ones(len(y), bool), X[te], params, [0])
            out[tname][wname] = {**score(p, y[te]), "train_from": str(asof[tr].min()), "train_rows": int(tr.sum()), "trees": n}
            r = out[tname][wname]
            print(f"  시험 {tname} · 학습 {wname:<3} ({r['train_from']}~, {r['train_rows']:,}줄, 나무 {n}) "
                  f"평균 오차 {r['mae_pp']:.2f}%p · 정반대 {r['opposite_pct']:.1f}%")
        print(f"  시험 {tname} · 그대로(변화 0) 평균 오차 {out[tname]['그대로']['mae_pp']:.2f}%p")
    return out


def exp_daegu(dseries, weather, seoul, cfg):
    names, drows = L.build_rows(dseries, weather, "야채")
    srows = seoul_rows(seoul, names)
    feats = cfg["features"]
    da, di, dX, dy = arrays(drows, feats)
    sa, si, sX, sy = arrays(srows, feats)
    last = da.max()
    te = da > last - timedelta(365)                 # learner.Data 와 같은 시험: 최근 1년
    start = da[te].min()
    print(f"\n[실험 2 · 대구 시험 {start} ~ {last}, {te.sum():,}건] 요인 {feats}")
    cat = [feats.index("item")]
    out = {"test_period": [str(start), str(last)], "features": feats}
    for label, s_from in (("대구만 (지금)", None), ("+ 서울 2016~", date(2016, 1, 1)), ("+ 서울 2021~ (같은 기간만)", date(2021, 1, 1))):
        dtr = da < start - GAP
        keep = np.zeros(len(sa), bool) if s_from is None else (sa >= s_from) & (sa < start - GAP)
        X, y, a = np.vstack([dX[dtr], sX[keep]]), np.concatenate([dy[dtr], sy[keep]]), np.concatenate([da[dtr], sa[keep]])
        is_daegu = np.r_[np.ones(dtr.sum(), bool), np.zeros(keep.sum(), bool)]   # 나무 수는 대구 줄로만 고름
        p, n = fit_predict(X, y, a, np.ones(len(y), bool), is_daegu, dX[te], cfg["params"], cat)
        per = {nm: score(p[di[te] == i], dy[te][di[te] == i]) for i, nm in enumerate(names) if (di[te] == i).sum() >= 20}
        out[label] = {**score(p, dy[te]), "train_rows": int(len(y)), "seoul_rows": int(keep.sum()), "trees": n, "items": per}
        r = out[label]
        print(f"  {label:<18} 학습 {r['train_rows']:,}줄 (서울 {r['seoul_rows']:,}) 나무 {n} → "
              f"평균 오차 {r['mae_pp']:.2f}%p · 정반대 {r['opposite_pct']:.1f}%")
    out["그대로"] = score(np.zeros(te.sum()), dy[te])
    out["fix"] = exp_fix(names, (da, di, dX, dy), (sa, si, sX, sy), start, last, cfg)
    out["years"] = exp_years(names, (da, di, dX, dy), (sa, si, sX, sy), cfg)
    return out


def run_daegu(D, S, cfg, t0, s_items, src):
    """t0 이전으로 학습 → 대구 [t0, t0 + 1년) 예측. s_items: 서울 줄을 쓸 품목 번호 (빈 set 이면 대구만) · src: 출처 요인(대구 0 · 서울 1)."""
    da, di, dX, dy = D
    sa, si, sX, sy = S
    with_src = lambda X, v: np.column_stack([X, np.full(len(X), v)])
    dtr = da < t0 - GAP
    keep = (sa < t0 - GAP) & np.isin(si, list(s_items))
    X = np.vstack([dX[dtr], sX[keep]])
    Xt = dX[(da >= t0) & (da < t0 + timedelta(365))]
    if src:
        X = np.vstack([with_src(dX[dtr], 0), with_src(sX[keep], 1)])
        Xt = with_src(Xt, 0)
    y, a = np.concatenate([dy[dtr], sy[keep]]), np.concatenate([da[dtr], sa[keep]])
    is_daegu = np.r_[np.ones(dtr.sum(), bool), np.zeros(keep.sum(), bool)]   # 나무 수는 대구 줄로만 고름
    return fit_predict(X, y, a, np.ones(len(y), bool), is_daegu, Xt, cfg["params"], [cfg["features"].index("item")])[0]


def exp_years(names, D, S, cfg):
    """실험 4: 시험 해를 바꿔 같은 비교 (2023-11 · 2024-11 · 2025-11 부터 1년). 대구 자료가 2021-01부터라 그 전 해는 못 봄."""
    da, di, dX, dy = D
    allx = set(range(len(names)))
    out = {}
    print("\n[실험 4 · 시험 해 바꾸기] 평균 오차 %p / 정반대 %  (오이 · 청양고추 정반대)")
    for t0 in (date(2023, 11, 1), date(2024, 11, 1), date(2025, 11, 1)):
        tm = (da >= t0) & (da < t0 + timedelta(365))
        p = {lb: run_daegu(D, S, cfg, t0, it, src) for lb, it, src in
             (("대구만", set(), False), ("+ 서울", allx, False), ("+ 서울 + 출처 요인", allx, True))}
        p["두 모델 평균"] = (p["대구만"] + p["+ 서울"]) / 2
        name = f"{t0:%Y-%m}~{t0 + timedelta(364):%Y-%m}"
        out[name] = {}
        for lb, pr in p.items():
            per = {nm: score(pr[di[tm] == i], dy[tm][di[tm] == i]) for i, nm in enumerate(names) if (di[tm] == i).sum() >= 20}
            out[name][lb] = {**score(pr, dy[tm]), "items": per}
            r = out[name][lb]
            print(f"  시험 {name} · {lb:<16} {r['mae_pp']:.2f} / {r['opposite_pct']:.1f}%   "
                  f"(오이 {per['오이']['opposite_pct']:.1f} · 청양고추 {per['청양고추']['opposite_pct']:.1f})")
    return out


def exp_fix(names, D, S, start, last, cfg):
    """실험 3: 서울을 섞어 나빠진 품목(오이 · 청양고추 등) 줄이기. 고르는 건 시험 전 1년(검증)으로만, 시험은 확인만."""
    da, di, dX, dy = D
    run = lambda t0, s_items, src: run_daegu(D, S, cfg, t0, s_items, src)
    allx = set(range(len(names)))
    v0 = start - timedelta(365)                    # 검증: 시험 바로 전 1년
    vm, tm = (da >= v0) & (da < v0 + timedelta(365)), (da >= start) & (da <= last)
    preds = {}
    for label, items, src in (("대구만", set(), False), ("+ 서울", allx, False), ("+ 서울 + 출처 요인", allx, True)):
        preds[label] = (run(v0, items, src), run(start, items, src))
    preds["두 모델 평균"] = tuple((preds["대구만"][k] + preds["+ 서울"][k]) / 2 for k in (0, 1))
    # 품목별 고르기: 검증 1년에서 서울을 섞어 정반대가 줄고 평균 오차가 늘지 않은 품목만 서울 줄을 씀
    picks = {}
    for base in ("+ 서울", "+ 서울 + 출처 요인"):
        good = set()
        for i in allx:
            k = di[vm] == i
            if k.sum() >= 20:
                a, b = score(preds["대구만"][0][k], dy[vm][k]), score(preds[base][0][k], dy[vm][k])
                if b["opposite_pct"] < a["opposite_pct"] and b["mae_pp"] <= a["mae_pp"]:
                    good.add(i)
        picks[base] = sorted(names[i] for i in good)
        preds[f"품목별 고르기 ({base})"] = (None, run(start, good, base.endswith("요인")))
    out = {"valid_period": [str(v0), str(start - timedelta(1))], "picked_items": picks, "results": {}}
    print(f"\n[실험 3 · 나빠진 품목 줄이기] 고르기 = 검증 {v0} ~ {start - timedelta(1)} · 확인 = 시험 {start} ~ {last}")
    for b, its in picks.items():
        print(f"  검증에서 서울이 도움 된 품목 ({b}): {' · '.join(its)}")
    for label, (_, p) in preds.items():
        per = {nm: score(p[di[tm] == i], dy[tm][di[tm] == i]) for i, nm in enumerate(names) if (di[tm] == i).sum() >= 20}
        out["results"][label] = {**score(p, dy[tm]), "items": per}
        r = out["results"][label]
        print(f"  {label:<26} 평균 오차 {r['mae_pp']:.2f}%p · 정반대 {r['opposite_pct']:.1f}%   "
              f"오이 {per['오이']['opposite_pct']:.1f}% · 청양고추 {per['청양고추']['opposite_pct']:.1f}%")
    return out


def main():
    t0 = time.time()
    seoul = load_seoul()
    dseries, weather = B.load_veg()
    cfg = L.DEFAULT_CONFIG   # 매일 학습의 기본 설정 (보관함의 오늘 챔피언은 안 읽음 — 파일만으로 다시 돌릴 수 있게)
    names = sorted(seoul)
    res = {"made": str(date.today()), "seoul_items": names, "seoul_range": [str(min(p[0] for s in seoul.values() for p in s)),
           str(max(p[0] for s in seoul.values() for p in s))],
           "seoul": exp_seoul(seoul, names, cfg["params"]), "daegu": exp_daegu(dseries, weather, seoul, cfg)}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {OUT} ({round(time.time() - t0)}초)")


if __name__ == "__main__":
    main()
