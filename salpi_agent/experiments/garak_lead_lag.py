"""가락시장이 대구보다 먼저 움직이나 — 품목별 시차 · 선행 적중률 표 (야채).

실행 (저장소 루트에서): python salpi_agent/experiments/garak_lead_lag.py   (numpy 없이 돌아감)

자료 (둘 다 aT perDay = KAMIS 조사 중도매 "상품" 값, 같은 출처)
  - 대구 북부도매: data/raw/1109_5y/1109_price_daily_*.csv
  - 가락도매:      data/raw/1112_2020-2025_농수축산물_일자별_도소매가격.csv.xz (~2025-08-29)
                   + data/raw/1124_garak_veg_recent/garak_perday_20250830_recent.csv (2025-08-30 ~)

방법
  1. 품목마다 (품종 · 단위)별 값을 따로 두고, 이웃한 거래일의 변화율(로그)을 평균해 "값 지수"를 만듦
     → 계절에 따라 품종이 바뀌어도 이어짐. 가락 · 대구 둘 다 값이 있는 날만 씀
  2. 가락 신호 = 가락 3거래일 변화. 3% 이상 오름 / 3% 이하 내림일 때
  3. k거래일 뒤(1~7) 대구가 같은 방향(±2% 넘게)으로 움직였나 = 선행 적중률. "아무 날이나" 기준(기준률)과 비교한 차이가 lift
  4. 시차는 앞 기간(~2025-10-31)으로 고르고, 마지막 1년(2025-11-01~)으로 확인 — 고를 때 안 본 자료
  5. 대구 자기 3거래일 변화로 설명되는 부분을 빼고도 가락이 더하는 설명력(ΔR²)도 같이 봄
"""
import csv
import io
import json
import lzma
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = Path(__file__).resolve().parent / "results" / "garak_lead_lag.json"
SEOUL_XZ = RAW / "1112_2020-2025_농수축산물_일자별_도소매가격.csv.xz"
SEOUL_RECENT = RAW / "1124_garak_veg_recent" / "garak_perday_20250830_recent.csv"

# 대구 파일 이름 → (품목 한글, 가락 품목 이름). 가지는 가락 자료 없음, 청양고추는 가락 풋고추와 품종이 달라 참고용
ITEMS = {"onion": ("양파", "양파"), "green_onion": ("대파", "파"), "napa_cabbage": ("배추", "배추"), "radish": ("무", "무"),
         "cabbage": ("양배추", "양배추"), "potato": ("감자", "감자"), "carrot": ("당근", "당근"), "zucchini": ("애호박", "호박"),
         "cucumber": ("오이", "오이"), "perilla_leaf": ("깻잎", "깻잎"), "lettuce": ("상추", "상추"), "spinach": ("시금치", "시금치"),
         "tomato": ("토마토", "토마토"), "cheongyang_pepper": ("청양고추(참고)", "풋고추")}
SIGNAL = 0.03      # 가락 3거래일 변화 ±3%
MOVE = 0.02        # 대구가 이 이상 움직여야 "움직였다" (±2%, 화면 정반대 기준과 같음)
LAGS = range(1, 8)
SPLIT = "20251101"
MIN_EVENTS = 15


def load_daegu(fname):
    ser = defaultdict(dict)  # (품종, 단위) → {날짜: 값}
    with open(RAW / "1109_5y" / f"1109_price_daily_{fname}.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["se_nm"] == "중도매" and r["mrkt_nm"] == "북부도매" and r["grd_nm"] == "상품":
                ser[(r["vrty_nm"], r["unit"], r["unit_sz"])][r["exmn_ymd"]] = float(r["exmn_dd_prc"])
    return ser


def load_garak(names):
    ser = defaultdict(lambda: defaultdict(dict))  # 품목 → (품종, 단위) → {날짜: 값}
    # 서울 합본 (cp949) : 가락도매 중도매 상품만
    with lzma.open(SEOUL_XZ, "rt", encoding="cp949", newline="") as f:
        head = next(csv.reader([f.readline()]))
        ix = {h: i for i, h in enumerate(head)}
        for line in f:
            if "가락도매" not in line:
                continue
            r = next(csv.reader([line]))
            if r[ix["시장명"]] == "가락도매" and r[ix["조사구분명"]] == "도매" and r[ix["산물등급명"]] == "상품" and r[ix["품목명"]] in names:
                ser[r[ix["품목명"]]][(r[ix["품종명"]], r[ix["도매출하단위명"]], r[ix["도매출하단위크기"]])][r[ix["가격등록일자"]]] = float(r[ix["품목가격"]])
    with open(SEOUL_RECENT, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["mrkt_nm"] == "가락도매" and r["se_nm"] == "중도매" and r["grd_nm"] == "상품" and r["item_nm"] in names:
                ser[r["item_nm"]][(r["vrty_nm"], r["unit"], r["unit_sz"])][r["exmn_ymd"]] = float(r["exmn_dd_prc"])
    return ser


def index_of(series, dates):
    """이웃한 거래일의 로그 변화를 (품종 · 단위)별로 평균해 이은 지수."""
    idx = [0.0]
    for i in range(1, len(dates)):
        a, b = dates[i - 1], dates[i]
        rets = [math.log(p[b] / p[a]) for p in series.values() if a in p and b in p and p[a] > 0 and p[b] > 0]
        idx.append(idx[-1] + (sum(rets) / len(rets) if rets else 0.0))
    return idx


def corr(x, y):
    n = len(x)
    if n < 10:
        return float("nan")
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sxx * syy) if sxx and syy else float("nan")


def r2_gain(y, own, g):
    """y ~ own 만 / y ~ own + g 의 R² 차이."""
    n = len(y)
    if n < 30:
        return float("nan")
    def r2(cols):
        ym = sum(y) / n
        ms = [sum(c) / n for c in cols]
        cc = [[v - m for v in c] for c, m in zip(cols, ms)]
        yc = [v - ym for v in y]
        k = len(cols)
        A = [[sum(a * b for a, b in zip(cc[i], cc[j])) for j in range(k)] for i in range(k)]
        bv = [sum(a * b for a, b in zip(cc[i], yc)) for i in range(k)]
        if k == 1:
            beta = [bv[0] / A[0][0]] if A[0][0] else [0]
        else:
            det = A[0][0] * A[1][1] - A[0][1] * A[1][0]
            if not det:
                return 0.0
            beta = [(bv[0] * A[1][1] - bv[1] * A[0][1]) / det, (A[0][0] * bv[1] - A[1][0] * bv[0]) / det]
        res = sum((yc[t] - sum(beta[j] * cc[j][t] for j in range(k))) ** 2 for t in range(n))
        tot = sum(v * v for v in yc)
        return 1 - res / tot if tot else 0.0
    return r2([own, g]) - r2([own])


def evaluate(g_idx, d_idx, dates, lo, hi, k):
    """기준일 i (lo ≤ 날짜 < hi) 별 신호와 k거래일 뒤 대구 변화."""
    rows = []
    for i in range(3, len(dates) - k):
        if not (lo <= dates[i] < hi):
            continue
        rows.append((g_idx[i] - g_idx[i - 3], d_idx[i - 3 + 3] - d_idx[i - 3], d_idx[i + k] - d_idx[i]))
    return rows  # (가락 3일 변화, 대구 자기 3일 변화, 대구 k일 뒤 변화)


def lift(rows):
    up = [r for r in rows if r[0] >= SIGNAL]
    dn = [r for r in rows if r[0] <= -SIGNAL]
    base_up = sum(1 for r in rows if r[2] >= MOVE) / len(rows) if rows else float("nan")
    base_dn = sum(1 for r in rows if r[2] <= -MOVE) / len(rows) if rows else float("nan")
    hit_up = sum(1 for r in up if r[2] >= MOVE) / len(up) if up else float("nan")
    hit_dn = sum(1 for r in dn if r[2] <= -MOVE) / len(dn) if dn else float("nan")
    return {"n_up": len(up), "n_dn": len(dn), "hit_up": hit_up, "hit_dn": hit_dn, "base_up": base_up, "base_dn": base_dn,
            "lift_up": hit_up - base_up, "lift_dn": hit_dn - base_dn}


def main():
    garak = load_garak({v[1] for v in ITEMS.values()})
    result = {}
    for fname, (name, gname) in ITEMS.items():
        d_ser = load_daegu(fname)
        g_ser = garak.get(gname, {})
        d_days = set().union(*[set(s) for s in d_ser.values()]) if d_ser else set()
        g_days = set().union(*[set(s) for s in g_ser.values()]) if g_ser else set()
        dates = sorted(d_days & g_days)
        if len(dates) < 200:
            result[name] = {"error": f"겹치는 날 {len(dates)}일"}
            continue
        g_idx, d_idx = index_of(g_ser, dates), index_of(d_ser, dates)
        per_lag = {}
        for k in LAGS:
            tr = evaluate(g_idx, d_idx, dates, "00000000", SPLIT, k)
            te = evaluate(g_idx, d_idx, dates, SPLIT, "99999999", k)
            ltr, lte = lift(tr), lift(te)
            per_lag[k] = {
                "corr": corr([r[0] for r in tr + te], [r[2] for r in tr + te]),
                "corr_own": corr([r[1] for r in tr + te], [r[2] for r in tr + te]),
                "r2_gain": r2_gain([r[2] for r in tr + te], [r[1] for r in tr + te], [r[0] for r in tr + te]),
                "train": ltr, "test": lte,
            }
        def avg_lift(l):
            v = [x for x in (l["lift_up"], l["lift_dn"]) if x == x]
            return sum(v) / len(v) if len(v) == 2 else float("nan")
        cand = [k for k in LAGS if per_lag[k]["train"]["n_up"] >= MIN_EVENTS and per_lag[k]["train"]["n_dn"] >= MIN_EVENTS]
        best = max(cand, key=lambda k: avg_lift(per_lag[k]["train"])) if cand else None
        res = {"days": len(dates), "from": dates[0], "to": dates[-1], "best_lag": best, "lags": per_lag}
        if best:
            tr, te = per_lag[best]["train"], per_lag[best]["test"]
            res["train_lift"], res["test_lift"] = avg_lift(tr), avg_lift(te)
            ok_n = te["n_up"] + te["n_dn"] >= MIN_EVENTS
            if ok_n and res["train_lift"] >= 0.05 and res["test_lift"] >= 0.05 and te["lift_up"] > 0 and te["lift_dn"] > 0:
                res["verdict"] = "쓸 만함"
            elif ok_n and res["train_lift"] > 0 and res["test_lift"] > 0:
                res["verdict"] = "약함"
            elif not ok_n:
                res["verdict"] = "표본 부족"
            else:
                res["verdict"] = "없음"
        else:
            res["verdict"] = "표본 부족"
        result[name] = res
        print(name, res["days"], "일", "시차", best, res.get("verdict"), flush=True)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=lambda x: None if x != x else x), encoding="utf-8")
    print("저장", OUT)


if __name__ == "__main__":
    main()
