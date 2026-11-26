"""나의 가게 메뉴 고치기 · 추가 · 판매 중지 (메뉴별 원가율 칸의 [수정] · [+ 메뉴 추가]).

- 메뉴는 지우지 않고 '판매 중지'(is_active=false)만 한다. 메뉴를 지우면 판매 기록(sales_daily)까지
  함께 지워져 내일 준비(수요 예측)가 망가지기 때문.
- 재료는 품목 목록(items)에서만 고른다. 아무 이름이나 받으면 가격을 찾지 못해 원가율을 계산할 수 없음.
- 손질 손실률은 화면에 보이지 않는다. 고칠 때는 원래 값을 그대로 두고, 새 재료는 0으로 넣는다.
"""

from store import inventory, menu_cost
from sources import supabase_db as db

MAX_NAME = 30


def editor_data(store_id):
    """입력 창에 필요한 것: 재료 목록(+ 최근 영수증 단가) · 메뉴(판매 중 · 중지) · 자주 쓰는 메뉴 틀."""
    items = inventory.shared_items(db.select("items", select="id,name,category,base_unit,note", order="category,name"))
    prices = {p["item_id"]: float(p["unit_price_base"]) for p in
              db.select("v_latest_purchase_price", store_id=f"eq.{store_id}", select="item_id,unit_price_base")
              if p["unit_price_base"] is not None}
    menus = db.select("menus", store_id=f"eq.{store_id}", select="id,name,price,is_active", order="id")
    recipes = db.select("recipe_items", menu_id=f"in.({','.join(str(m['id']) for m in menus) or 0})",
                        select="menu_id,item_id,qty_per_serving,loss_rate")
    by_name = {i["name"]: i for i in items}
    templates = []
    for name, rows in menu_cost.STANDARD_RECIPES.items():   # 표준 레시피(g · 모 · 개) → 품목 기준 단위(kg · 모 · 개)
        recipe = [{"item_id": by_name[n]["id"], "qty": a / 1000 if u == "g" and by_name[n]["base_unit"] == "kg" else a}
                  for n, a, u in rows if n in by_name]
        if recipe:
            templates.append({"name": name, "recipe": recipe})
    return {
        "items": [{"id": i["id"], "name": i["name"], "category": i["category"], "unit": i["base_unit"],
                   "price": prices.get(i["id"])} for i in items],
        "menus": [{"id": m["id"], "name": m["name"], "price": m["price"], "active": m["is_active"],
                   "recipe": [{"item_id": r["item_id"], "qty": float(r["qty_per_serving"]), "loss": float(r["loss_rate"])}
                              for r in recipes if r["menu_id"] == m["id"]]} for m in menus],
        "templates": templates,
    }


def _check(body, item_ids):
    name = str(body.get("name") or "").strip()
    if not name:
        raise ValueError("메뉴 이름을 적어 주세요")
    if len(name) > MAX_NAME:
        raise ValueError(f"메뉴 이름은 {MAX_NAME}자까지 적을 수 있어요")
    try:
        price = int(body.get("price"))
    except (TypeError, ValueError):
        raise ValueError("판매가를 숫자로 적어 주세요") from None
    if not 100 <= price <= 1_000_000:
        raise ValueError("판매가는 100원 ~ 100만 원 사이로 적어 주세요")
    recipe, seen = [], set()
    for r in body.get("recipe") or []:
        try:
            item_id, qty = int(r.get("item_id")), float(r.get("qty"))
        except (TypeError, ValueError):
            raise ValueError("재료와 양을 다시 확인해 주세요") from None
        if item_id not in item_ids:
            raise ValueError("목록에 없는 재료가 있어요")
        if item_id in seen:
            raise ValueError("같은 재료가 두 번 들어 있어요. 한 줄로 합쳐 주세요")
        if not 0 < qty < 100:
            raise ValueError("재료 양은 0보다 크게 적어 주세요")
        seen.add(item_id)
        recipe.append({"item_id": item_id, "qty": qty})
    if not recipe:
        raise ValueError("재료를 한 가지 이상 넣어 주세요")
    return name, price, recipe


def save(store_id, menu_id, body):
    """menu_id 가 없으면 새 메뉴, 있으면 고치기. 같은 이름의 판매 중지 메뉴가 있으면 그 메뉴를 다시 살림."""
    item_ids = {i["id"] for i in db.select("items", select="id")}
    name, price, recipe = _check(body, item_ids)
    same = db.select("menus", store_id=f"eq.{store_id}", name=f"eq.{name}", select="id,is_active")
    other = [m for m in same if m["id"] != menu_id]
    if menu_id is None:
        if other and other[0]["is_active"]:
            raise ValueError(f"'{name}' 메뉴가 이미 있어요. 그 메뉴의 [수정]을 눌러 고쳐 주세요")
        if other:   # 판매 중지했던 같은 이름 메뉴 → 다시 판매 (판매 기록도 이어짐)
            menu_id = other[0]["id"]
        else:
            menu_id = db.insert("menus", [{"store_id": store_id, "name": name, "price": price}])[0]["id"]
    elif other:
        raise ValueError(f"'{name}' 이름을 쓰는 다른 메뉴가 있어요. 다른 이름으로 적어 주세요")
    if not db.update("menus", {"name": name, "price": price, "is_active": True}, id=f"eq.{menu_id}", store_id=f"eq.{store_id}"):
        raise ValueError("메뉴를 찾지 못했어요")
    # 재료: 원래 있던 재료는 손질 손실률을 그대로 두고 양만 바꿈, 빠진 재료는 지움
    loss = {r["item_id"]: r["loss_rate"] for r in db.select("recipe_items", menu_id=f"eq.{menu_id}", select="item_id,loss_rate")}
    db.upsert("recipe_items", [{"menu_id": menu_id, "item_id": r["item_id"], "qty_per_serving": round(r["qty"], 4),
                                "loss_rate": loss.get(r["item_id"], 0)} for r in recipe], "menu_id,item_id")
    gone = set(loss) - {r["item_id"] for r in recipe}
    if gone:
        db.delete("recipe_items", menu_id=f"eq.{menu_id}", item_id=f"in.({','.join(map(str, gone))})")
    return {"menu_id": menu_id, "name": name}


def stop(store_id, menu_id):
    """판매 중지: 원가율 · 내일 준비 목록에서 빠지고, 판매 기록과 레시피는 남는다."""
    rows = db.update("menus", {"is_active": False}, id=f"eq.{menu_id}", store_id=f"eq.{store_id}")
    if not rows:
        raise ValueError("메뉴를 찾지 못했어요")
    return {"menu_id": menu_id, "name": rows[0]["name"]}
