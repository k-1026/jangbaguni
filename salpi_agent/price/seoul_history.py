"""서울 가락 도매 10년 치(2016-02 ~ 2025-08) — 야채 매일 학습에 더하는 학습 자료.

왜: 대구 경락가가 2021-01부터라 학습 기간이 최대 약 4년. 서울 10년을 학습에만 섞으니 시험 세 해(2023-11 · 2024-11 · 2025-11)
    모두 정반대 · 평균 오차가 줄었음 (plan/forecast/1125_train_length_10y.md)
자료: 서울 가락 중도매 '상품' 조사가 (aT 일별 도·소매 = KAMIS)
      2016 ~ 2019 = data/raw/1124_veg_past_seoul_daegu/seoul_1101 · 2020 ~ 2025-08 = data/raw/1112_*.csv.xz (서울 · 도매)
쓰는 법: rows(names) → learner.build_rows 와 같은 모양의 줄. 반입량 · 대구 날씨는 빈 값, 출처 요인 src = 1
"""
import csv
import glob
import lzma
import math
import statistics
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta

from price import backtest as B
from price import forecast_model as FM

OLD_DIR = B.RAW / "1124_veg_past_seoul_daegu" / "seoul_1101"
# 우리 품목 → (KAMIS 품목명, 쓸 품종 코드 · None 이면 그날 모든 품종 평균). 가지는 서울 조사가가 없음
SEOUL = {"양파": ("양파", {0}), "배추": ("배추", None), "무": ("무", None), "양배추": ("양배추", {0}), "감자": ("감자", {1}),
         "당근": ("당근", {1}), "오이": ("오이", {2}), "청양고추": ("풋고추", {3}), "깻잎": ("깻잎", {0}), "상추": ("상추", {1, 2}),
         "시금치": ("시금치", {0}), "토마토": ("토마토", {0}), "대파": ("파", {0}), "애호박": ("호박", {1})}


def load():
    """{우리 품목: [(날짜, kg당 가격, 반입량 없음)]} — 품종별 단위 크기로 나눈 값을 그날 평균."""
    want = {k: (ours, v) for ours, (k, v) in SEOUL.items()}
    by = defaultdict(lambda: defaultdict(list))

    def add(kname, vcode, ymd, price, size):
        if kname not in want:
            return
        ours, codes = want[kname]
        try:
            p = float(price) / (float(size or 1) or 1)
        except ValueError:
            return
        if p > 0 and (codes is None or int(vcode) in codes):
            by[ours][date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))].append(p)

    for f in sorted(glob.glob(str(OLD_DIR / "*.csv"))):
        with open(f, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if r["se_nm"] == "중도매" and r["grd_nm"] == "상품":
                    add(r["item_nm"], r["vrty_cd"], r["exmn_ymd"], r["exmn_dd_prc"], r["unit_sz"])
    with lzma.open(glob.glob(str(B.RAW / "1112_*.csv.xz"))[0], "rt", encoding="cp949", errors="replace") as fh:
        rows = csv.reader(fh)
        next(rows)
        for r in rows:
            if r[5] == "서울" and r[13] == "도매" and r[15] == "상품" and r[0] >= "20200101":
                add(r[9], r[10], r[0], r[16], r[19])
    return {n: [(d, statistics.mean(v), math.nan) for d, v in sorted(m.items())] for n, m in by.items()}


def rows(names, series=None):
    """learner.build_rows 와 같은 모양 (기준일, 품목 번호, 요인, 공식 자리 0, 7일 뒤 변화). names 에 있는 품목만."""
    series = series if series is not None else load()
    out = []
    for name, s in series.items():
        if name not in names:
            continue
        idx = names.index(name)
        days, prices = [p[0] for p in s], [p[1] for p in s]
        for i in range(30, len(s)):
            asof = days[i]
            j = bisect_right(days, asof + timedelta(6))
            if j >= len(s) or days[j] > asof + timedelta(10):
                continue
            f = FM.make_features(name, idx, s[max(0, i - 40): i + 1], {}, asof, FM.season_value(days, prices, asof))
            f["wx"] = math.nan   # 대구 날씨 점수가 없음 (0 이 아니라 빈 값)
            f["src"] = 1.0
            out.append((asof, idx, f, 0.0, (prices[j] / prices[i] - 1) * 100))
    return out
