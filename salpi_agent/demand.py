"""판매량 예측: 우리 가게 판매 기록(Supabase)으로 내일 메뉴별 그릇 수 → 재료 필요량 → 발주량.

규칙 기반 (LLM은 숫자를 만들지 않는다)
- 기본 수준: 최근 4주 판매량에서 요일 차이를 뺀 평균
- 요일: 지난 기록 전체에서 그 요일이 평소보다 얼마나 많이 · 적게 팔렸는지
- 최근 흐름: 최근 2주가 그 전 2주보다 늘었는지 줄었는지 (꺾이기 쉬워 절반만 반영)
- 공휴일: 지난 공휴일에 평소보다 얼마나 팔렸는지
- 범위: 최근 4주 동안 위 방식이 실제와 얼마나 어긋났는지로 정함 (10번 중 8번 들어오는 폭)
"""

import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import analysis
import supabase_db as db
from data_sources import ITEMS, holidays_between

WEEKDAYS = "월화수목금토일"
KST = timezone(timedelta(hours=9))   # Vercel 서버는 세계 표준시라 한국 날짜로 맞춤
SAFETY = 0.10   # 발주할 때 예측보다 10% 더 (모자라면 장사를 못 하니까)


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def _holidays(start, end):
    """공휴일 날짜 모음: Supabase special_days + 천문연구원 API (둘 중 하나가 비어도 동작)."""
    days = {r["locdate"] for r in db.select("special_days", is_holiday="is.true", select="locdate",
                                            locdate=f"gte.{start}") if r["locdate"] <= str(end)}
    try:
        days |= {f"{h['date'][:4]}-{h['date'][4:6]}-{h['date'][6:]}" for h in holidays_between(start, end)}
    except Exception:
        pass   # API 키가 없거나 장애면 Supabase 값만 사용
    return days


def _load(store_id):
    store = db.select("stores", id=f"eq.{store_id}")
    if not store:
        raise ValueError("가게 정보를 찾지 못했어요")
    menus = db.select("menus", store_id=f"eq.{store_id}", is_active="is.true", select="id,name,price", order="id")
    sales = db.select("sales_daily", store_id=f"eq.{store_id}", select="menu_id,sale_date,qty", order="sale_date")
    recipes = db.select("recipe_items", menu_id=f"in.({','.join(str(m['id']) for m in menus) or 0})",
                        select="menu_id,qty_per_serving,loss_rate,items(id,name,base_unit)")
    stock = db.select("inventory", store_id=f"eq.{store_id}", select="item_id,on_hand_qty,next_delivery_date,updated_at")
    return store[0], menus, sales, recipes, stock


class _MenuModel:
    """메뉴 하나의 하루 판매량 예측기 (홀 + 배달 합계)."""

    def __init__(self, daily, holidays):
        self.daily = daily                                    # {date: qty}
        normal = {d: q for d, q in daily.items() if str(d) not in holidays}
        mean_all = statistics.mean(normal.values())
        by_wd = defaultdict(list)
        for d, q in normal.items():
            by_wd[d.weekday()].append(q)
        self.wd = {w: statistics.mean(v) / mean_all if len(v) >= 3 else 1.0 for w, v in by_wd.items()}

        last = max(daily)
        def flat(a, b):   # a~b일 전 사이, 요일 차이를 뺀 판매량들
            return [q / self.wd.get(d.weekday(), 1) for d, q in normal.items() if last - timedelta(b) < d <= last - timedelta(a)]
        recent, before = flat(0, 14), flat(14, 28)
        self.level = statistics.mean(recent + before) if recent + before else mean_all
        self.trend = _clip((statistics.mean(recent) / statistics.mean(before) - 1) * 0.5, -0.10, 0.10) \
            if len(recent) >= 5 and len(before) >= 5 else 0.0

        hol = [q / (mean_all * self.wd.get(d.weekday(), 1)) for d, q in daily.items() if str(d) in holidays]
        self.holiday = _clip(statistics.mean(hol), 0.3, 1.5) if hol else 0.7   # 기록이 없으면 평소의 70%로 가정

        # 범위: 최근 4주 동안 '기본 수준 × 요일 × 공휴일'이 실제와 어긋난 정도
        errs = [q / self._base(d, holidays) - 1 for d, q in daily.items() if d > last - timedelta(28)]
        self.spread = _clip(1.28 * statistics.pstdev(errs), 0.05, 0.40) if len(errs) >= 8 else 0.20

    def _base(self, d, holidays):
        return self.level * self.wd.get(d.weekday(), 1) * (self.holiday if str(d) in holidays else 1)

    def predict(self, d, holidays):
        mid = self._base(d, holidays) * (1 + self.trend)
        factors = {f"{WEEKDAYS[d.weekday()]}요일": round(self.wd.get(d.weekday(), 1) - 1, 3),
                   "최근 2주 흐름": round(self.trend, 3)}
        if str(d) in holidays:
            factors["공휴일"] = round(self.holiday - 1, 3)
        return round(mid), round(mid * (1 - self.spread)), round(mid * (1 + self.spread)), factors


def forecast(store_id=db.DEMO_STORE, target=None, price_outlook=None, save=True):
    """target(기본 내일) 메뉴별 예상 그릇 수, 재료 필요량, 다음 입고까지 발주 추천.

    price_outlook: {재료 이름: 다음 7일 예상 변화율(%)} — 대시보드 시세 예측. 발주 판단(지금 사기 · 나눠 사기)에 씀.
    save: 결과를 Supabase menu_forecasts · order_recommendations 에 저장.
    """
    today = datetime.now(KST).date()
    target = target or today + timedelta(1)
    store, menus, sales, recipes, stock = _load(store_id)
    if not sales:
        return {"error": "판매 기록이 없어요. 판매량을 먼저 넣어 주세요."}

    open_days = set(store.get("open_days") or WEEKDAYS[:6])
    next_delivery = min((date.fromisoformat(s["next_delivery_date"]) for s in stock if s.get("next_delivery_date")), default=None)
    horizon_end = max(target, (next_delivery - timedelta(1)) if next_delivery and next_delivery > today else target)
    first_sale = date.fromisoformat(sales[0]["sale_date"])
    holidays = _holidays(first_sale, horizon_end)

    per_menu = defaultdict(lambda: defaultdict(int))
    for s in sales:
        per_menu[s["menu_id"]][date.fromisoformat(s["sale_date"])] += s["qty"]
    last_sale = max(d for v in per_menu.values() for d in v)

    def is_open(d):
        return WEEKDAYS[d.weekday()] in open_days

    # 1) 메뉴별 예상 그릇 수 (target 하루 + 다음 입고 전날까지 매일)
    result_menus, need_target, need_period, models = [], defaultdict(float), defaultdict(float), {}
    for m in menus:
        if not per_menu.get(m["id"]):
            continue
        models[m["id"]] = model = _MenuModel(per_menu[m["id"]], holidays)
        mid, lo, hi, factors = model.predict(target, holidays) if is_open(target) else (0, 0, 0, {"휴무일": -1})
        recent = [{"date": str(d), "qty": q} for d, q in sorted(per_menu[m["id"]].items())[-14:]]
        result_menus.append({"menu_id": m["id"], "menu": m["name"], "price": m["price"], "predicted": mid,
                             "range": [lo, hi], "factors": factors, "recent": recent})

    rec_by_menu = defaultdict(list)
    for r in recipes:
        rec_by_menu[r["menu_id"]].append(r)
    d = today
    while d <= horizon_end:
        if is_open(d):
            for mid_, model in models.items():
                qty = model.predict(d, holidays)[0]
                for r in rec_by_menu[mid_]:
                    amount = qty * float(r["qty_per_serving"]) / (1 - float(r["loss_rate"]))
                    need_period[r["items"]["id"]] += amount
                    if d == target:
                        need_target[r["items"]["id"]] += amount
        d += timedelta(1)

    # 2) 재료별 내일 필요량 · 재고 · 발주 추천
    items = {r["items"]["id"]: r["items"] for r in recipes}
    on_hand = {s["item_id"]: float(s["on_hand_qty"]) for s in stock}
    if price_outlook is None:   # 대시보드 시세 예측이 없을 때: 레시피에 든 야채만 직접 계산
        price_outlook = {}
        for it in items.values():
            if it["name"] in ITEMS:
                try:
                    price_outlook[it["name"]] = analysis.forecast_item(it["name"])["expected_change_pct"]
                except Exception:
                    pass
    result_items = []
    for item_id, it in items.items():
        unit = it["base_unit"]
        step = 1 if unit == "모" else 0.1
        need = need_period[item_id] * (1 + SAFETY)
        short = need - on_hand.get(item_id, 0)
        order = math.ceil(short / step - 1e-9) * step if short > 0 else 0
        change = price_outlook.get(it["name"])
        if order <= 0:
            decision, why = "기다리기", "재고로 다음 입고까지 충분해요"
        elif change is not None and change <= -2:
            decision, why = "나눠 사기", f"모자란 만큼만 지금 사고, 시세가 내릴 수 있어(다음 7일 {change:+.0f}%) 나머지는 기다려요"
        elif change is not None and change >= 2:
            decision, why = "지금 사기", f"모자라고 시세도 오를 수 있어요(다음 7일 {change:+.0f}%)"
        else:
            decision, why = "지금 사기", "다음 입고 전에 모자라요"
        result_items.append({
            "item_id": item_id, "item": it["name"], "unit": unit,
            "need_target": round(need_target[item_id], 2), "need_until_delivery": round(need_period[item_id], 2),
            "on_hand": on_hand.get(item_id, 0), "order_qty": round(order, 1), "decision": decision, "reason": why,
            "price_change_pct": change,
        })
    result_items.sort(key=lambda x: (x["decision"] == "기다리기", -x["order_qty"]))

    out = {
        "store": {"id": store["id"], "name": store["name"], "district": store.get("district"), "is_demo": store.get("is_demo")},
        "target_date": str(target), "target_weekday": WEEKDAYS[target.weekday()], "is_open": is_open(target),
        "is_holiday": str(target) in holidays, "last_sales_date": str(last_sale),
        "next_delivery_date": str(next_delivery) if next_delivery else None,
        "period": [str(today), str(horizon_end)],
        "total_predicted": sum(m["predicted"] for m in result_menus),
        "menus": result_menus, "items": result_items,
        "method": "규칙 기반(요일 · 최근 2주 흐름 · 공휴일). 범위는 10번 중 8번 들어오는 폭. 발주는 예측보다 10% 여유",
    }
    if save:
        _save(store["id"], target, out)
    return out


def _save(store_id, target, out):
    db.upsert("menu_forecasts", [{
        "store_id": store_id, "menu_id": m["menu_id"], "target_date": str(target), "predicted_qty": m["predicted"],
        "lower_qty": m["range"][0], "upper_qty": m["range"][1], "contributions": m["factors"], "model_version": "rule-v1",
    } for m in out["menus"]], "store_id,menu_id,target_date")
    db.upsert("order_recommendations", [{
        "store_id": store_id, "item_id": i["item_id"], "target_date": str(target), "recommended_qty": i["order_qty"],
        "decision": i["decision"], "reason": {"text": i["reason"], "need_until_delivery": i["need_until_delivery"],
                                              "on_hand": i["on_hand"], "price_change_pct": i["price_change_pct"]},
    } for i in out["items"]], "store_id,item_id,target_date")
