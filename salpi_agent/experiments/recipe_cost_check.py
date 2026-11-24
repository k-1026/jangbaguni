"""레시피 원가율 검증: 시연 가게 메뉴 5개의 1인분 재료(g) × 최근 영수증 단가 → 원가율을 업계 범위 · 레시피 양과 비교.

실행:  .venv\\Scripts\\python -m experiments.recipe_cost_check        (.env 의 SUPABASE_* 필요, 10초)

- 레시피: Supabase recipe_items (demand/dummy_store.py RECIPES 와 같음) · 단가: 우리 가게 최근 영수증 (원가율 화면과 같은 계산)
- 비교 1 — 업계 원가율: 외식업 적정 원가율 보통 30~35% (한식은 출처에 따라 25~40%), 살피 기준 40% (자영업자 카페 답 중 가장 보수적),
  외식업 평균 식재료비 비중 40.7% (aT 외식업체 경영실태조사 2024)
- 비교 2 — 핵심 재료 양: 가정식 레시피(만개의레시피 · 마켓컬리 · 백종원)를 1인분으로 나눈 범위 (식당 공식 1인분 기준은 공개된 것이 없음)
- 무게 환산: 두부 1모 = 300g (식봄 · 영수증 '국산두부300G'), 계란 1개 = 60g, 식용유 1L = 920g, 쌀은 마른 쌀 그대로
- 결과: experiments/results/recipe_cost_check.json
"""
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sources import supabase_db as db   # noqa: E402
from store import receipts   # noqa: E402

OUT = Path(__file__).resolve().parent / "results" / "recipe_cost_check.json"
GRAM = {"kg": 1000, "모": 300, "개": 60, "L": 920}
INDUSTRY = {"low": 30, "high": 35, "hansik_low": 25, "hansik_high": 40, "salpi_limit": receipts.TARGET_RATIO, "avg_food_cost": 40.7}

# 핵심 재료 1인분 양 (g) — 가정식 레시피를 1인분으로 나눈 값. (메뉴, 재료): (적게, 많게, 근거)
REFERENCE = {
    ("김치찌개", "돼지고기 앞다리"): (50, 130, "볶음김치 100g + 돼지고기 50g(1인 기준 레시피) ~ 돼지고기 130g : 김치 390g(백종원 1:3 비율 예)"),
    ("김치찌개", "배추김치"): (100, 200, "볶음김치 100g(1인 기준) ~ 김치 1/4포기 400g을 2인분으로"),
    ("제육볶음", "돼지고기 앞다리"): (150, 200, "앞다리살 400~500g을 2~3인분으로 (만개의레시피)"),
    ("순두부찌개", "돼지고기 앞다리"): (27, 50, "다진 돼지고기 80g 3인분(백종원) ~ 100g 2인분(만개의레시피)"),
}
# 1인분 그릇 무게 (식약처 식품영양성분DB를 옮긴 칼로리표) — 국물 · 물은 레시피에 없어 '건더기 무게'와만 견줌
DISH_G = {"김치찌개": "300~400g", "제육볶음": "250g", "된장찌개": "450g", "순두부찌개": "500g", "김치볶음밥": "300~350g (볶음밥)"}


def main():
    menus = db.select("menus", store_id=f"eq.{db.DEMO_STORE}", is_active="is.true", select="id,name,price", order="id")
    recipes = db.select("recipe_items", menu_id=f"in.({','.join(str(m['id']) for m in menus)})",
                        select="menu_id,item_id,qty_per_serving,loss_rate,items(name,base_unit)")
    hist = receipts._price_history(db.DEMO_STORE)
    out = []
    for m in menus:
        parts = []
        for r in (x for x in recipes if x["menu_id"] == m["id"]):
            it = r["items"]
            per = float(r["qty_per_serving"]) / (1 - float(r["loss_rate"]))   # 손질 손실 포함해 사는 양
            h = hist.get(r["item_id"]) or []
            price = h[-1][1] if h else None
            parts.append({"item": it["name"], "unit": it["base_unit"], "qty": float(r["qty_per_serving"]),
                          "grams": round(float(r["qty_per_serving"]) * GRAM.get(it["base_unit"], 1000)),
                          "unit_price": round(price) if price else None, "cost": round(per * price) if price else None,
                          "receipt_date": h[-1][0] if h else None})
        cost = sum(p["cost"] or 0 for p in parts)
        ratio = round(cost / m["price"] * 100, 1)
        solid = sum(p["grams"] for p in parts if p["item"] != "쌀")
        checks = []
        for p in parts:
            ref = REFERENCE.get((m["name"], p["item"]))
            if ref:
                lo, hi, why = ref
                checks.append({"item": p["item"], "grams": p["grams"], "ref": f"{lo}~{hi}g",
                               "verdict": "적음" if p["grams"] < lo else "많음" if p["grams"] > hi else "범위 안", "basis": why})
        band = ("업계 범위보다 낮음" if ratio < INDUSTRY["low"] else "업계 범위(30~35%)" if ratio <= INDUSTRY["high"]
                else "업계 범위보다 높음 · 살피 기준 아래" if ratio < INDUSTRY["salpi_limit"] else "살피 기준(40%) 넘음")
        out.append({"menu": m["name"], "price": m["price"], "cost": cost, "ratio_pct": ratio, "band": band,
                    "solid_grams_without_rice": solid, "dish_reference": DISH_G.get(m["name"]),
                    "parts": sorted(parts, key=lambda p: -(p["cost"] or 0)), "amount_checks": checks,
                    "missing_price": [p["item"] for p in parts if p["cost"] is None],
                    # 레시피에 없는 반찬 · 육수 · 양념을 1인분 500원 · 1,000원 더했다면 (가정 — 출처 없음, 민감도만)
                    "if_sides_500": round((cost + 500) / m["price"] * 100, 1), "if_sides_1000": round((cost + 1000) / m["price"] * 100, 1)})
    OUT.write_text(json.dumps({"industry": INDUSTRY, "menus": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    for x in out:
        print(f"{x['menu']:6} {x['price']:>6,}원  재료비 {x['cost']:>5,}원  원가율 {x['ratio_pct']:>5}%  {x['band']}  "
              f"(+500원 {x['if_sides_500']}% · +1,000원 {x['if_sides_1000']}%)  건더기 {x['solid_grams_without_rice']}g / 그릇 {x['dish_reference']}")
        print("        ", ", ".join(f"{p['item']} {p['grams']}g {p['cost']}원" for p in x["parts"]))
        for c in x["amount_checks"]:
            print(f"         양 확인: {c['item']} {c['grams']}g vs {c['ref']} → {c['verdict']}")


if __name__ == "__main__":
    main()
