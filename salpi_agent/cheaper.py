"""더 싼 판매처 — GET /api/cheaper?item=양파 (plan/1116_api_contract.md 3절)

1) 사장님이 산 값: 최근 영수증 단가 → 없으면 대구 소매 평균(KAMIS). paid 로 직접 줄 수도 있음
2) 판매처 상품: 식봄 (지금 받아 보고, 막히면 Supabase price_snapshots 에 하루 한 번 저장한 마지막 값)
3) 상품마다 단위 기준(units.py)으로 기준 단위당 가격 → 못 읽은 상품은 뺌
4) 산 값보다 싼 것만, 싼 순서. 환산("약")이 들어간 비교는 10% 넘게 싸야 넣음 (오차로 억지 판정 안 함)
"""

import foodspring
import receipts
import supabase_db as db
from analysis import item_trend
from data_sources import ITEMS, ApiError, ApiKeyMissing
from units import base_unit, parse_pack, per_base_price

APPROX_BAND_PCT = 10   # 단위 기준: 환산이 들어간 비교는 10% 안쪽이면 "비슷해요"
MAX_SELLERS = 5


def _paid(item, store_id):
    """사장님이 산 값 (기준 단위당). → {"price", "date", "source", "approx"} 또는 None"""
    try:
        ids = {i["name"]: i["id"] for i in db.select("items", select="id,name")}
        hist = receipts._price_history(store_id).get(ids.get(item)) if item in ids else None
        if hist:
            return {"price": round(hist[-1][1]), "date": hist[-1][0], "source": "최근 영수증", "approx": False}
    except (ApiError, ApiKeyMissing):
        pass
    if item in ITEMS:
        r = item_trend(item)["retail"]
        if r.get("base_price"):
            return {"price": r["base_price"], "date": r["date"], "source": "대구 소매 평균(KAMIS)", "approx": r["base_how"] == "약"}
    return None


def _foodspring(item):
    """식봄 상품 [(이름, 판매가, 양, 단위, 주소, 무료배송)] 과 자료 날짜 (None = 지금 받은 것)."""
    goods = foodspring.products(item, limit=20)
    if goods:
        return [(g["name"], g["sale_price"], g["kg"], "kg", g["url"], g.get("free_delivery")) if g.get("kg")
                else (g["name"], g["sale_price"], *(parse_pack(f"{g.get('standard') or ''} {g['name']}") or (None, None)),
                      g["url"], g.get("free_delivery"))
                for g in goods], None
    # 식봄이 자동 접속을 막을 때가 있음 → 하루 한 번 저장한 마지막 값
    try:
        rows = db.select("price_snapshots", source="eq.식봄", item=f"eq.{item}",
                         select="snap_date,product_name,url,sale_price,kg", order="snap_date.desc", limit="40")
    except (ApiError, ApiKeyMissing):
        return [], None
    last = rows[0]["snap_date"] if rows else None
    out = []
    for r in rows:
        if r["snap_date"] != last:
            continue
        qty, unit = (r["kg"], "kg") if r.get("kg") else (parse_pack(r["product_name"]) or (None, None))
        out.append((r["product_name"], r["sale_price"], qty, unit, r["url"], None))
    return out, last


def cheaper(item, paid=None, store_id=db.DEMO_STORE):
    unit = base_unit(item)
    if item not in ITEMS:   # 식봄 상품은 시세 품목(ITEMS)만 모음
        return {"item": item, "unit": unit, "paid_per_unit": None, "paid_source": None, "paid_date": None,
                "paid_approx": None, "sellers": [], "checked": 0, "skipped_unknown_unit": 0, "data_date": None,
                "message": f"'{item}'은(는) 아직 판매처 비교를 지원하지 않아요. 지원 품목: {', '.join(ITEMS)}"}
    p = ({"price": round(float(paid)), "date": None, "source": "직접 입력", "approx": False} if paid
         else _paid(item, store_id))
    goods, snap_date = _foodspring(item)

    sellers, unknown = [], []
    for name, sale_price, qty, q_unit, url, free in goods:
        b = per_base_price(item, sale_price, qty, q_unit) if qty else {"price": None, "how": "모름"}
        if b["price"] is None or b["unit"] != unit:
            unknown.append(name)
            continue
        sellers.append({
            "name": f"식봄 · {name}", "price_per_unit": b["price"], "approx": b["how"] == "약", "url": url,
            "affiliate": False, "retail": False,
            "pack_price": sale_price, "pack": f"{qty:g}{q_unit}", "free_delivery": free, "note": b.get("note"),
        })

    if p:
        def cheap_enough(s):
            if s["price_per_unit"] >= p["price"]:
                return False
            saving = (1 - s["price_per_unit"] / p["price"]) * 100
            return saving > APPROX_BAND_PCT if (s["approx"] or p["approx"]) else True
        sellers = [s for s in sellers if cheap_enough(s)]
        for s in sellers:
            s["saving_per_unit"] = p["price"] - s["price_per_unit"]
            s["saving_pct"] = round((1 - s["price_per_unit"] / p["price"]) * 100, 1)
    sellers.sort(key=lambda s: s["price_per_unit"])

    return {
        "item": item, "unit": unit,
        "paid_per_unit": p["price"] if p else None, "paid_source": p["source"] if p else None,
        "paid_date": p["date"] if p else None, "paid_approx": p["approx"] if p else None,
        "sellers": sellers[:MAX_SELLERS],
        "checked": len(goods), "skipped_unknown_unit": len(unknown),
        "data_date": snap_date,   # None 이면 지금 받은 값, 날짜면 그날 저장한 식봄 가격
        "message": None if goods else "식봄 상품을 불러오지 못했어요",
    }
