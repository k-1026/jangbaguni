"""야채 7일 시세 예측: 지금 공식 vs 절대오차 회귀 vs 부스팅 비교 실험 (부스팅은 gbdt.py, numpy만 씀).

실행:  python boost_compare.py          (data/raw 자료만 씀, API 호출 없음, 몇 분)

- 자료 · 채점은 backtest.py 와 같음 (북부도매 야채 경락가 · 반입량 · 대구 날씨, 이틀마다 기준일, 7일 뒤 첫 거래일)
- 기간: 2021~2024 = 학습 (2024는 부스팅 반복 횟수 고르는 데만 씀) / 2025~2026 = 시험 (어떤 방법도 안 봄)
- 채점: 방향 맞음 · 정반대 · 평균 오차(%p) · "그대로" 오차 — 채택 기준은 시험 기간의 정반대와 평균 오차가 둘 다 낮은 것
- 새 요인
  계절: 지난 해들 같은 날짜의 7일 변화 평균 (기준일보다 앞선 해만 써서 미래를 보지 않음)
  명절: 다음 설 · 추석까지 남은 날 (날짜 표는 아래 MAJOR_HOLIDAYS)
  서울 도매가: KAMIS 합본(data/raw/1112_...csv.xz)의 서울 도매 조사가 — 2025-08까지만 있어 시험은 두 갈래로 봄
"""
import csv
import lzma
import glob
import math
import statistics
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

import backtest as B
from analysis import VEG_REVERSION, VEG_VOLUME, reversion_factor, volume_factor, weather_effect
from data_sources import kind_of
from gbdt import GBDT

MAJOR_HOLIDAYS = [date(2021, 2, 12), date(2021, 9, 21), date(2022, 2, 1), date(2022, 9, 10), date(2023, 1, 22), date(2023, 9, 29),
                  date(2024, 2, 10), date(2024, 9, 17), date(2025, 1, 29), date(2025, 10, 6), date(2026, 2, 17), date(2026, 9, 25)]
# 우리 품목 → KAMIS 합본의 품목명 (대파 · 애호박 · 가지는 서울 도매 조사가가 없음)
SEOUL_NAME = {"양파": "양파", "배추": "배추", "무": "무", "양배추": "양배추", "감자": "감자", "당근": "당근", "오이": "오이",
              "청양고추": "풋고추", "깻잎": "깻잎", "상추": "상추", "시금치": "시금치", "토마토": "토마토"}
SEOUL_END = date(2025, 8, 31)


def load_seoul():
    """서울 도매 · 상품 등급 · 품목마다 가장 많은 품종 하나 → {품목: [(날짜, kg당 가격)]}"""
    raw = defaultdict(lambda: defaultdict(list))
    path = glob.glob(str(B.RAW / "1112_*.csv.xz"))[0]
    with lzma.open(path, "rt", encoding="cp949", errors="replace") as fh:
        rows = csv.reader(fh)
        next(rows)
        for r in rows:
            if r[5] != "서울" or r[13] != "도매" or r[15] != "상품" or r[9] not in SEOUL_NAME.values():
                continue
            try:
                price = float(r[16]) / (float(r[19]) if r[19] else 1.0)
            except ValueError:
                continue
            if price > 0:
                raw[r[9]][r[10]].append((date(int(r[0][:4]), int(r[0][4:6]), int(r[0][6:])), price))
    out = {}
    for ours, kname in SEOUL_NAME.items():
        if kname not in raw:
            continue
        variety = max(raw[kname], key=lambda v: len(raw[kname][v]))
        by = defaultdict(list)
        for d, p in raw[kname][variety]:
            by[d].append(p)
        out[ours] = sorted((d, statistics.mean(v)) for d, v in by.items())
    return out


def value_on_or_before(series, days, d):
    i = bisect_right(days, d) - 1
    return series[i] if i >= 0 else None


def build_rows():
    series, weather = B.load_veg()
    seoul = load_seoul()
    seoul_days = {k: [p[0] for p in v] for k, v in seoul.items()}
    names = [n for n in series if kind_of(n) == "야채"]
    rows = []
    for idx, name in enumerate(names):
        s = series[name]
        days = [p[0] for p in s]
        for i in range(30, len(s) - 1, 2):
            asof = s[i][0]
            j = bisect_right(days, asof + timedelta(6))
            if asof < date(2021, 3, 1) or j >= len(s) or s[j][0] > asof + timedelta(10):
                continue
            win = [p for p in s[: i + 1] if p[0] > asof - timedelta(28)]
            pr = [p[1] for p in win]
            w = [weather[d] for d in (asof - timedelta(k) for k in range(7)) if d in weather]
            rain = sum(x[0] for x in w)
            cold = sum(1 for x in w if (x[1] or 0) <= -3)
            hot = sum(1 for x in w if (x[2] or 0) >= 33)
            wx = weather_effect(name, rain, cold, hot)[0] if w else 0.0
            rev = reversion_factor(pr, *VEG_REVERSION)
            vol = volume_factor([p[2] for p in win], *VEG_VOLUME)
            current = (rev["effect_pct"] if rev else 0) + (vol["effect_pct"] if vol else 0) + wx
            # --- 요인 ---
            dev = (pr[-1] / statistics.mean(pr) - 1) * 100
            trend = B.old_trend(win, asof, 1e9) / 0.5
            vf = volume_factor([p[2] for p in win], k=-1, cap=1e9)
            vchg = -vf["effect_pct"] if vf else math.nan
            rets = [math.log(b / a) for a, b in zip(pr, pr[1:])]
            volat = statistics.pstdev(rets) * 100 if len(rets) > 2 else math.nan
            chg3 = (pr[-1] / pr[-4] - 1) * 100 if len(pr) >= 4 else math.nan
            # 계절: 앞선 해들의 같은 날 → 7일 뒤 변화
            seas = []
            for back in range(1, 6):
                d0 = asof - timedelta(365 * back)
                if d0 < days[0]:
                    break
                a = bisect_left(days, d0)
                b = bisect_right(days, d0 + timedelta(6))
                if a < len(s) and b < len(s) and abs((s[a][0] - d0).days) <= 3 and s[b][0] <= d0 + timedelta(10):
                    seas.append((s[b][1] / s[a][1] - 1) * 100)
            season = statistics.mean(seas) if seas else math.nan
            to_major = min([(h - asof).days for h in MAJOR_HOLIDAYS if (h - asof).days >= 0] or [99])
            # 서울 도매가
            s_chg7 = s_dev = gap = math.nan
            if name in seoul and asof <= SEOUL_END:
                sd, sv = seoul_days[name], seoul[name]
                cur = value_on_or_before(sv, sd, asof)
                prev = value_on_or_before(sv, sd, asof - timedelta(7))
                lo = bisect_right(sd, asof - timedelta(28))
                hi = bisect_right(sd, asof)
                if cur and prev and (asof - cur[0]).days <= 4 and hi - lo >= 5:
                    s_chg7 = (cur[1] / prev[1] - 1) * 100
                    s_dev = (cur[1] / statistics.mean(p[1] for p in sv[lo:hi]) - 1) * 100
                    gap = math.log(pr[-1] / cur[1])
            actual = (s[j][1] / s[i][1] - 1) * 100
            rows.append(dict(asof=asof, item=idx, current=current, dev=dev, trend=trend, vchg=vchg, wx=wx, rain=rain, cold=cold, hot=hot,
                             volat=volat, chg3=chg3, season=season, to_major=to_major, month=asof.month,
                             s_chg7=s_chg7, s_dev=s_dev, gap=gap, actual=actual))
    return rows, names


def metrics(pred, act):
    cls = lambda x: np.where(x >= 2, 1, np.where(x <= -2, -1, 0))
    p, a = cls(pred), cls(act)
    return dict(n=len(act), hit=(p == a).mean() * 100, opp=((p * a) == -1).mean() * 100,
                mae=np.abs(pred - act).mean(), flat=np.abs(act).mean())


def lad(X, y, iters=60):
    """절대오차 회귀 (반복 가중 최소제곱)."""
    Z = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(Z, y, rcond=None)
    for _ in range(iters):
        w = 1 / np.maximum(np.abs(y - Z @ b), 1e-3)
        Wz = Z * w[:, None]
        b = np.linalg.solve(Z.T @ Wz + 1e-6 * np.eye(Z.shape[1]), Wz.T @ y)
    return b


def main():
    rows, names = build_rows()
    col = lambda k: np.array([r[k] for r in rows], dtype=float)
    asof = np.array([r["asof"] for r in rows])
    y = col("actual")
    cur = col("current")
    base_feats = ["dev", "vchg", "wx"]
    all_feats = ["item", "dev", "trend", "vchg", "wx", "rain", "cold", "hot", "volat", "chg3", "season", "to_major", "month"]
    seoul_feats = ["s_chg7", "s_dev", "gap"]
    train = asof < date(2025, 1, 1)
    fit_part = asof < date(2024, 1, 1)     # 부스팅 반복 횟수 고르기: 2021~23 학습, 2024 확인
    val_part = train & ~fit_part
    test = ~train
    test_seoul = test & (asof <= SEOUL_END)

    preds = {"지금 공식": cur}

    # 절대오차 회귀 (지금과 같은 요인 3개)
    Xb = np.nan_to_num(np.column_stack([col(f) for f in base_feats]))
    lo, hi = np.percentile(Xb[train], 1, axis=0), np.percentile(Xb[train], 99, axis=0)
    Xb = np.clip(Xb, lo, hi)
    b = lad(Xb[train], y[train])
    preds["절대오차 회귀 (요인 3개)"] = np.column_stack([np.ones(len(Xb)), Xb]) @ b
    coef_lad = b

    def boost(feats, objective, label):
        X = np.column_stack([col(f) for f in feats])
        cat = [feats.index("item")] if "item" in feats else []
        probe = GBDT(objective=objective, cat_cols=cat).fit(X[fit_part], y[fit_part], X[val_part], y[val_part])
        m = GBDT(objective=objective, cat_cols=cat, n_rounds=max(probe.best_iteration, 20)).fit(X[train], y[train])
        preds[label] = m.predict(X)
        return m, m.best_iteration

    boost(["item"] + base_feats, "l1", "부스팅 · 요인 3개 (절대오차)")
    m_all, best_all = boost(all_feats, "l1", "부스팅 · 새 요인 포함 (절대오차)")
    boost(all_feats, "l2", "부스팅 · 새 요인 포함 (제곱오차)")
    m_seoul, _ = boost(all_feats + seoul_feats, "l1", "부스팅 · + 서울 도매가 (절대오차)")

    print(f"야채 {len(names)}개 · 기준일 {len(y)}건 (학습 {train.sum()} / 시험 {test.sum()}, 그중 서울 자료 있는 기간 {test_seoul.sum()})")
    print(f"부스팅 나무 수: 새 요인 모델 {best_all}개")
    print(f"절대오차 회귀 계수 [절편, 평균차이, 반입량, 날씨] = {np.round(coef_lad, 3).tolist()}")
    for label, mask in (("시험 2025-01 ~ 2026-11", test), ("시험 2025-01 ~ 2025-08 (서울 자료 있는 기간)", test_seoul)):
        print(f"\n[{label}]")
        print(f"  {'방법':<34}{'방향 맞음':>8}{'정반대':>8}{'평균 오차':>10}{'그대로 오차':>11}")
        for k, p in preds.items():
            r = metrics(p[mask], y[mask])
            print(f"  {k:<34}{r['hit']:>7.1f}%{r['opp']:>7.1f}%{r['mae']:>9.2f}p{r['flat']:>10.2f}p")

    # 해마다 굴려 검증: Y년 전까지로 학습 → Y년 시험 (지금 공식 vs 부스팅 새 요인)
    print("\n[해마다 굴려 검증 · 지금 공식 vs 부스팅(새 요인, 절대오차)]")
    X = np.column_stack([col(f) for f in all_feats])
    years = np.array([d.year for d in asof])
    for Y in (2023, 2024, 2025):
        tr = years < Y
        te = (years == Y) if Y < 2025 else (years >= 2025)
        m = GBDT(objective="l1", cat_cols=[0], n_rounds=best_all).fit(X[tr], y[tr])
        a, c = metrics(cur[te], y[te]), metrics(m.predict(X[te]), y[te])
        print(f"  {Y}{'~26' if Y == 2025 else '   '}  공식 정반대 {a['opp']:5.1f}% 오차 {a['mae']:5.2f}p  |  부스팅 정반대 {c['opp']:5.1f}% 오차 {c['mae']:5.2f}p  방향 {a['hit']:4.1f}→{c['hit']:4.1f}%")

    imp = sorted(zip(all_feats + seoul_feats, m_seoul.importance(len(all_feats + seoul_feats))), key=lambda t: -t[1])
    tot = sum(v for _, v in imp) or 1
    print("\n[부스팅이 많이 쓴 요인 (서울 포함 모델, 나누는 데 쓴 비율)]")
    print("  " + " · ".join(f"{k} {v / tot * 100:.0f}%" for k, v in imp[:10]))


if __name__ == "__main__":
    main()
