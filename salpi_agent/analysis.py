"""시세 계산과 가격 방향 예측.

살피 원칙(기획서 11장): 숫자는 여기서만 만든다. 제미나이는 이 결과를 설명만 한다.
예측은 통계 모델이 아니라 이유를 하나하나 보여 줄 수 있는 규칙 기반 추정이다.
"""

import statistics
from datetime import date, timedelta

from data_sources import (kind_of, BEEF_GRADES, EKAPE_LINKS, EKAPE_MARKET_NAME, EXTRA_ITEMS, PIG_GRADES, ITEMS, daegu_events, ekape_days,
                          events_between, foodspring_url, holidays, holidays_between, perday_prices, sale_days,
                          weather_days)

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
    grd = ITEMS[item_name].get("retail_grd", "04")   # 상품 등급 (감귤 · 포도는 크기 등급)
    for r in perday_prices(item_name, days):
        if r.get("grd_cd") != grd or r.get("se_nm") != "소매":
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
        rows.append({"item": name, "kind": kind_of(name),
                     "wholesale_kg": t["wholesale"]["kg_price"], "wholesale_change_pct": t["wholesale"]["week_change_pct"],
                     "wholesale_date": t["wholesale"]["date"], "direction": t["wholesale"]["direction"],
                     "retail_price": t["retail"]["price"], "retail_unit": t["retail"]["unit"],
                     "retail_change_pct": t["retail"]["week_change_pct"], "foodspring_url": foodspring_url(name)})
    return rows


# ---------------------------------------------------------------
# 육류 · 수산물
#   가격: aT 일별 도·소매가(KAMIS 조사) — 수산물은 북부도매시장 중도매가, 육류 · 젓갈은 대구 소매 평균
#         (육류는 KAMIS에 소매만 있음. 사장님이 실제로 사는 값이라 대시보드는 이 값)
#   한우 등심 · 양지 · 돼지 앞다리 · 삼겹살은 협신식품(대구) 도매 경락가(축산물품질평가원)를
#   재료 페이지 등급표에만 씀 (예측 이유로는 채점에서 더 나빠져 뺌)
# ---------------------------------------------------------------

def _extra_unit_price(r):
    """perDay 한 줄 → (단위당 가격, 단위). g·kg은 kg당, 구는 1개당, 그 밖(마리 · 손)은 그 단위당.
    육류는 환산가(exmn_dd_cnvs_prc)가 의미 없는 값으로 와서 조사가 ÷ 단위 크기로 직접 계산함."""
    unit, size, price = r.get("unit") or "", float(r.get("unit_sz") or 1), float(r["exmn_dd_prc"])
    if unit == "g":
        return price / size * 1000, "kg"
    if unit == "kg":
        return price / size, "kg"
    if unit == "구":
        return price / size, "개"
    return price / size, unit or "개"


def retail_extra_series(item_name, days=35):
    """perDay(KAMIS 조사가): 날짜별 대구 평균가(조사한 곳 · 등급 평균)."""
    cfg = EXTRA_ITEMS[item_name]
    by_date, unit = {}, None
    for r in perday_prices(item_name, days):
        if r.get("se_nm") != cfg["se"] or (cfg["grd"] and r.get("grd_cd") != cfg["grd"]):
            continue
        try:
            price, unit = _extra_unit_price(r)
        except (TypeError, ValueError, KeyError):
            continue
        d = f"{r['exmn_ymd'][:4]}-{r['exmn_ymd'][4:6]}-{r['exmn_ymd'][6:]}"
        by_date.setdefault(d, []).append(price)
    return [{"date": d, "price": round(statistics.mean(v)), "unit": unit} for d, v in sorted(by_date.items())]


def auction_series(item_name, days=35):
    """한우 등심 · 양지 · 돼지고기: 협신식품(대구) 경락가 kg당과 경매 물량(상자 · 마리). 키가 없거나 실패하면 빈 목록."""
    link = EKAPE_LINKS.get(item_name)
    if not link:
        return []
    try:
        by_day = ekape_days(days)
    except Exception:
        return []
    out = []
    for d, v in sorted(by_day.items()):
        if link["op"] == "beefGrade":
            x = (v.get("beef") or {}).get(link["cut"]) or {}
            price, count = x.get(link["price"]), x.get(link["count"])
        else:
            x = (v.get("pig") or {}).get(link["grade"]) or {}
            price, count = x.get("price"), x.get("count")
        if price:
            out.append({"date": d.isoformat(), "price": round(price), "unit": "kg", "count": count})
    return out


def extra_series(item_name, days=35):
    """대시보드에 쓰는 가격 (KAMIS 조사가: 수산물 중도매 · 육류 소매)."""
    return retail_extra_series(item_name, days)


def _with_context(series, rain=True, days=40):
    """날짜마다 그날 비 · 공휴일 · 대구 행사를 붙임 (야채 대시보드와 같은 칸)."""
    if not series:
        return series
    start, end = date.fromisoformat(series[0]["date"]), date.today()
    try:
        weather = {w["date"]: w for w in weather_days(days)} if rain else {}
        hols = {f"{h['date'][:4]}-{h['date'][4:6]}-{h['date'][6:]}": h["name"] for h in holidays_between(start, end)}
        events = events_between(start, end)
    except Exception:   # 참고 정보라 못 받아도 가격은 그대로 보여 줌
        weather, hols, events = {}, {}, []

    def active(d):
        k = d.replace("-", "")
        return [e["title"] for e in events if (e["start"] or "") <= k <= (e["end"] or "")]

    return [{**p, "rain_mm": weather.get(p["date"], {}).get("rain_mm") if rain else None,
             "holiday": hols.get(p["date"]), "events": active(p["date"])} for p in series]


def _grade_table(item_name):
    """재료 페이지용 표: 최근 경매일의 등급별 경락가 · 물량 (+ 소매 참고값)."""
    link = EKAPE_LINKS.get(item_name)
    if not link:
        return None
    try:
        by_day = ekape_days(14)
    except Exception:
        return None
    for d, v in sorted(by_day.items(), reverse=True):
        rows = []
        if link["op"] == "beefGrade":
            x = (v.get("beef") or {}).get(link["cut"]) or {}
            if not x.get(link["price"]):   # 그 부위 경매가 없던 날은 건너뜀
                continue
            for name, n in BEEF_GRADES:
                if x.get(f"hanAvg_{n}"):
                    rows.append({"grade": name, "price": round(x[f"hanAvg_{n}"]), "count": x.get(f"han_{n}Cnt")})
            note = f"한우 {link['cut']} · 물량은 경매에 나온 상자 수"
        else:
            pig = v.get("pig") or {}
            if not (pig.get(link["grade"]) or {}).get("price"):
                continue
            for name in PIG_GRADES:
                g = pig.get(name) or {}
                if g.get("price") or g.get("all_price"):
                    rows.append({"grade": name, "price": round(g["price"]) if g.get("price") else None,
                                 "count": g.get("count"), "all_price": round(g["all_price"]) if g.get("all_price") else None})
            note = "돼지 도체(통째) · 물량은 마리 수"
        r = retail_extra_series(item_name)
        retail = {"name": item_name, "price": r[-1]["price"], "unit": r[-1]["unit"], "date": r[-1]["date"]} if r else None
        return {"date": d.isoformat(), "market": EKAPE_MARKET_NAME, "unit": "kg", "rows": rows, "note": note,
                # 소매가와 견줄 경락가: 한우는 같은 1등급, 돼지는 도체 등외 제외 평균
                "compare_grade": "1" if link["op"] == "beefGrade" else None,
                "compare_price": (round(x[link["price"]]) if link["op"] == "beefGrade"
                                  else round((v.get("pig") or {})[link["grade"]]["price"])),
                "compare_name": link["what"], "retail": retail,
                "source": f"축산물품질평가원 축산물경락가격정보 · {EKAPE_MARKET_NAME}"}
    return None


def extra_trend(item_name):
    """육류 · 수산물 하나의 최근 대구 가격과 1주 · 4주 전 대비 변화 · 7일 예측."""
    if item_name not in EXTRA_ITEMS:
        return {"error": f"'{item_name}'은(는) 아직 지원하지 않아요. 육류 · 수산물: {', '.join(EXTRA_ITEMS)}"}
    cfg = EXTRA_ITEMS[item_name]
    series = extra_series(item_name)
    price, week_pct, last = _week_change(series, "price")
    # 4주 변화: 첫 3개 값의 가운데값과 비교 (조사 첫날 하루만 튀는 값이 있음, 예: 닭고기 10/8)
    month_pct = (_pct(series[-1]["price"], statistics.median(p["price"] for p in series[:3]))
                 if len(series) >= 4 else None)
    if cfg.get("se") == "중도매":
        basis, label, source = "중도매", "북부도매시장 중도매가", "aT 일별 도·소매가(KAMIS 조사) · 대구 북부도매시장 중도매가"
    else:
        basis, label, source = "소매", "대구 소매 평균", "aT 일별 도·소매가(KAMIS 조사) · 대구 소매 평균"
    return {
        "item": item_name, "group": cfg["group"],
        "source": source, "price_basis": basis, "basis_label": label,
        "date": last, "price": price, "unit": series[-1]["unit"] if series else None,
        "week_change_pct": week_pct, "direction": _direction(week_pct),
        "month_change_pct": month_pct, "month_from": series[0]["date"] if series else None,
        # 약 4주 + 그날 비(수산물만) · 공휴일 · 행사 (대시보드 그래프 · 재료 페이지 시세판에 씀)
        "history": _with_context(series, rain=cfg["group"] == "수산물"),
        "forecast": extra_forecast(item_name, series),
        "grade_table": _grade_table(item_name) if item_name in EKAPE_LINKS else None,   # 재료 페이지 참고 표
        "foodspring_url": foodspring_url(item_name),
    }


def extra_overview():
    """육류 · 수산물 전체 요약 (등급 표는 한우 · 돼지 3개만 있고 몇 줄이라 같이 보냄 → 재료 페이지에서 씀)."""
    return [extra_trend(name) for name in EXTRA_ITEMS]


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


# 과거 자료로 채점해 정한 계수 (salpi_agent/backtest.py 로 다시 잴 수 있음, 2026-11-12)
#   - '최근 2주 흐름'(오르면 더 오른다)은 뺌: 농산물 2021~2026 채점에서 정반대로 맞힌 비율 40%, '그대로'라고 한 것보다 오차가 큼
#   - 대신 '평균과의 차이'(평소보다 비싸면 내려오고 싸면 올라옴): 고를 때 안 쓴 2025~26 에서 정반대 41.5% → 26.1%
FORMULA_VERSION = "2026-11-12"   # 예측 공식 버전: 계수를 바꾸면 날짜를 바꿈 → forecast_log 에서 버전별로 따로 채점
VEG_REVERSION = (0.3, 15)     # 농산물: 4주 평균과의 차이 × −0.3, 최대 ±15%
VEG_VOLUME = (-0.1, 6)        # 농산물: 반입량 변화율 × −0.1, 최대 ±6% (예전 −0.25 는 채점에서 더 나빴음)
FRUIT_REVERSION = (0.2, 15)   # 과일: 4주 평균과의 차이 × −0.2 (2025~26 정반대 27.7% → 20.1%)
FRUIT_VOLUME = (-0.05, 6)     # 과일: 반입량 × −0.05. 대구 날씨는 과일 채점에서 더 나빠져 안 씀
EXTRA_REVERSION = (0.2, 4)    # 수산물 · 육류: 한 달 평균과의 차이 × −0.2, 최대 ±4% (값이 잘 안 움직여 약하게)


def reversion_factor(prices, k, cap, unit="kg", period="4주"):
    """평균과의 차이: 지금 값이 최근 평균보다 비싸면 내려오고, 싸면 올라오는 경향."""
    prices = [p for p in prices if p]
    if len(prices) < 5:
        return None
    avg = statistics.mean(prices)
    gap = _pct(prices[-1], avg)
    if gap is None:
        return None
    return {"factor": f"{period} 평균과의 차이", "effect_pct": round(_clip(-k * gap, -cap, cap), 1),
            "detail": f"지금 값이 최근 {period} 평균({round(avg):,}원/{unit})보다 {gap:+.1f}%"}


def volume_factor(vols, k=VEG_VOLUME[0], cap=VEG_VOLUME[1]):
    """반입량: 최근 3거래일 평균 vs 그 전 10거래일 평균. 시장에 들어오는 양이 줄면 오르고 늘면 내림."""
    if len(vols) < 8:
        return None
    v_pct = _pct(statistics.mean(vols[-3:]), statistics.mean(vols[-13:-3]))
    if v_pct is None:
        return None
    return {"factor": "도매시장 반입량", "effect_pct": round(_clip(k * v_pct, -cap, cap), 1),
            "detail": f"최근 3거래일 반입량이 그 전 평균보다 {v_pct:+.0f}%"}


def weather_effect(item_name, rain_total_mm, freezing_days, hot_days):
    """대구 지난 7일 날씨 → (영향 %, 이유 문구들)."""
    effect, notes = 0.0, []
    if rain_total_mm >= 30:
        effect += 3 if item_name in LEAFY else 1.5
        notes.append(f"비 {rain_total_mm}mm")
    if freezing_days and item_name in COLD_SENSITIVE:
        effect += 2
        notes.append(f"영하 3도 이하 {freezing_days}일")
    if hot_days >= 3:
        effect += 2
        notes.append(f"33도 이상 {hot_days}일")
    return effect, notes


def forecast_item(item_name):
    """다음 7일 도매가 방향을 이유(요인별 %)와 함께 추정."""
    if item_name not in ITEMS:
        return {"error": f"'{item_name}'은(는) 아직 지원하지 않아요. 지원 품목: {', '.join(ITEMS)}"}
    series = wholesale_series(item_name, 28)
    factors = []

    # 1) 4주 평균과의 차이 (평소보다 비싸면 내려오고 싸면 올라옴 — 채점으로 '최근 2주 흐름' 대신 넣음)
    fruit = kind_of(item_name) == "과일"   # 과일은 채점으로 따로 정한 계수
    f = reversion_factor([p["kg_price"] for p in series], *(FRUIT_REVERSION if fruit else VEG_REVERSION), unit="kg", period="4주")
    if f:
        factors.append(f)

    # 2) 반입량: 시장에 들어오는 양이 줄면 오르고, 늘면 내린다
    f = volume_factor([p["volume_kg"] for p in series], *(FRUIT_VOLUME if fruit else VEG_VOLUME))
    if f:
        factors.append(f)

    # 3) 대구 날씨 (지난 7일, 야채만 · 주산지 날씨는 아직 반영 못 함 · 과거 채점에도 같은 규칙)
    w = weather_summary(7) if not fruit else {}
    if w.get("days"):
        effect, notes = weather_effect(item_name, w["rain_total_mm"], w["freezing_days"], w["hot_days"])
        factors.append({"factor": "날씨(대구, 지난 7일)", "effect_pct": effect,
                        "detail": ", ".join(notes) if notes else
                        f"비 {w['rain_total_mm']}mm, 최저 {w['min_temp']}도 · 최고 {w['max_temp']}도로 큰 영향 없음"})

    # 4) 다가오는 공휴일 (도매시장 휴장 전 수요가 몰림)
    hol = holidays(7)
    if hol:
        big = any(n in h["name"] for h in hol for n in ("설", "추석"))
        factors.append({"factor": "다가오는 공휴일", "effect_pct": 4.0 if big else 2.0,
                        "detail": ", ".join(f"{h['date'][4:6]}/{h['date'][6:]} {h['name']}" for h in hol)})
    else:
        factors.append({"factor": "다가오는 공휴일", "effect_pct": 0.0, "detail": "7일 안에 공휴일 없음"})

    # 5) 대구 행사 (외식 수요 ↑ → 가격 영향은 작게)
    ev = daegu_events(7)
    factors.append({"factor": "대구 행사·축제(7일 안)", "effect_pct": 1.0 if len(ev) >= 5 else 0.0,
                    "detail": ", ".join(e["title"] for e in ev) if ev else "7일 안에 대구 행사 축제 없음"})

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
        "method": "규칙 기반 추정(4주 평균과의 차이 · 반입량 · 날씨 · 공휴일 · 행사, 계수는 2021~2026 채점으로 정함)."
                  " 주산지 날씨와 수입량은 아직 반영하지 않음",
    }


# ---------------------------------------------------------------
# 육류 · 수산물 다음 7일 방향 추정
# 경매 자료(반입량)가 없어서 농산물과 이유가 조금 다름:
#   한 달 평균과의 차이 · 명절 · 대구 행사
#   '최근 2주 흐름' · '김장철'은 2020~2025 채점에서 오히려 덜 맞아서 뺌. 산지 조업 · 수입량은 아직 반영 못 함
# ---------------------------------------------------------------

HOLIDAY_DEMAND = {"한우 등심", "한우 양지", "수입 소고기 갈비살", "돼지고기 앞다리",
                  "돼지고기 삼겹살", "계란", "갈치", "명태", "새우"}   # 명절 차례 · 선물 · 전 부치기 수요


def extra_forecast(item_name, series=None):
    """육류 · 수산물: 다음 7일 가격 방향을 이유(요인별 %)와 함께 추정 (농산물 forecast_item 과 같은 모양)."""
    if item_name not in EXTRA_ITEMS:
        return {"error": f"'{item_name}'은(는) 아직 지원하지 않아요"}
    series = series if series is not None else extra_series(item_name)
    if len(series) < 5:
        return {"error": "조사한 날이 적어 예측할 수 없어요"}
    prices = [p["price"] for p in series]
    last = series[-1]
    factors = []

    # 1) 한 달 평균과의 차이: 평균보다 비싸면 내려오고, 싸면 올라오는 경향 (채점으로 정한 계수, EXTRA_REVERSION)
    f = reversion_factor(prices, *EXTRA_REVERSION, unit=last["unit"], period="한 달")
    if f:
        factors.append(f)

    # 협신식품 경락가 흐름 · 경매 물량은 넣지 않음: 2021~2026 주 단위 채점에서 어떤 세기 · 방향으로 넣어도 더 나빠짐
    #   (2025~26 평균 오차: 평균과의 차이만 2.46%p · 둘 다 넣으면 3.20%p, "그대로" 2.58%p — backtest.py)
    #   경락가는 재료 페이지 등급표에 참고로만 보여 줌

    # 3) 다가오는 공휴일: 설 · 추석이면 고기 · 차례 생선 수요가 몰림
    hol = holidays(7)
    big = any(n in h["name"] for h in hol for n in ("설", "추석"))
    effect = (4.0 if big else 1.0) if hol and item_name in HOLIDAY_DEMAND else 0.0
    factors.append({"factor": "다가오는 공휴일", "effect_pct": effect,
                    "detail": ", ".join(f"{h['date'][4:6]}/{h['date'][6:]} {h['name']}" for h in hol) if hol
                    else "7일 안에 공휴일 없음"})

    # 5) 대구 행사 (외식 수요 ↑, 고기만 작게)
    ev = daegu_events(7)
    meat = EXTRA_ITEMS[item_name]["group"] == "육류"
    factors.append({"factor": "대구 행사·축제(7일 안)", "effect_pct": 1.0 if meat and len(ev) >= 5 else 0.0,
                    "detail": ", ".join(e["title"] for e in ev) if ev else "7일 안에 대구 행사 축제 없음"})

    total = round(sum(f["effect_pct"] for f in factors), 1)
    daily = [_pct(b, a) for a, b in zip(prices, prices[1:]) if a]
    spread = 2 + (_clip(statistics.pstdev(daily) * 1.5, 0, 8) if len(daily) >= 5 else 5)
    if total >= 2:
        direction, tip = "오를 가능성이 있어요", "필요한 양은 미리 사 두는 편이 나아요"
    elif total <= -2:
        direction, tip = "내릴 가능성이 있어요", "급하지 않으면 며칠 기다려 보세요"
    else:
        direction, tip = "비슷할 가능성이 커요", "평소대로 사면 돼요"
    return {
        "item": item_name, "horizon": "다음 7일", "base_date": last["date"], "unit": last["unit"],
        "base_price": last["price"], "expected_change_pct": total,
        "range_pct": [round(total - spread, 1), round(total + spread, 1)],
        "expected_price_range": [round(last["price"] * (1 + (total - spread) / 100)),
                                 round(last["price"] * (1 + (total + spread) / 100))],
        "direction": direction, "suggestion": tip,
        "confidence": "낮음" if len(series) < 10 or spread >= 8 else "보통",
        "factors": factors,
        "method": "규칙 기반 추정(한 달 평균과의 차이 · 명절 · 행사). 평균과의 차이 계수는 2020~2026 채점으로 정함."
                  " 명절 · 행사 계수는 아직 채점 전. 경락가 이유는 채점에서 더 나빠져 넣지 않음",
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
