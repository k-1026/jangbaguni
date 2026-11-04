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


def insert(table, rows):
    """새 줄을 넣고 넣은 줄(자동 번호 포함)을 돌려받음."""
    base, headers = _base()
    try:
        r = requests.post(base + table, json=rows, timeout=20, headers={**headers, "Prefer": "return=representation"})
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        code = getattr(getattr(e, "response", None), "status_code", None) or type(e).__name__
        raise ApiError(f"Supabase {table} 저장 실패 ({code})") from None


def delete(table, **params):
    base, headers = _base()
    try:
        r = requests.delete(base + table, params=params, timeout=20, headers={**headers, "Prefer": "return=representation"})
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        code = getattr(getattr(e, "response", None), "status_code", None) or type(e).__name__
        raise ApiError(f"Supabase {table} 삭제 실패 ({code})") from None


# ---------------------------------------------------------------
# 사진 보관 (Supabase Storage, 비공개 보관함)
# ---------------------------------------------------------------
_buckets_ready = set()


def upload(bucket, path, data, content_type):
    """비공개 보관함(bucket)에 파일을 올림. 보관함이 없으면 처음 한 번 만듦."""
    base, headers = _base()
    storage = base.replace("/rest/v1/", "/storage/v1/")
    auth = {"apikey": headers["apikey"], "Authorization": f"Bearer {headers['apikey']}"}
    try:
        if bucket not in _buckets_ready:
            r = requests.post(storage + "bucket", json={"id": bucket, "name": bucket, "public": False}, headers=auth, timeout=20)
            if r.status_code not in (200, 201, 400, 409):   # 400 · 409 = 이미 있음
                r.raise_for_status()
            _buckets_ready.add(bucket)
        r = requests.post(f"{storage}object/{bucket}/{path}", data=data, timeout=30,
                          headers={**auth, "Content-Type": content_type, "x-upsert": "true"})
        r.raise_for_status()
        return f"{bucket}/{path}"
    except requests.RequestException as e:
        code = getattr(getattr(e, "response", None), "status_code", None) or type(e).__name__
        raise ApiError(f"Supabase 사진 보관 실패 ({code})") from None


def remove_file(path):
    """보관함 파일 지우기 (path = "보관함/경로"). 실패해도 영수증 지우기는 계속."""
    base, headers = _base()
    bucket, _, name = path.partition("/")
    try:
        requests.delete(base.replace("/rest/v1/", "/storage/v1/") + f"object/{bucket}", json={"prefixes": [name]}, timeout=20,
                        headers={"apikey": headers["apikey"], "Authorization": f"Bearer {headers['apikey']}"})
    except requests.RequestException:
        pass
