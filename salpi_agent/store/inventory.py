"""재고 — 사장님이 직접 입력 · 수정 + 영수증 저장 · 고치기 · 지우기 때 자동으로 늘고 줄기 (Supabase inventory).

- listing : 재고 입력 창용. 메뉴에 들어가는 재료 + 이미 재고가 있는 재료를 이름순으로 (없으면 0) · 더 넣을 수 있는 재료(catalog)
- remove  : 직접 넣은 재료 빼기 (메뉴에 쓰는 재료는 못 뺌)
- set_qty : 사장님이 고친 남은 양을 그대로 저장 (기준 단위: kg · 모 · 개 · L)
- adjust  : 재료별로 더하고 빼기 (영수증 저장 +, 지우기 −, 고치기는 바뀐 만큼). 0 밑으로는 안 내려감
"""

from datetime import datetime, timezone

from sources import supabase_db as db


def _now():
    return datetime.now(timezone.utc).isoformat()


def _stock(store_id):
    return {r["item_id"]: r for r in db.select("inventory", store_id=f"eq.{store_id}",
                                                 select="item_id,on_hand_qty,next_delivery_date,updated_at")}


def _used(store_id):
    """지금 파는 메뉴에 들어가는 재료 id"""
    menus = [m["id"] for m in db.select("menus", store_id=f"eq.{store_id}", is_active="eq.true", select="id")]
    return {r["item_id"] for r in db.select("recipe_items", menu_id=f"in.({','.join(map(str, menus)) or 0})", select="item_id")}


def listing(store_id):
    stock, used = _stock(store_id), _used(store_id)
    ids = used | set(stock)
    items = {i["id"]: i for i in db.select("items", select="id,name,base_unit,category")}   # 표준 재료 전체 (20여 개)
    rows = [{"item_id": i, "item": items[i]["name"], "unit": items[i]["base_unit"], "category": items[i]["category"],
             "on_hand": float(stock[i]["on_hand_qty"]) if i in stock else 0.0,
             "updated_at": stock[i]["updated_at"] if i in stock else None, "in_menu": i in used}
            for i in ids if i in items]
    rows.sort(key=lambda r: (not r["in_menu"], r["item"]))
    catalog = sorted(({"item_id": i, "item": x["name"], "unit": x["base_unit"], "category": x["category"]}
                      for i, x in items.items() if i not in ids), key=lambda r: r["item"])
    nxt = min((s["next_delivery_date"] for s in stock.values() if s.get("next_delivery_date")), default=None)
    return {"items": rows, "catalog": catalog, "next_delivery_date": nxt}


def remove(store_id, item_id):
    """직접 넣은 재료를 재고 목록에서 뺌. 메뉴 재료는 메뉴에서 먼저 빼야 함"""
    if int(item_id) in _used(store_id):
        raise ValueError("메뉴에 쓰는 재료는 뺄 수 없어요")
    db.delete("inventory", store_id=f"eq.{store_id}", item_id=f"eq.{int(item_id)}")
    return listing(store_id)


def set_qty(store_id, rows):
    """rows: [{"item_id", "on_hand"}] → 그 재료들만 바꿈."""
    out = []
    for r in rows:
        try:
            q = float(r["on_hand"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("남은 양은 숫자로 넣어 주세요")
        if q < 0 or q > 100000:
            raise ValueError("남은 양은 0 이상으로 넣어 주세요")
        out.append({"store_id": store_id, "item_id": int(r["item_id"]), "on_hand_qty": round(q, 3), "updated_at": _now()})
    db.upsert("inventory", out, "store_id,item_id")
    return listing(store_id)


def adjust(store_id, delta):
    """delta: {item_id: 더할 양(빼면 음수)} → 재료별 재고를 바꿈."""
    delta = {int(k): v for k, v in delta.items() if k and v}
    if not delta:
        return
    stock = _stock(store_id)
    db.upsert("inventory", [{"store_id": store_id, "item_id": i,
                             "on_hand_qty": round(max(0.0, float(stock.get(i, {}).get("on_hand_qty") or 0) + d), 3),
                             "updated_at": _now()} for i, d in delta.items()], "store_id,item_id")


def qty_by_item(rows):
    """영수증 품목 줄 → {item_id: 기준 단위 양 합계}"""
    out = {}
    for r in rows:
        if r.get("item_id") and r.get("qty_base"):
            out[int(r["item_id"])] = out.get(int(r["item_id"]), 0) + float(r["qty_base"])
    return out
