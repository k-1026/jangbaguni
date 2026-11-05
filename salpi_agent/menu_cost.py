"""메뉴 1인분 원가 · 원가율 계산 ("이 가격에 팔아도 남아?").

채소는 오늘 대구 도매 경락가(kg당)를 쓰고 (실제 구매가는 이보다 높을 수 있음),
시세 API가 없는 재료(고기 · 두부 · 양념 등)는 아래 참고 단가를 쓴다.
참고 단가는 시연용 가정값이라 사장님 영수증 값으로 바꿔야 정확해진다.
"""

from analysis import item_trend
from data_sources import ITEMS

# 시세 API가 없는 재료: (단위, 단위당 원) — 시연용 가정값 (supabase/seed.sql 영수증 값 기준)
REFERENCE_PRICES = {
    "돼지고기 앞다리": ("kg", 12800), "돼지고기 삼겹살": ("kg", 22000), "닭고기": ("kg", 6500),
    "소고기 국거리": ("kg", 30000), "오징어": ("kg", 15000), "두부": ("모", 1200),
    "배추김치": ("kg", 3800), "된장": ("kg", 7000), "고추장": ("kg", 7000), "고춧가루": ("kg", 14000),
    "간장": ("kg", 4000), "설탕": ("kg", 2000), "깐마늘": ("kg", 11000), "쌀": ("kg", 2750),
    "떡볶이떡": ("kg", 4000), "어묵": ("kg", 6000), "계란": ("개", 250), "콩나물": ("kg", 3000),
    "참기름": ("kg", 20000), "햄": ("kg", 9000), "라면사리": ("개", 400),
}

# 사장님이 흔히 부르는 이름 → (품목, 환산 배율). 밥 200g ≈ 쌀 90g
ALIASES = {
    "김치": ("배추김치", 1), "포기김치": ("배추김치", 1), "밥": ("쌀", 0.45), "공기밥": ("쌀", 0.45),
    "돼지고기": ("돼지고기 앞다리", 1), "앞다리": ("돼지고기 앞다리", 1), "삼겹살": ("돼지고기 삼겹살", 1),
    "닭": ("닭고기", 1), "마늘": ("깐마늘", 1), "파": ("대파", 1), "호박": ("애호박", 1), "고추": ("청양고추", 1),
    "떡": ("떡볶이떡", 1), "달걀": ("계란", 1), "스팸": ("햄", 1), "라면": ("라면사리", 1),
}

# 표준 레시피 1인분: [(재료, 양, 단위)] — kg 재료는 g로 적음
STANDARD_RECIPES = {
    "김치찌개": [("배추김치", 150, "g"), ("돼지고기 앞다리", 20, "g"), ("두부", 0.25, "모"), ("양파", 8, "g"),
             ("대파", 10, "g"), ("고춧가루", 5, "g"), ("쌀", 120, "g")],
    "제육볶음": [("돼지고기 앞다리", 120, "g"), ("양파", 80, "g"), ("대파", 20, "g"), ("청양고추", 5, "g"),
             ("고추장", 30, "g"), ("고춧가루", 8, "g"), ("깐마늘", 10, "g"), ("설탕", 10, "g"), ("쌀", 120, "g")],
    "된장찌개": [("된장", 40, "g"), ("두부", 0.25, "모"), ("애호박", 50, "g"), ("감자", 50, "g"), ("양파", 30, "g"),
             ("청양고추", 3, "g"), ("대파", 10, "g"), ("쌀", 120, "g")],
    "떡볶이": [("떡볶이떡", 200, "g"), ("어묵", 60, "g"), ("양배추", 40, "g"), ("대파", 20, "g"),
            ("고추장", 30, "g"), ("고춧가루", 5, "g"), ("설탕", 15, "g")],
    "비빔밥": [("쌀", 150, "g"), ("콩나물", 40, "g"), ("시금치", 30, "g"), ("당근", 20, "g"), ("애호박", 30, "g"),
            ("계란", 1, "개"), ("고추장", 20, "g"), ("참기름", 5, "g")],
    "부대찌개": [("햄", 80, "g"), ("배추김치", 60, "g"), ("두부", 0.2, "모"), ("양파", 30, "g"), ("대파", 20, "g"),
             ("라면사리", 0.5, "개"), ("고춧가루", 5, "g"), ("쌀", 120, "g")],
    "오징어볶음": [("오징어", 120, "g"), ("양파", 60, "g"), ("양배추", 40, "g"), ("당근", 15, "g"), ("대파", 15, "g"),
              ("청양고추", 5, "g"), ("고추장", 30, "g"), ("고춧가루", 8, "g"), ("쌀", 120, "g")],
}


def _unit_price(name):
    """(단위, 단위당 원, 출처) 또는 None."""
    if name in ITEMS:
        t = item_trend(name)
        if t["wholesale"]["kg_price"]:
            return "kg", t["wholesale"]["kg_price"], f"오늘 시세(대구 도매 경락, {t['wholesale']['date']})"
    if name in REFERENCE_PRICES:
        unit, price = REFERENCE_PRICES[name]
        return unit, price, "참고 단가(가정값)"
    return None


def menu_cost(menu, sale_price, ingredients=None):
    """menu: 메뉴 이름, sale_price: 판매가(원),
    ingredients: [{"name", "amount", "unit"(g·모·개)}] — 없으면 표준 레시피 사용."""
    if ingredients:
        recipe = []
        for i in ingredients:
            name, rate = ALIASES.get(i["name"], (i["name"], 1))
            recipe.append((name, float(i["amount"]) * rate, i.get("unit", "g")))
        recipe_source = "사장님이 알려 준 재료"
    elif menu in STANDARD_RECIPES:
        recipe = STANDARD_RECIPES[menu]
        recipe_source = "살피 표준 레시피(1인분)"
    else:
        return {"need_ingredients": True, "menu": menu,
                "message": "표준 레시피가 없는 메뉴예요. 1인분에 들어가는 재료와 양을 알려 주세요.",
                "standard_menus": list(STANDARD_RECIPES)}

    lines, unknown, total = [], [], 0.0
    for name, amount, unit in recipe:
        p = _unit_price(name)
        if not p:
            unknown.append(name)
            continue
        p_unit, price, source = p
        qty = amount / 1000 if unit == "g" and p_unit == "kg" else amount
        cost = qty * price
        total += cost
        lines.append({"name": name, "amount": f"{amount:g}{unit}", "unit_price": f"{price:,.0f}원/{p_unit}",
                      "cost": round(cost), "source": source})

    ratio = total / sale_price * 100 if sale_price else None
    if ratio is None:
        verdict = "판매가를 알려 주시면 남는지 계산해 드려요"
    elif ratio <= 30:
        verdict = "충분히 남아요"
    elif ratio <= 38:
        verdict = "남지만 빠듯해요"
    else:
        verdict = "재료비 비중이 높아요. 가격이나 재료를 다시 보는 게 좋아요"
    lines.sort(key=lambda x: -x["cost"])
    return {
        "menu": menu, "sale_price": sale_price, "recipe_source": recipe_source,
        "cost_per_serving": round(total), "cost_ratio_pct": round(ratio, 1) if ratio else None,
        "margin_after_ingredients": round(sale_price - total) if sale_price else None,
        "verdict": verdict, "biggest_costs": lines[:3], "breakdown": lines, "unknown_price_items": unknown,
        "note": "식재료비만 본 값이에요(인건비 · 임대료 · 가스비 제외). 참고 단가는 영수증 값으로 바꾸면 정확해져요.",
        "price_for_30pct": round(total / 0.30, -2),   # 재료비 30%가 되는 판매가
    }
