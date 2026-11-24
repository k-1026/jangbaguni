"""발주량 추천 베이스라인 평가: 살피 추천 vs 단순한 방식들을 지난 6달 하루씩 되돌려 보며 비교.

방법 (시뮬레이션)
  1. 시험 기간 = demand_learn 과 같은 마지막 6달(28일 × 6). 그날 이전 기록으로만 예측 (미래 정보 없음)
  2. 방식마다 '그날 메뉴별 그릇 수'를 예측 → 레시피로 재료 필요량 → × (1 + 여유) = 발주량
  3. 실제 판매량 × 레시피 = 실제 쓴 재료량. 발주량이 모자라면 '모자란 날', 남으면 '남는 양'
  4. 모든 방식에 같은 레시피 · 같은 여유를 써서, 차이는 '예측 방식'에서만 나오게 함

방식: 어제만큼 · 지난주 같은 요일 · 최근 4주 평균 · 살피 규칙 · 살피 학습 모델
(살피 학습 모델 = demand_learn 과 같은 부스팅을 시험 달마다 그 달 앞 기록으로만 학습. numpy 를 쓸 수 있는 PC 에서만 자동 포함)

실행:  salpi_agent 폴더에서  python -m demand.order_eval
가상 판매 기록 평가라 '실제 가게에서 이만큼'이 아니라 '방식끼리의 상대 비교'로 읽을 것. 모델 파일은 건드리지 않음.
"""
import csv
import json
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from demand import demand
from demand import dummy_store as DS

BASE_METHODS = ["어제만큼", "지난주 같은 요일", "최근 4주 평균", "살피 규칙"]
LEARNED = "살피 학습 모델"   # numpy 를 쓸 수 있는 PC 에서만 자동으로 추가됨
METHODS = list(BASE_METHODS)
FOLDS = 6   # demand_learn 과 같은 시험 기간: 마지막 6달(28일씩)
MARGINS = [0.0, 0.05, 0.10, 0.15]
CURRENT_MARGIN = 0.10   # demand.py 의 SAFETY
TARGET_SHORT = 0.05     # '같은 안전도' 비교: 재료·날 기준 모자람 5% 이하
OUT = Path(__file__).resolve().parents[2] / "plan" / "forecast" / "1124_order_baseline_eval.json"


def recipes():
    out = defaultdict(list)
    with open(DS.OUT / "recipes.csv", encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            out[r["메뉴"]].append((r["재료"], float(r["1인분_양(기준단위)"]), float(r["손질_손실"])))
    return out


def baseline_preds(h, d):
    """h: [(날짜, 그릇)] 오름차순. d 이전 기록만 써서 세 가지 단순 방식의 d 예측."""
    past = [(x, q) for x, q in h if x < d]
    yesterday = past[-1][1]
    by = dict(past[-35:])
    last_week = by.get(d - timedelta(7), yesterday)
    recent = [q for x, q in past if x >= d - timedelta(28)]
    return yesterday, last_week, sum(recent) / len(recent)


def load():
    """가상 가게 판매 기록(메뉴별 {날짜: 그릇}) · 공휴일 날짜."""
    hist, holidays = defaultdict(dict), set()
    with open(DS.OUT / "sales_daily.csv", encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            d = date.fromisoformat(r["날짜"])
            hist[r["메뉴"]][d] = hist[r["메뉴"]].get(d, 0) + int(r["그릇수"])
    with open(DS.OUT / "calendar.csv", encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            if r["공휴일"]:
                holidays.add(r["날짜"])
    return {m: sorted(v.items()) for m, v in hist.items()}, holidays


def rule_predict(h, d, holidays):
    """지금 규칙(demand.py) — d 이전 기록만 씀."""
    return demand._MenuModel({x: q for x, q in h if x < d}, holidays).predict(d, holidays)[0]


def learned_preds(hist, test_days):
    """살피 학습 모델: 시험 달마다 그 달 앞 기록으로만 학습 → 그 달 예측. numpy 를 못 쓰면 None."""
    try:
        import numpy as np
        from demand import demand_learn as DL
        menus, h2, cal = DL.load()
        rs = DL.rows(menus, h2, cal)
        last = max(r[0] for r in rs)
        out = {}
        for k in range(FOLDS, 0, -1):
            t0, t1 = last - timedelta(28 * k - 1), last - timedelta(28 * (k - 1))
            v0 = t0 - timedelta(28)
            tr = [r for r in rs if r[0] < v0]
            va = [r for r in rs if v0 <= r[0] < t0]
            te = [r for r in rs if t0 <= r[0] <= t1]
            g = DL.fit(tr, va)
            for r, p in zip(te, g.predict(DL.X(te)) * np.array([r[3] for r in te])):
                out[(r[0], r[1])] = float(p)
            print(f"  학습 모델 {t0} ~ {t1} 예측 완료", flush=True)
        return out
    except Exception as e:
        print(f"[학습 모델 건너뜀] {type(e).__name__}: {str(e)[:80]}", flush=True)
        return None


def collect():
    """시험 기간 날짜 × 메뉴마다 방식별 예측 그릇 수와 실제 그릇 수."""
    hist, holidays = load()
    last = max(d for h in hist.values() for d, _q in h)
    t0 = last - timedelta(28 * FOLDS - 1)
    pred, actual = {m: {} for m in BASE_METHODS}, {}
    for m, h in hist.items():
        for d, q in h:
            if d < t0:
                continue
            key = (d, m)
            actual[key] = q
            a, b, c = baseline_preds(h, d)
            pred["어제만큼"][key], pred["지난주 같은 요일"][key], pred["최근 4주 평균"][key] = a, b, c
            pred["살피 규칙"][key] = rule_predict(h, d, holidays)
    learned = learned_preds(hist, None)
    if learned is not None:
        pred[LEARNED] = {k: learned[k] for k in actual}
        METHODS.append(LEARNED)
    return pred, actual


def ingredient_days(bowls, rec):
    """{(날짜, 재료): 필요량} — 메뉴별 그릇 수(bowls[(날짜, 메뉴)])를 재료로 환산."""
    need = defaultdict(float)
    for (d, m), n in bowls.items():
        for item, qty, loss in rec[m]:
            need[(d, item)] += n * qty / (1 - loss)
    return need


def score(pred_need, real_need, margin):
    keys = sorted(real_need)
    order = [pred_need[k] * (1 + margin) for k in keys]
    real = [real_need[k] for k in keys]
    short = [o < r - 1e-9 for o, r in zip(order, real)]
    days = defaultdict(bool)
    for k, sh in zip(keys, short):
        days[k[0]] |= sh
    total = sum(real)
    return {
        "short_rate": sum(short) / len(short) * 100,                       # 재료·날 중 모자란 비율 %
        "short_day_rate": sum(days.values()) / len(days) * 100,            # 하루라도 모자란 재료가 있던 날 %
        "short_amt": sum(max(r - o, 0) for o, r in zip(order, real)) / total * 100,   # 모자란 양 / 쓴 양 %
        "leftover": sum(max(o - r, 0) for o, r in zip(order, real)) / total * 100,    # 남는 양 / 쓴 양 %
    }


def margin_for(pred_need, real_need, target):
    """재료·날 모자람 비율이 target 이하가 되는 가장 작은 여유(1% 단위)."""
    for m in range(0, 101):
        if score(pred_need, real_need, m / 100)["short_rate"] <= target * 100:
            return m / 100
    return None


def main():
    rec = recipes()
    print("시험 기간 예측 중")
    pred, actual = collect()
    real_need = ingredient_days(actual, rec)
    needs = {m: ingredient_days(pred[m], rec) for m in METHODS}
    days = sorted({k[0] for k in actual})
    print(f"\n시험 {days[0]} ~ {days[-1]} · 장사한 날 {len(days)}일 · 재료 {len({k[1] for k in real_need})}종 · 재료×날 {len(real_need)}건")

    result = {"period": [str(days[0]), str(days[-1])], "open_days": len(days), "rows": len(real_need),
              "by_margin": {}, "same_safety": {}, "demand_mae": {}, "per_item": {}}
    # 0) 예측 자체의 오차 (그릇 수, 메뉴×날)
    keys = sorted(actual)
    for m in METHODS:
        result["demand_mae"][m] = statistics.mean(abs(pred[m][k] - actual[k]) for k in keys)
    # 1) 여유별 점수
    for m in METHODS:
        result["by_margin"][m] = {f"{int(mg * 100)}": score(needs[m], real_need, mg) for mg in MARGINS}
    # 2) 같은 안전도(모자람 5% 이하)에서 필요한 여유와 남는 양
    for m in METHODS:
        mg = margin_for(needs[m], real_need, TARGET_SHORT)
        result["same_safety"][m] = {"margin": mg, **(score(needs[m], real_need, mg) if mg is not None else {})}
    # 3) 살피(학습 모델) 재료별, 현재 여유 10%
    items = sorted({k[1] for k in real_need})
    for it in items:
        rn = {k: v for k, v in real_need.items() if k[1] == it}
        result["per_item"][it] = {m: score(needs[m], rn, CURRENT_MARGIN) for m in METHODS if m in ("최근 4주 평균", "살피 규칙", LEARNED)}

    print("\n[예측 자체: 메뉴×날 평균 오차(그릇)]")
    for m in METHODS:
        print(f"  {m:<10} {result['demand_mae'][m]:5.2f}")
    for mg in MARGINS:
        print(f"\n[여유 {int(mg * 100)}%]  모자란 재료·날% | 모자란 날% | 모자란 양% | 남는 양%")
        for m in METHODS:
            s = result["by_margin"][m][str(int(mg * 100))]
            print(f"  {m:<10} {s['short_rate']:6.1f} | {s['short_day_rate']:6.1f} | {s['short_amt']:6.2f} | {s['leftover']:6.1f}")
    print(f"\n[같은 안전도: 재료·날 모자람 {int(TARGET_SHORT * 100)}% 이하가 되는 최소 여유]")
    for m in METHODS:
        s = result["same_safety"][m]
        print(f"  {m:<10} 필요 여유 {s['margin']}  모자란 날% {s.get('short_day_rate', 0):.1f}  남는 양% {s.get('leftover', 0):.1f}")
    print("\n[재료별, 여유 10% — 모자란 재료·날% / 남는 양%]  " + " → ".join(next(iter(result["per_item"].values()))))
    for it, v in result["per_item"].items():
        print(f"  {it:<10} " + "   →   ".join(f"{s['short_rate']:5.1f} / {s['leftover']:5.1f}" for s in v.values()))
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
