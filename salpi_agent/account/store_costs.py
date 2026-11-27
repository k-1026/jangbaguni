"""가게 비용 (마이페이지 '내 정보'): 좌석 · 쉬는 요일 · 업종 · 고정 비용 · 판매 비용 · 배달 비용 저장.

- 계정 정보(user_metadata.store_costs)에 저장 → 다른 기기 · 앱에서 로그인해도 같은 값 (가게 이름 · 구와 같은 방식, 표를 따로 만들지 않음)
- 금액은 화면과 같은 '만 원' 단위 그대로 (예: 임대료 120 = 120만 원)
- 화면이 보낸 값을 아래 모양으로만 걸러서 저장 (모르는 칸 · 음수 · 너무 긴 글자는 버림)
"""
from account import auth
from sources.data_sources import ApiError

WEEK = ("월", "화", "수", "목", "금", "토", "일")
BIZ = ("한식", "중식", "일식", "양식", "분식", "치킨", "카페", "기타")
FIXED_KEYS = ("rent", "manage", "staff", "power", "gas", "water")
DELIV_KEYS = ("sales", "fee", "ride", "pack")
SECS = ("fixed", "sale", "deliv")
MAX_MAN = 100_000          # 한 칸 최대 10억 원 (만 원 단위)
MAX_EXTRA = 30


def _num(v, top=MAX_MAN):
    """빈칸 → None, 숫자 → 0 ~ top 로 자름, 숫자가 아니면 None."""
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:   # NaN
        return None
    return round(min(max(x, 0), top), 2)


def clean(c):
    """화면 값 → 저장할 값. 모양이 틀린 칸은 버림 (사장님이 넣은 다른 칸은 그대로 살림)."""
    if not isinstance(c, dict):
        raise auth.AuthError("비용 정보 모양이 올바르지 않아요.")
    fixed = c.get("fixed") if isinstance(c.get("fixed"), dict) else {}
    deliv = c.get("deliv") if isinstance(c.get("deliv"), dict) else {}
    extra = []
    for x in (c.get("extra") if isinstance(c.get("extra"), list) else [])[:MAX_EXTRA]:
        if not isinstance(x, dict):
            continue
        name = str(x.get("name") or "").strip()[:30]
        v = _num(x.get("v"))
        if name or v is not None:
            extra.append({"name": name, "v": v, "sec": x.get("sec") if x.get("sec") in SECS else "fixed"})
    closed = c.get("closed") if isinstance(c.get("closed"), list) else ["일"]
    return {
        "seats": _num(c.get("seats"), 1000),
        "closed": [d for d in WEEK if d in closed],
        "biz": c.get("biz") if c.get("biz") in BIZ else None,
        "sales": _num(c.get("sales")),
        "fixed": {k: _num(fixed.get(k)) for k in FIXED_KEYS if _num(fixed.get(k)) is not None},
        "extra": extra,
        "material": _num(c.get("material")),
        "card": _num(c.get("card")),
        "tax": "simple" if c.get("tax") == "simple" else "general",
        "delivery": bool(c.get("delivery")),
        "deliv": {k: _num(deliv.get(k)) for k in DELIV_KEYS if _num(deliv.get(k)) is not None},
    }


def of(user):
    """계정 → 저장된 비용 (없으면 None = 아직 서버에 넣은 적 없음)."""
    return (user.get("user_metadata") or {}).get("store_costs")


def get(token):
    return {"costs": of(auth.user_of(token))}


def save(token, costs):
    user = auth.user_of(token)
    value = clean(costs)
    meta = {**(user.get("user_metadata") or {}), "store_costs": value}
    r = auth._call("PUT", f"admin/users/{user['id']}", admin=True, json={"user_metadata": meta})
    if not r.ok:
        raise ApiError(f"가게 비용을 저장하지 못했어요 ({r.status_code})")
    return {"costs": value}


TARGETS = (30, 35, 40, 45)   # 원가율 기준(%) 고를 수 있는 값: 자영업자 카페 답 30 · 35 · 40% + 고기 위주 가게 45%


def target_of(user):
    """계정 → 원가율 기준(%). 고른 적 없으면 None (= 기본 40%)."""
    return (user.get("user_metadata") or {}).get("cost_target")


def set_target(token, target):
    """원가율 기준 저장 (계정 정보에 → 다른 기기에서도 같은 값). 11/27 피드백: 사장님마다 원가율 기준이 다를 수 있음."""
    if target not in TARGETS:
        raise auth.AuthError(f"원가율 기준은 {' · '.join(map(str, TARGETS))}% 중에서 골라 주세요.")
    user = auth.user_of(token)
    meta = {**(user.get("user_metadata") or {}), "cost_target": target}
    r = auth._call("PUT", f"admin/users/{user['id']}", admin=True, json={"user_metadata": meta})
    if not r.ok:
        raise ApiError(f"원가율 기준을 저장하지 못했어요 ({r.status_code})")
    return target
