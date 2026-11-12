"""시세 예측 되돌려 채점 (백테스트): 과거 날짜마다 "그날 예측했다면?"을 다시 계산해 7일 뒤 실제 가격과 비교.

실행:  .venv\\Scripts\\python backtest.py          (저장소의 data/raw 자료를 씀, 2~5분)

- 계산 조각은 analysis.py 의 것을 그대로 가져옴 (reversion_factor · volume_factor · weather_effect · 계수)
  → 공식을 고치면 이 파일을 다시 돌려 점수가 나아졌는지 확인
- 자료
  농산물: data/raw/1109_5y (북부도매시장 경락가 · 반입량 2021-01~2026-11, 대구 날씨)
  수산물 · 육류: data/raw/1112_2020-2025_농수축산물_일자별_도소매가격.csv.xz (KAMIS 대구, 육류는 2022-04까지만 있음)
- 공휴일 · 대구 행사 · 협신식품 경락가는 과거 자료가 없어 채점에서 뺌 (모든 공식에 똑같이 빠짐)
- 채점표 (plan/forecast/1112_forecast_validation_agent.md 2절)
  방향 적중: 오를(+2% 이상) · 비슷 · 내릴(−2% 이하) 이 실제와 같은 비율
  정반대: 오른다고 했는데 내렸거나 그 반대 (사장님께 가장 손해)
  평균 오차: |예측 변화율 − 실제 변화율| 평균 (%p). "그대로"(변화 0%)라고 했을 때보다 작아야 의미 있음
"""
import csv
import glob
import lzma
import statistics
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from analysis import (EXTRA_REVERSION, FRUIT_REVERSION, FRUIT_VOLUME, VEG_VOLUME, VEG_REVERSION, _clip, reversion_factor, volume_factor, weather_effect)
from data_sources import ITEMS, kind_of

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
SPLIT = date(2025, 1, 1)   # 이 날 전 = 계수를 고른 기간, 이후 = 고를 때 안 쓴 기간 (농산물)

# 수산물 · 육류: 우리 품목 → 합본 파일의 (품목코드, 품종코드, 조사구분, 등급코드). 육류 코드는 perDay 와 다름
EXTRA_MAP = {
    "한우 등심": ("512", "12", "소매", "1"), "한우 양지": ("512", "14", "소매", "1"), "수입 소고기 갈비살": ("512", "22", "소매", None),
    "돼지고기 앞다리": ("514", "4", "소매", None), "돼지고기 삼겹살": ("514", "0", "소매", None),
    "닭고기": ("515", "2", "소매", None), "계란": ("516", "0", "소매", None),
    "고등어": ("611", "2", "도매", None), "새우젓": ("650", "0", "소매", None),
    "갈치": ("613", "2", "도매", "21"), "명태": ("615", "2", "도매", "21"), "굴": ("644", "0", "도매", None),
    "홍합": ("658", "2", "도매", None), "새우": ("654", "1", "도매", None),
    "멸치액젓": ("651", "0", "소매", None),
}


def old_trend(points, asof, cap):
    """예전 공식의 '최근 2주 흐름' (비교용으로만 남김): 2주 기울기 × 7일 ÷ 평균 × 0.5."""
    rec = [p for p in points if p[0] > asof - timedelta(15)]
    if len(rec) < 4:
        return 0.0
    xs = [(p[0] - asof).days for p in rec]
    ys = [p[1] for p in rec]
    if len(set(xs)) < 2:
        return 0.0
    return _clip(statistics.linear_regression(xs, ys).slope * 7 / statistics.mean(ys) * 100 * 0.5, -cap, cap)


def load_veg():
    agg = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    with open(RAW / "1109_5y" / "1109_wholesale_qty_daily.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            for name, cfg in ITEMS.items():
                if r["mclsf"] == cfg["sale_name"] and (not cfg["sale_sub"] or cfg["sale_sub"] in r["sclsf"]):
                    a = agg[name][r["date"]]
                    a[0] += float(r["qty_kg"] or 0)
                    a[1] += float(r["totprc"] or 0)
    series = {n: sorted((date.fromisoformat(d), v[1] / v[0], v[0]) for d, v in m.items() if v[0] > 0 and v[1] > 0)
              for n, m in agg.items()}
    weather = {}
    with open(RAW / "1109_5y" / "1109_weather_daegu_daily.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            num = lambda k: float(r[k]) if r[k] else None
            weather[date.fromisoformat(r["tm"])] = (num("sumRn") or 0.0, num("minTa"), num("maxTa"))
    return series, weather


def load_extra():
    key = {(c, v, s): n for n, (c, v, s, g) in EXTRA_MAP.items()}
    by = defaultdict(lambda: defaultdict(list))
    path = glob.glob(str(RAW / "1112_*.csv.xz"))[0]
    with lzma.open(path, "rt", encoding="cp949", errors="replace") as fh:
        rows = csv.reader(fh)
        next(rows)
        for row in rows:
            if row[5] != "대구":
                continue
            name = key.get((row[8], row[10].lstrip("0") or "0", row[13]))
            if not name or (EXTRA_MAP[name][3] and row[14] != EXTRA_MAP[name][3]):
                continue
            try:
                price = float(row[16]) / (float(row[21] or row[19] or 1) or 1)
            except ValueError:
                continue
            if price > 0:
                by[name][row[0]].append(price)
    return {n: sorted((date(int(d[:4]), int(d[4:6]), int(d[6:])), statistics.mean(v)) for d, v in m.items())
            for n, m in by.items()}


def score(cases):
    """cases: [(예측 %, 실제 %)]"""
    cls = lambda x: 1 if x >= 2 else -1 if x <= -2 else 0
    n = len(cases) or 1
    hit = sum(cls(p) == cls(a) for p, a in cases)
    opp = sum(cls(p) * cls(a) == -1 for p, a in cases)
    return (f"{len(cases):>6}건 · 방향 적중 {hit / n * 100:5.1f}% · 정반대 {opp / n * 100:5.1f}% · "
            f"평균 오차 {statistics.mean(abs(p - a) for p, a in cases):5.2f}%p "
            f"(그대로라 했을 때 {statistics.mean(abs(a) for _, a in cases):5.2f}%p)")


def veg_cases(series, weather):
    """(기간, 예전 공식, 지금 공식, 실제)"""
    out = []
    for name, s in series.items():
        days = [p[0] for p in s]
        for i in range(30, len(s) - 1, 2):   # 이틀마다
            asof = s[i][0]
            j = bisect_right(days, asof + timedelta(6))   # 7일 뒤 (그 뒤 첫 거래일, 10일 안)
            if asof < date(2021, 3, 1) or j >= len(s) or s[j][0] > asof + timedelta(10):
                continue
            win = [p for p in s[: i + 1] if p[0] > asof - timedelta(28)]   # 실제 예측처럼 28일치만
            fruit = kind_of(name) == "과일"   # analysis.forecast_item 과 같은 갈림
            vol = volume_factor([p[2] for p in win], *(FRUIT_VOLUME if fruit else VEG_VOLUME))
            w = [weather[d] for d in (asof - timedelta(k) for k in range(7)) if d in weather]
            wx = weather_effect(name, sum(x[0] for x in w), sum(1 for x in w if (x[1] or 0) <= -3),
                                sum(1 for x in w if (x[2] or 0) >= 33))[0] if w else 0.0
            rev = reversion_factor([p[1] for p in win], *(FRUIT_REVERSION if fruit else VEG_REVERSION))
            new = (rev["effect_pct"] if rev else 0) + (vol["effect_pct"] if vol else 0) + (0 if fruit else wx)
            old_vol = volume_factor([p[2] for p in win], k=-0.25)
            old = old_trend(win, asof, 10) + (old_vol["effect_pct"] if old_vol else 0) + wx
            out.append(("이전" if asof < SPLIT else "이후", old, new, (s[j][1] / s[i][1] - 1) * 100, kind_of(name)))
    return out


def extra_cases(series):
    out = []
    for name, s in series.items():
        group = "육류" if EXTRA_MAP[name][0].startswith("5") else "수산물"
        days = [p[0] for p in s]
        for i in range(10, len(s) - 1, 2):
            asof = s[i][0]
            j = bisect_right(days, asof + timedelta(6))
            if j >= len(s) or s[j][0] > asof + timedelta(10):
                continue
            win = [p for p in s[: i + 1] if p[0] > asof - timedelta(35)]
            if len(win) < 5:
                continue
            prices = [p[1] for p in win]
            rev = reversion_factor(prices, *EXTRA_REVERSION)
            new = rev["effect_pct"] if rev else 0
            old_rev = reversion_factor(prices, 0.3, 4)
            kimjang = 2 if name in ("새우젓", "멸치액젓", "굴") and asof.month in (11, 12) else 0
            old = old_trend(win, asof, 8) + (old_rev["effect_pct"] if old_rev else 0) + kimjang
            out.append((group, old, new, (s[j][1] / s[i][1] - 1) * 100))
    return out


def meat_auction_cases(gap_k=0.3, vol_k=-0.1):
    """한우 · 돼지 경락가 이유 채점 (주 단위) — 결과: 어떤 계수로도 더 나빠져 예측에서 뺌 (2026-11-12): data/raw/1112_meat_weekly (fetch_meat_weekly.py 로 받음).
    실제 예측은 날마다 계산하지만 과거 경락가는 주 평균으로만 받아서, 같은 생각을 주 단위로 재현:
      도매 경락가 흐름 = gap_k × (이번 주 경락가 변화 − 이번 주 소매 변화), 최대 ±4%
      경매 물량 = vol_k × (이번 주 물량 ÷ 앞 3주 평균 − 1), 최대 ±3%
    실제 = 다음 주 소매 평균 ÷ 이번 주 소매 평균 − 1. 결과: (기간, 평균 차이만, +경락가 흐름, +경매 물량, +둘 다, 실제)"""
    path = RAW / "1112_meat_weekly" / "1112_meat_weekly_2021-2026.csv"
    if not path.exists():
        return []
    by = defaultdict(list)
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            num = lambda k: float(r[k]) if r[k] else None
            by[r["item"]].append((date.fromisoformat(r["week"]), num("auction_price"), num("auction_count"), num("retail_price")))
    out = []
    for rows in by.values():
        rows.sort()
        for i in range(4, len(rows) - 1):
            ret = [x[3] for x in rows[i - 4: i + 2]]
            if None in ret:
                continue
            actual = (ret[-1] / ret[-2] - 1) * 100
            rev = reversion_factor(ret[:-1], *EXTRA_REVERSION)
            base = rev["effect_pct"] if rev else 0
            a, a0 = rows[i][1], rows[i - 1][1]
            gap = _clip(gap_k * ((a / a0 - 1) * 100 - (ret[-2] / ret[-3] - 1) * 100), -4, 4) if a and a0 else 0
            cnt = [x[2] for x in rows[i - 3: i]]
            vol = (_clip(vol_k * (rows[i][2] / statistics.mean(cnt) - 1) * 100, -3, 3)
                   if rows[i][2] and all(cnt) else 0)
            period = "이전" if rows[i][0] < SPLIT else "이후"
            out.append((period, base, base + gap, base + vol, base + gap + vol, actual))
    return out


if __name__ == "__main__":
    mc = meat_auction_cases()
    if mc:
        print("한우 · 돼지 경락가 이유 (주 단위, 협신식품 2021-01 ~ 2026-11)")
        for period, label in (("이전", "2021~2024"), ("이후", "2025~2026")):
            part = [c for c in mc if c[0] == period]
            print(f"  {label}")
            for col, name in ((1, "평균과의 차이만          "), (2, "+ 도매 경락가 흐름       "),
                              (3, "+ 경매 물량              "), (4, "+ 둘 다 (예전 화면)      ")):
                print(f"    {name}", score([(c[col], c[5]) for c in part]))
    vc = veg_cases(*load_veg())
    for kind in ("야채", "과일"):
        print(f"농산물 · {kind} (북부도매시장 경락가, 2021-03 ~ 2026-11)")
        for period, label in (("이전", "2021~2024 (계수 고른 기간)"), ("이후", "2025~2026 (고를 때 안 쓴 기간)")):
            part = [c for c in vc if c[0] == period and c[4] == kind]
            print(f"  {label}")
            print("    예전 공식 (최근 2주 흐름 · 반입량 −0.25)  ", score([(c[1], c[3]) for c in part]))
            print("    지금 공식 (4주 평균과의 차이 · 반입량, 과일은 따로 정한 계수)", score([(c[2], c[3]) for c in part]))
    print("수산물 · 육류 (KAMIS 대구, 2020-01 ~ 2025-08 · 육류는 2022-04까지)")
    ec = extra_cases(load_extra())
    for group in ("수산물", "육류"):
        part = [c for c in ec if c[0] == group]
        print(f"  {group}")
        print("    예전 공식 (최근 2주 흐름 · 평균 차이 0.3 · 김장철)", score([(c[1], c[3]) for c in part]))
        print("    지금 공식 (한 달 평균과의 차이 0.2)          ", score([(c[2], c[3]) for c in part]))
