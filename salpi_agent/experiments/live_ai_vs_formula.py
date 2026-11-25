"""실전 채점: 화면에 나간 AI 모델 예측 vs 같은 날 고정 공식 (야채 · 과일).

실행:  .venv\\Scripts\\python -m experiments.live_ai_vs_formula        (.env 의 SUPABASE_* · AT_SALE_* · KMA_ASOS_* 필요, 1~2분)

- AI 예측: Supabase forecast_log 에서 formula_version 이 'ai-' 로 시작하는 줄 (11/17부터 화면에 나감)
  주말 · 휴장일에 같은 기준 날짜로 여러 번 저장된 것은 품목 · 기준 날짜마다 처음 것 하나만 셈 (forecast_log.scorecard 와 같음)
- 고정 공식: 화면에 AI가 나가면 고정 공식은 저장되지 않음 → 그 기준 날짜로 analysis.forecast_item 과 같은 계산을 다시 함
  (4주 평균과의 차이 · 반입량 · 대구 지난 7일 날씨 · 공휴일 · 대구 행사, 계수는 analysis.py 그대로)
- 실제: 기준 날짜 + 7일 이후 사흘 안 첫 시세 (forecast_log.score 와 같음). 기록에 아직 채점이 안 된 줄도 여기서 직접 채점
- 결과: experiments/results/live_ai_vs_formula.json
"""
import json
import statistics
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from price import analysis   # noqa: E402
from price.forecast_log import BAND, LOOK_AHEAD, _direction, today   # noqa: E402
from sources import supabase_db   # noqa: E402
from sources.data_sources import ITEMS, events_between, holidays_between, kind_of, sale_days, weather_days   # noqa: E402

OUT = Path(__file__).resolve().parent / "results" / "live_ai_vs_formula.json"


def ai_rows():
    """채점할 수 있는(기준 날짜 + 7일이 지난) AI 예측, 품목 · 기준 날짜마다 처음 것 하나."""
    last = (today() - timedelta(7)).isoformat()
    rows = supabase_db.select("forecast_log", formula_version="like.ai-*", base_date=f"lte.{last}",
                              select="run_date,item,kind,base_date,base_price,expected_change_pct,range_low,range_high,"
                                     "direction,actual_date,actual_price,formula_version")
    first = {}
    for r in sorted(rows, key=lambda r: r["run_date"]):
        first.setdefault((r["item"], r["base_date"]), r)
    return list(first.values())


def all_series(days):
    """품목 → [{date, kg_price, volume_kg}] (analysis.wholesale_series 와 같은 계산, 하루치 자료를 한 번만 받음)."""
    raw = sorted(sale_days(days).items())
    out = {}
    for name, cfg in ITEMS.items():
        s = []
        for day, rows in raw:
            hits = [r for r in rows if r["gds_mclsf_nm"] == cfg["sale_name"]
                    and (not cfg["sale_sub"] or cfg["sale_sub"] in (r["gds_sclsf_nm"] or "")) and r["unit_nm"] == "kg"]
            qty = sum(float(r["unit_tot_qty"] or 0) for r in hits)
            amount = sum(float(r["totprc"] or 0) for r in hits)
            if qty > 0 and amount > 0:
                s.append({"date": day.isoformat(), "kg_price": round(amount / qty), "volume_kg": round(qty)})
        out[name] = s
    return out


def formula_at(name, series, run_day, weather):
    """analysis.forecast_item 을 run_day(예측을 낸 날)에 돌렸다면 → 예상 변화율 · 범위 %."""
    fruit = kind_of(name) == "과일"
    total = 0.0
    f = analysis.reversion_factor([p["kg_price"] for p in series], *(analysis.FRUIT_REVERSION if fruit else analysis.VEG_REVERSION))
    total += f["effect_pct"] if f else 0
    f = analysis.volume_factor([p["volume_kg"] for p in series], *(analysis.FRUIT_VOLUME if fruit else analysis.VEG_VOLUME))
    total += f["effect_pct"] if f else 0
    if not fruit:
        # weather_summary(7): 예측한 날 기준 어제까지 7일
        w = [x for x in weather if (run_day - timedelta(7)).isoformat() <= x["date"] <= (run_day - timedelta(1)).isoformat()]
        if w:
            effect, _ = analysis.weather_effect(name, round(sum(d["rain_mm"] for d in w), 1),
                                                sum(1 for d in w if (d["min_temp"] or 0) <= -3),
                                                sum(1 for d in w if (d["max_temp"] or 0) >= 33))
            total += effect
    hol = holidays_between(run_day, run_day + timedelta(7))
    if hol:
        total += 4.0 if any(n in h["name"] for h in hol for n in ("설", "추석")) else 2.0
    total += 1.0 if len(events_between(run_day, run_day + timedelta(7))) >= 5 else 0.0
    daily = [analysis._pct(b["kg_price"], a["kg_price"]) for a, b in zip(series, series[1:])]
    spread = 2 + (analysis._clip(statistics.pstdev(daily) * 1.5, 0, 10) if len(daily) >= 5 else 6)
    return round(total, 1), (round(total - spread, 1), round(total + spread, 1))


def actual(series, base):
    target = date.fromisoformat(base) + timedelta(7)
    return next(((p["date"], p["kg_price"]) for p in series
                 if target <= date.fromisoformat(p["date"]) <= target + timedelta(LOOK_AHEAD)), None)


def summary(group, key):
    n = len(group)
    if not n:
        return {"n": 0}
    pred = [r[key] for r in group]
    real = [r["actual_change_pct"] for r in group]
    opp = sum(1 for p, a in zip(pred, real) if {_direction(p["change"]), _direction(a)} == {"up", "down"})
    return {"n": n,
            "direction_hit_pct": round(sum(_direction(p["change"]) == _direction(a) for p, a in zip(pred, real)) / n * 100, 1),
            "in_range_pct": round(sum(p["low"] <= a <= p["high"] for p, a in zip(pred, real)) / n * 100, 1),
            "opposite_pct": round(opp / n * 100, 1),
            "mae_pp": round(statistics.mean(abs(p["change"] - a) for p, a in zip(pred, real)), 2)}


def main():
    rows = ai_rows()
    if not rows:
        print("채점할 AI 예측이 아직 없어요")
        return
    oldest = min(date.fromisoformat(r["base_date"]) for r in rows)
    days = (today() - oldest).days + 30
    series = all_series(days)
    weather = weather_days(days)

    cases = []
    for r in rows:
        s = series.get(r["item"]) or []
        upto = [p for p in s if p["date"] <= r["base_date"] and p["date"] >= (date.fromisoformat(r["base_date"]) - timedelta(27)).isoformat()]
        hit = actual(s, r["base_date"])
        # 기준 날짜가 휴장일(예: 11/17)이면 직전 개장일 시세가 기준 — 사흘 넘게 비면 건너뜀
        if not hit or not upto or (date.fromisoformat(r["base_date"]) - date.fromisoformat(upto[-1]["date"])).days > 3:
            continue   # 7일 뒤 시세가 아직 없거나 기준 날짜 시세를 다시 못 받음
        base = float(r["base_price"])
        change = round((hit[1] / base - 1) * 100, 2)
        f_change, (f_lo, f_hi) = formula_at(r["item"], upto, date.fromisoformat(r["run_date"]), weather)
        ai_lo, ai_hi = (float(r["range_low"]) / base - 1) * 100, (float(r["range_high"]) / base - 1) * 100
        cases.append({"item": r["item"], "kind": r["kind"], "run_date": r["run_date"], "base_date": r["base_date"],
                      "base_price": base, "recomputed_base_price": upto[-1]["kg_price"],
                      "actual_date": hit[0], "actual_price": hit[1], "actual_change_pct": change,
                      "ai": {"change": float(r["expected_change_pct"]), "low": round(ai_lo, 1), "high": round(ai_hi, 1),
                             "version": r["formula_version"]},
                      "formula": {"change": f_change, "low": f_lo, "high": f_hi}})

    out = {"made": today().isoformat(), "band_pct": BAND,
           "note": "AI = 화면에 나간 예측(forecast_log), 고정 공식 = 같은 기준 날짜로 다시 계산. 실제 = 기준 날짜 + 7일 이후 사흘 안 첫 시세",
           "by_base_date": {}, "by_kind": {}, "all": {}, "cases": cases}
    for b in sorted({c["base_date"] for c in cases}):
        g = [c for c in cases if c["base_date"] == b]
        out["by_base_date"][b] = {"ai": summary(g, "ai"), "formula": summary(g, "formula")}
    for k in sorted({c["kind"] for c in cases}):
        g = [c for c in cases if c["kind"] == k]
        out["by_kind"][k] = {"ai": summary(g, "ai"), "formula": summary(g, "formula")}
    out["all"] = {"ai": summary(cases, "ai"), "formula": summary(cases, "formula")}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"채점 {len(cases)}건 (AI 예측 {len(rows)}건 중)")
    for title, block in [("전체", {"": out["all"]}), ("종류별", out["by_kind"]), ("기준 날짜별", out["by_base_date"])]:
        print(f"\n[{title}]")
        for k, v in block.items():
            for who in ("ai", "formula"):
                print(f"  {k:>10} {who:8}", v[who])
    mism = [c for c in cases if abs(c["recomputed_base_price"] - c["base_price"]) > 1]
    if mism:
        print(f"\n주의: 기준 값이 기록과 다른 줄 {len(mism)}개", [(c['item'], c['base_date'], c['base_price'], c['recomputed_base_price']) for c in mism][:5])


if __name__ == "__main__":
    main()
