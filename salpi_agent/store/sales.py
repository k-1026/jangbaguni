"""판매 기록 입력 · 확인 — 하루에 메뉴별로 몇 그릇 팔았는지 (Supabase sales_daily).

- GET  /api/sales?date=2026-11-24 : 그날 메뉴(판매 중인 것)마다 홀 · 배달 그릇 수 + 최근 입력한 날
- PUT  /api/sales                  : {date, items: [{menu_id, hall, delivery}]} 저장 → 내일 준비 · 원가율이 다시 계산됨
- 하루 판매를 올리면 판매율 분석 1회 (account/trial.py feature=sales, 같은 날짜를 고쳐 올리면 다시 세지 않음)
- 빈칸(None)은 '안 넣음' → 그 칸은 건드리지 않음. 0은 '안 팔림'으로 저장
- 지금은 시연 가게 한 곳 (영수증 · 메뉴와 같음, supabase_db.DEMO_STORE)
- 영업시간(stores.open_time · close_time): 마감이 자정을 넘기면(11:00 ~ 02:00) 새벽 마감 전까지는 전날을 '오늘'로 봄
  PUT /api/sales/hours {open, close} 로 저장
"""
import re
from datetime import date, datetime, time, timedelta, timezone

from sources import supabase_db as db
from sources.data_sources import ApiError

KST = timezone(timedelta(hours=9))
MAX_QTY = 2000          # 한 메뉴 하루 최대 그릇 수
BACK_DAYS = 60          # 며칠 전까지 고칠 수 있나
CHANNELS = {"hall": "홀", "delivery": "배달"}


DEFAULT_HOURS = ("11:00", "21:00")


def hours(store_id):
    """가게 영업시간 ("HH:MM", "HH:MM"). DB에 칸이 아직 없거나(schema.sql 의 alter 전) 비었으면 기본값."""
    try:
        r = db.select("stores", id=f"eq.{store_id}", select="open_time,close_time")
    except ApiError:
        return DEFAULT_HOURS
    r = r[0] if r else {}
    return (str(r.get("open_time") or DEFAULT_HOURS[0])[:5], str(r.get("close_time") or DEFAULT_HOURS[1])[:5])


def business_day(now, open_t, close_t):
    """영업일: 마감이 자정을 넘기는 가게(마감 <= 개점)는 새벽 마감 시각 전까지 전날."""
    o, c = time.fromisoformat(open_t), time.fromisoformat(close_t)
    return now.date() - timedelta(1) if c <= o and now.time() < c else now.date()


assert business_day(datetime(2026, 11, 27, 1, 30), "11:00", "02:00") == date(2026, 11, 26)   # 새벽 1:30 마감 전 → 전날
assert business_day(datetime(2026, 11, 27, 3, 0), "11:00", "02:00") == date(2026, 11, 27)
assert business_day(datetime(2026, 11, 27, 1, 30), "11:00", "21:00") == date(2026, 11, 27)   # 자정 전 마감 가게는 그대로


def _today(store_id=db.DEMO_STORE):
    return business_day(datetime.now(KST).replace(tzinfo=None), *hours(store_id))


def set_hours(store_id, open_t, close_t):
    for t in (open_t, close_t):
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(t or "")):
            raise ValueError("영업시간은 11:00 처럼 시:분으로 넣어 주세요")
    if open_t == close_t:
        raise ValueError("개점과 마감 시간이 같아요")
    try:
        db.update("stores", {"open_time": open_t, "close_time": close_t}, id=f"eq.{store_id}")
    except ApiError:
        raise ValueError("영업시간 칸이 아직 DB에 없어요. supabase/schema.sql 의 영업시간 줄을 먼저 실행해 주세요")
    return {"open_time": open_t, "close_time": close_t, "today": _today(store_id).isoformat()}


def _day(text, today):
    try:
        d = date.fromisoformat(text) if text else today
    except (TypeError, ValueError):
        raise ValueError("날짜는 2026-11-24 형식으로 보내 주세요")
    if d > today:
        raise ValueError("오늘보다 뒤 날짜는 넣을 수 없어요")
    if d < today - timedelta(BACK_DAYS):
        raise ValueError(f"{BACK_DAYS}일보다 오래된 날짜는 고칠 수 없어요")
    return d


def _menus(store_id):
    return db.select("menus", store_id=f"eq.{store_id}", is_active="is.true", select="id,name,price", order="id")


def _last_day(store_id):
    rows = db.select("sales_daily", store_id=f"eq.{store_id}", select="sale_date", order="sale_date.desc", limit="1")
    return rows[0]["sale_date"] if rows else None


def day(store_id, text=None):
    """그날 메뉴별 홀 · 배달 그릇 수 (안 넣은 칸은 None) + 영업시간 · 영업일 기준 오늘."""
    h = hours(store_id)
    today = business_day(datetime.now(KST).replace(tzinfo=None), *h)
    d = _day(text, today)
    rows = db.select("sales_daily", store_id=f"eq.{store_id}", sale_date=f"eq.{d.isoformat()}", select="menu_id,channel,qty")
    got = {(r["menu_id"], r["channel"]): r["qty"] for r in rows}
    menus = [{"menu_id": m["id"], "name": m["name"], "price": m["price"],
              "hall": got.get((m["id"], "홀")), "delivery": got.get((m["id"], "배달"))} for m in _menus(store_id)]
    entered = [m for m in menus if m["hall"] is not None or m["delivery"] is not None]
    return {"date": d.isoformat(), "today": today.isoformat(), "open_time": h[0], "close_time": h[1], "menus": menus, "entered": bool(entered),
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
    d = _day(body.get("date"), _today(store_id))
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
