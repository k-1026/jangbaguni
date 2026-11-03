"""Supabase 저장소 읽기 · 쓰기 (판매량 · 메뉴 · 재고 · 예측 결과).

주소와 Secret key는 .env 의 SUPABASE_URL · SUPABASE_SECRET_KEY (Vercel은 환경 변수).
Secret key는 서버에서만 쓰고 화면(브라우저)에는 절대 보내지 않는다.
"""

import os

import requests

from data_sources import ApiError, ApiKeyMissing

DEMO_STORE = "00000000-0000-0000-0000-000000000001"   # 시연용 가게 '살피 시연 한식당' (seed.sql)


def _base():
    url, key = os.getenv("SUPABASE_URL", "").strip().rstrip("/"), os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if not url or not key:
        raise ApiKeyMissing(".env 의 SUPABASE_URL 또는 SUPABASE_SECRET_KEY 가 비어 있어요")
    return f"{url}/rest/v1/", {"apikey": key, "Content-Type": "application/json"}


def select(table, **params):
    """예: select("menus", store_id="eq.<id>", select="id,name")"""
    base, headers = _base()
    params.setdefault("select", "*")
    try:
        r = requests.get(base + table, params=params, headers={**headers, "Range": "0-9999"}, timeout=20)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        code = getattr(getattr(e, "response", None), "status_code", None) or type(e).__name__
        raise ApiError(f"Supabase {table} 읽기 실패 ({code})") from None


def upsert(table, rows, on_conflict):
    """같은 키(on_conflict)가 있으면 새 값으로 바꾸고, 없으면 새로 넣는다."""
    if not rows:
        return
    base, headers = _base()
    try:
        r = requests.post(base + table, params={"on_conflict": on_conflict}, json=rows, timeout=20,
                          headers={**headers, "Prefer": "resolution=merge-duplicates,return=minimal"})
        r.raise_for_status()
    except requests.RequestException as e:
        code = getattr(getattr(e, "response", None), "status_code", None) or type(e).__name__
        raise ApiError(f"Supabase {table} 저장 실패 ({code})") from None
