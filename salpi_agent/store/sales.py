"""판매 기록 입력 · 확인 — 하루에 메뉴별로 몇 그릇 팔았는지 (Supabase sales_daily).

- GET  /api/sales?date=2026-11-24 : 그날 메뉴(판매 중인 것)마다 홀 · 배달 그릇 수 + 최근 입력한 날
- PUT  /api/sales                  : {date, items: [{menu_id, hall, delivery}]} 저장 → 내일 준비 · 원가율이 다시 계산됨
- 하루 판매를 올리면 판매율 분석 1회 (account/trial.py feature=sales, 같은 날짜를 고쳐 올리면 다시 세지 않음)
- 빈칸(None)은 '안 넣음' → 그 칸은 건드리지 않음. 0은 '안 팔림'으로 저장
- 지금은 시연 가게 한 곳 (영수증 · 메뉴와 같음, supabase_db.DEMO_STORE)
"""
from datetime import date, datetime, timedelta, timezone

from sources import supabase_db as db

KST = timezone(timedelta(hours=9))
MAX_QTY = 2000          # 한 메뉴 하루 최대 그릇 수
BACK_DAYS = 60          # 며칠 전까지 고칠 수 있나
CHANNELS = {"hall": "홀", "delivery": "배달"}


def _today():
    return datetime.now(KST).date()


def _day(text):
    try:
        d = date.fromisoformat(text) if text else _today()
    except (TypeError, ValueError):
        raise ValueError("날짜는 2026-11-24 형식으로 보내 주세요")
    if d > _today():
        raise ValueError("오늘보다 뒤 날짜는 넣을 수 없어요")
    if d < _today() - timedelta(BACK_DAYS):
        raise ValueError(f"{BACK_DAYS}일보다 오래된 날짜는 고칠 수 없어요")
    return d


def _menus(store_id):
    return db.select("menus", store_id=f"eq.{store_id}", is_active="is.true", select="id,name,price", order="id")


def _last_day(store_id):
    rows = db.select("sales_daily", store_id=f"eq.{store_id}", select="sale_date", order="sale_date.desc", limit="1")
    return rows[0]["sale_date"] if rows else None


def day(store_id, text=None):
    """그날 메뉴별 홀 · 배달 그릇 수 (안 넣은 칸은 None)."""
    d = _day(text)
    rows = db.select("sales_daily", store_id=f"eq.{store_id}", sale_date=f"eq.{d.isoformat()}", select="menu_id,channel,qty")
    got = {(r["menu_id"], r["channel"]): r["qty"] for r in rows}
    menus = [{"menu_id": m["id"], "name": m["name"], "price": m["price"],
              "hall": got.get((m["id"], "홀")), "delivery": got.get((m["id"], "배달"))} for m in _menus(store_id)]
    entered = [m for m in menus if m["hall"] is not None or m["delivery"] is not None]
    return {"date": d.isoformat(), "menus": menus, "entered": bool(entered),
            "total": sum((m["hall"] or 0) + (m["delivery"] or 0) for m in menus),
            "sales_won": sum(((m["hall"] or 0) + (m["delivery"] or 0)) * m["price"] for m in menus),
            "last_sales_date": _last_day(store_id)}


def _qty(v, label):
    if v is None or v == "":
        return None
    try:
        q = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{label}: 그릇 수는 숫자로 넣어 주세요")
    if q < 0 or q != int(q):
        raise ValueError(f"{label}: 그릇 수는 0 이상 정수로 넣어 주세요")
    if q > MAX_QTY:
        raise ValueError(f"{label}: 하루 {MAX_QTY}그릇까지 넣을 수 있어요")
    return int(q)


def save(store_id, body):
    """메뉴별 홀 · 배달 그릇 수 저장. → 저장한 뒤의 그날 판매 (day 와 같은 모양) + 이 날짜를 처음 넣었는지(new)"""
    d = _day(body.get("date"))
    menus = {m["id"]: m for m in _menus(store_id)}
    rows = []
    for x in body.get("items") or []:
        mid = x.get("menu_id")
        if mid not in menus:
            raise ValueError("판매 중인 메뉴가 아니에요. 메뉴 목록을 새로 불러와 주세요")
        for key, channel in CHANNELS.items():
            q = _qty(x.get(key), f"{menus[mid]['name']} {channel}")
            if q is not None:
                rows.append({"store_id": store_id, "menu_id": mid, "sale_date": d.isoformat(), "channel": channel, "qty": q})
    if not rows:
        raise ValueError("그릇 수를 하나 이상 넣어 주세요")
    before = db.select("sales_daily", store_id=f"eq.{store_id}", sale_date=f"eq.{d.isoformat()}", select="menu_id", limit="1")
    db.upsert("sales_daily", rows, "store_id,menu_id,sale_date,channel")
    return {**day(store_id, d.isoformat()), "new": not before, "saved_rows": len(rows)}
