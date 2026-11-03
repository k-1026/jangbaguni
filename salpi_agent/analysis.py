"""시세 계산과 가격 방향 예측.

살피 원칙(기획서 11장): 숫자는 여기서만 만든다. 제미나이는 이 결과를 설명만 한다.
예측은 통계 모델이 아니라 이유를 하나하나 보여 줄 수 있는 규칙 기반 추정이다.
"""

import statistics
from datetime import date, timedelta

from data_sources import (ITEMS, daegu_events, events_between, foodspring_url, holidays,
                          holidays_between, perday_prices, sale_days, weather_days)

FLAT_BAND = 3.0  # ±3% 안쪽은 '비슷함'으로 본다


def _direction(pct, band=FLAT_BAND):
    if pct is None:
        return "데이터 부족"
    if pct >= band:
        return "올랐어요"
    if pct <= -band:
        return "내렸어요"
    return "비슷해요"


def _pct(new, old):
    if not new or not old:
        return None
    return round((new - old) / old * 100, 1)


# ---------------------------------------------------------------
# 시세 묶음
# ---------------------------------------------------------------

def wholesale_series(item_name, days=28):
    """대구 북부도매시장 경락가: 거래일별 kg당 가중평균가와 반입량(kg)."""
    cfg = ITEMS[item_name]
    series = []
    for day, rows in sorted(sale_days(days).items()):
        hits = [r for r in rows
                if r["gds_mclsf_nm"] == cfg["sale_name"]
                and (not cfg["sale_sub"] or cfg["sale_sub"] in (r["gds_sclsf_nm"] or ""))
                and r["unit_nm"] == "kg"]
        qty = sum(float(r["unit_tot_qty"] or 0) for r in hits)
        amount = sum(float(r["totprc"] or 0) for r in hits)
        if qty > 0 and amount > 0:
            series.append({"date": day.isoformat(), "kg_price": round(amount / qty), "volume_kg": round(qty)})
    return series


def _unit_price(r):
    """perDay 한 줄 → (단위당 가격, 단위). kg·g는 kg당, 개·포기는 1개(포기)당."""
    unit, size = r.get("unit") or "", float(r.get("unit_sz") or 1)
    if unit.startswith("kg") and "포기" not in unit or unit == "g":
        return float(r["exmn_dd_cnvs_prc"]), "kg"
    return float(r["exmn_dd_prc"]) / size, unit.split("(")[0] or "개"


def retail_series(item_name, days=35):
    """KAMIS 조사가격(대구, 상품 등급): 날짜별 소매 평균가(단위 포함)."""
    by_date, unit = {}, None
    for r in perday_prices(item_name, days):
        if r.get("grd_cd") != "04" or r.get("se_nm") != "소매":
            continue
        try:
            price, unit = _unit_price(r)
        except (TypeError, ValueError):
            continue
        d = f"{r['exmn_ymd'][:4]}-{r['exmn_ymd'][4:6]}-{r['exmn_ymd'][6:]}"
        by_date.setdefault(d, []).append(price)
    return [{"date": d, "retail": round(statistics.mean(v)), "unit": unit} for d, v in sorted(by_date.items())]


def _week_change(series, key):
    """최근 3개 값 평균 vs 7일 전 무렵 3개 값 평균."""
    points = [(date.fromisoformat(p["date"]), p[key]) for p in series if p.get(key)]
    if len(points) < 4:
        return None, None, None
    last_day = points[-1][0]
    recent = [v for d, v in points if d > last_day - timedelta(3)][-3:]
    before = [v for d, v in points if last_day - timedelta(10) < d <= last_day - timedelta(7)][-3:]
    if not before:
        return points[-1][1], None, points[-1][0].isoformat()
    return points[-1][1], _pct(statistics.mean(recent), statistics.mean(before)), last_day.isoformat()


def item_trend(item_name):
    """재료 하나의 도매·소매 시세와 1주 전 대비 변화."""
    if item_name not in ITEMS:
        return {"error": f"'{item_name}'은(는) 아직 지원하지 않아요. 지원 품목: {', '.join(ITEMS)}"}
    whl = wholesale_series(item_name)
    ret = retail_series(item_name)
    w_price, w_pct, w_date = _week_change(whl, "kg_price")
    r_price, r_pct, r_date = _week_change(ret, "retail")
    return {
        "item": item_name,
        "wholesale": {"source": "aT 정산정보 · 대구 북부도매시장(매천시장)", "date": w_date,
                      "kg_price": w_price, "week_change_pct": w_pct, "direction": _direction(w_pct),
                      "volume_kg": whl[-1]["volume_kg"] if whl else None},
        "retail": {"source": "aT 일별 도·소매가(KAMIS 조사) · 대구 소매 평균, 상품", "date": r_date,
                   "price": r_price, "unit": ret[-1]["unit"] if ret else None, "week_change_pct": r_pct, "direction": _direction(r_pct)},
        "wholesale_history": whl[-14:],
    }


def market_overview():
    """지원 품목 전체 요약 (대시보드 · 아침 브리핑용)."""
    rows = []
    for name in ITEMS:
        t = item_trend(name)
        rows.append({"item": name,
                     "wholesale_kg": t["wholesale"]["kg_price"], "wholesale_change_pct": t["wholesale"]["week_change_pct"],
                     "wholesale_date": t["wholesale"]["date"], "direction": t["wholesale"]["direction"],
                     "retail_price": t["retail"]["price"], "retail_unit": t["retail"]["unit"],
                     "retail_change_pct": t["retail"]["week_change_pct"], "foodspring_url": foodspring_url(name)})
    return rows


# ---------------------------------------------------------------
# 다음 7일 가격 방향 추정
# ---------------------------------------------------------------

LEAFY = {"대파", "깻잎", "양배추", "배추", "상추", "시금치"}   # 비·한파에 민감한 잎·줄기 채소
COLD_SENSITIVE = {"대파", "깻잎", "청양고추", "상추", "시금치", "오이", "애호박", "가지", "토마토"}  # 한파·난방비 영향


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def weather_summary(days=7):
    w = weather_days(35)[-days:]
    if not w:
        return {"days": 0}
    return {"days": len(w), "from": w[0]["date"], "to": w[-1]["date"],
            "rain_total_mm": round(sum(d["rain_mm"] for d in w), 1),
            "rain_days": sum(1 for d in w if d["rain_mm"] >= 1),
            "min_temp": min(d["min_temp"] for d in w if d["min_temp"] is not None),
            "max_temp": max(d["max_temp"] for d in w if d["max_temp"] is not None),
            "hot_days": sum(1 for d in w if (d["max_temp"] or 0) >= 33),
            "freezing_days": sum(1 for d in w if (d["min_temp"] or 0) <= -3),
            "daily": w}


def forecast_item(item_name):
    """다음 7일 도매가 방향을 이유(요인별 %)와 함께 추정."""
    if item_name not in ITEMS:
        return {"error": f"'{item_name}'은(는) 아직 지원하지 않아요. 지원 품목: {', '.join(ITEMS)}"}
    series = wholesale_series(item_name, 28)
    factors = []

    # 1) 최근 2주 추세 (추세는 꺾이기 쉬워 절반만 반영)
    recent = [p for p in series if date.fromisoformat(p["date"]) > date.today() - timedelta(15)]
    if len(recent) >= 5:
        xs = [(date.fromisoformat(p["date"]) - date.today()).days for p in recent]
        ys = [p["kg_price"] for p in recent]
        slope = statistics.linear_regression(xs, ys).slope
        effect = _clip(slope * 7 / statistics.mean(ys) * 100 * 0.5, -10, 10)
        factors.append({"factor": "최근 2주 시세 흐름", "effect_pct": round(effect, 1),
                        "detail": f"2주 동안 하루 평균 {slope:+.0f}원/kg 움직였어요"})

    # 2) 반입량: 시장에 들어오는 양이 줄면 오르고, 늘면 내린다
    vols = [p["volume_kg"] for p in series]
    if len(vols) >= 8:
        v_pct = _pct(statistics.mean(vols[-3:]), statistics.mean(vols[-13:-3]))
        if v_pct is not None:
            effect = _clip(-0.25 * v_pct, -6, 6)
            factors.append({"factor": "도매시장 반입량", "effect_pct": round(effect, 1),
                            "detail": f"최근 3거래일 반입량이 그 전 평균보다 {v_pct:+.0f}%"})

    # 3) 대구 날씨 (지난 7일, 주산지 날씨는 아직 반영 못 함)
    w = weather_summary(7)
    if w.get("days"):
        effect, notes = 0.0, []
        if w["rain_total_mm"] >= 30:
            effect += 3 if item_name in LEAFY else 1.5
            notes.append(f"비 {w['rain_total_mm']}mm")
        if w["freezing_days"] and item_name in COLD_SENSITIVE:
            effect += 2
            notes.append(f"영하 3도 이하 {w['freezing_days']}일")
        if w["hot_days"] >= 3:
            effect += 2
            notes.append(f"33도 이상 {w['hot_days']}일")
        factors.append({"factor": "날씨(대구, 지난 7일)", "effect_pct": effect,
                        "detail": ", ".join(notes) if notes else
                        f"비 {w['rain_total_mm']}mm, 최저 {w['min_temp']}도 · 최고 {w['max_temp']}도로 큰 영향 없음"})

    # 4) 다가오는 공휴일 (도매시장 휴장 전 수요가 몰림)
    hol = holidays(10)
    if hol:
        big = any(n in h["name"] for h in hol for n in ("설", "추석"))
        factors.append({"factor": "다가오는 공휴일", "effect_pct": 4.0 if big else 2.0,
                        "detail": ", ".join(f"{h['date'][4:6]}/{h['date'][6:]} {h['name']}" for h in hol)})
    else:
        factors.append({"factor": "다가오는 공휴일", "effect_pct": 0.0, "detail": "10일 안에 공휴일 없음"})

    # 5) 대구 행사 (외식 수요 ↑ → 가격 영향은 작게)
    ev = daegu_events(7)
    factors.append({"factor": "대구 행사·축제(7일 안)", "effect_pct": 1.0 if len(ev) >= 5 else 0.0,
                    "detail": f"{len(ev)}개 진행" + (" — 메뉴 판매에 더 큰 영향" if ev else "")})

    total = sum(f["effect_pct"] for f in factors)
    daily = [_pct(b["kg_price"], a["kg_price"]) for a, b in zip(series, series[1:])]
    spread = 2 + (_clip(statistics.pstdev(daily) * 1.5, 0, 10) if len(daily) >= 5 else 6)
    enough = len(series) >= 8
    if total >= 2:
        direction, tip = "오를 가능성이 있어요", "필요한 양은 미리 사 두는 편이 나아요"
    elif total <= -2:
        direction, tip = "내릴 가능성이 있어요", "급하지 않으면 며칠 기다려 보세요"
    else:
        direction, tip = "비슷할 가능성이 커요", "평소대로 사면 돼요"
    last = series[-1] if series else None
    return {
        "item": item_name, "horizon": "다음 7일", "base_date": last["date"] if last else None,
        "base_kg_price": last["kg_price"] if last else None,
        "expected_change_pct": round(total, 1),
        "range_pct": [round(total - spread, 1), round(total + spread, 1)],
        "expected_kg_price_range": [round(last["kg_price"] * (1 + (total - spread) / 100)),
                                    round(last["kg_price"] * (1 + (total + spread) / 100))] if last else None,
        "direction": direction, "suggestion": tip,
        "confidence": "보통" if enough and spread < 8 else "낮음",
        "factors": factors,
        "method": "규칙 기반 추정(추세·반입량·날씨·공휴일·행사). 주산지 날씨와 수입량은 아직 반영하지 않음",
    }


# ---------------------------------------------------------------
# 대시보드 상세: 날짜별 시세 + 그날 날씨 · 공휴일 · 행사
# ---------------------------------------------------------------

def item_detail(item_name, days=28):
    if item_name not in ITEMS:
        return {"error": f"'{item_name}'은(는) 아직 지원하지 않아요"}
    series = wholesale_series(item_name, days)
    start, end = date.today() - timedelta(days), date.today()
    weather = {w["date"]: w for w in weather_days(35)}
    hols = {f"{h['date'][:4]}-{h['date'][4:6]}-{h['date'][6:]}": h["name"] for h in holidays_between(start, end)}
    events = events_between(start, end)

    def active(d):
        k = d.replace("-", "")
        return [e["title"] for e in events if (e["start"] or "") <= k <= (e["end"] or "")]

    rows, prev = [], None
    for p in series:
        w = weather.get(p["date"], {})
        rows.append({**p, "diff": p["kg_price"] - prev if prev else None,
                     "rain_mm": w.get("rain_mm"), "max_temp": w.get("max_temp"), "min_temp": w.get("min_temp"),
                     "holiday": hols.get(p["date"]), "events": active(p["date"])})
        prev = p["kg_price"]
    return {"item": item_name, "history": rows,
            "holidays": [{"date": d, "name": n} for d, n in sorted(hols.items())],
            "events": events, "forecast": forecast_item(item_name),
            "trend": {k: v for k, v in item_trend(item_name).items() if k != "wholesale_history"},
            "foodspring_url": foodspring_url(item_name)}


# ---------------------------------------------------------------
# 지금 사면 이득인 재료
# ---------------------------------------------------------------

def buy_now_recommendations():
    """지금 사기 / 지금 싸요 / 기다리기 로 나눔.
    - 다음 7일 오를 가능성 → 지금 사기
    - 1주 새 5% 넘게 내렸고 더 내릴 신호가 없으면 → 지금 싸요
    - 다음 7일 내릴 가능성 → 기다리기"""
    buy, cheap, wait, normal = [], [], [], []
    for name in ITEMS:
        f = forecast_item(name)
        t = item_trend(name)["wholesale"]
        row = {"item": name, "kg_price": t["kg_price"], "week_change_pct": t["week_change_pct"],
               "next_week": f.get("direction"), "expected_change_pct": f.get("expected_change_pct"),
               "range_pct": f.get("range_pct"), "confidence": f.get("confidence"),
               "main_reason": max(f.get("factors", []), key=lambda x: abs(x["effect_pct"]), default={}).get("detail"),
               "foodspring_url": foodspring_url(name)}
        exp = f.get("expected_change_pct") or 0
        if exp >= 2:
            buy.append(row)
        elif exp <= -2:
            wait.append(row)
        elif (t["week_change_pct"] or 0) <= -5:
            cheap.append(row)
        else:
            normal.append(row)
    buy.sort(key=lambda r: -(r["expected_change_pct"] or 0))
    cheap.sort(key=lambda r: r["week_change_pct"] or 0)
    wait.sort(key=lambda r: r["expected_change_pct"] or 0)
    # 답이 길어지지 않게 묶음마다 3개까지만, 나머지는 이름만
    return {"buy_now_before_rise": buy[:3], "cheap_now": cheap[:3], "wait": wait[:3],
            "more_buy_now": [r["item"] for r in buy[3:]], "more_wait": [r["item"] for r in wait[3:]],
            "as_usual": [r["item"] for r in normal]}
