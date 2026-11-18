"""사장님 계정: 회원가입 · 로그인 · 로그인 유지 · 로그아웃 · 탈퇴 (Supabase 로그인 = auth.users).

- 아이디로 가입: Supabase 로그인은 이메일이 있어야 해서, 아이디로 내부용 주소(<아이디>@id.salpi.app)를 만들어 씀
  (메일 · 문자는 보내지 않음 — 가입하면 바로 확인된 계정으로 만듦). 이름 · 휴대폰 · 알림 동의는 계정 정보(user_metadata)에
- 로그인: 아이디 또는 휴대폰 번호 + 비밀번호 → 로그인 표(access_token · refresh_token). 비밀번호는 우리가 저장하지 않음
- 가게: 가입할 때 stores 에 한 줄 (owner_id = 계정). 가게 번호 · 이름 · 구는 계정 정보(user_metadata)에도 복사해 둠
  → 로그인 · 내 정보가 Supabase 를 한 번만 다녀옴 (한 번에 약 0.3초). 가게 이름을 바꾸는 기능을 만들면 계정 정보도 같이 고칠 것 계정을 지우면 가게 → 메뉴 · 영수증 · 재고 · 판매 기록까지 함께 지워짐 (schema.sql cascade)
- 휴대폰 번호로 찾기: 계정 목록을 훑음 (가입자가 수천 명을 넘으면 따로 표로 옮길 것)
- 휴대폰 인증 문자는 아직 연결 전 (화면에서 6자리를 넣으면 인증된 것으로 봄)
- 카카오 로그인: Supabase 의 카카오 연결(Authentication → Providers → Kakao)을 그대로 씀
  kakao_url() 로 카카오 화면에 보냄 → 돌아오면 화면이 로그인 표를 받음 → 가게가 없으면 setup_store() 로 가게 · 약관만 한 번 받음
"""
import base64
import json as _json
import os
import re
import uuid
from urllib.parse import quote

import requests

from sources import supabase_db as db
from sources.data_sources import ApiError, ApiKeyMissing

ID_DOMAIN = "id.salpi.app"
DAEGU_GU = {"중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군", "군위군"}


class AuthError(Exception):
    """사장님께 그대로 보여 줄 수 있는 안내 (status = HTTP 코드)."""
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _conf():
    url, key = os.getenv("SUPABASE_URL", "").strip().rstrip("/"), os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if not url or not key:
        raise ApiKeyMissing(".env 의 SUPABASE_URL 또는 SUPABASE_SECRET_KEY 가 비어 있어요")
    return url, key


def _call(method, path, *, json=None, token=None, admin=False, params=None):
    url, key = _conf()
    headers = {"apikey": key}
    if admin:
        headers["Authorization"] = f"Bearer {key}"
    elif token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        return db._http().request(method, f"{url}/auth/v1/{path}", json=json, params=params, headers=headers, timeout=20)
    except requests.RequestException as e:
        raise ApiError(f"로그인 서버에 연결하지 못했어요 ({type(e).__name__})") from None


def _digits(phone):
    return re.sub(r"\D", "", phone or "")


def _email(login_id):
    return f"{login_id.lower()}@{ID_DOMAIN}"


def _users():
    """계정 전부 (쪽 나눠 받기)."""
    out, page = [], 1
    while True:
        r = _call("GET", "admin/users", admin=True, params={"page": page, "per_page": 1000})
        if not r.ok:
            raise ApiError(f"계정 목록을 읽지 못했어요 ({r.status_code})")
        users = r.json().get("users", [])
        out += users
        if len(users) < 1000:
            return out
        page += 1


def _by_phone(digits):
    return next((u for u in _users() if (u.get("user_metadata") or {}).get("phone") == digits), None)


def _store_of(user_id):
    rows = db.select("stores", owner_id=f"eq.{user_id}", select="id,name,district,business_type", order="created_at", limit="1")
    return rows[0] if rows else None


def _store_meta(store_id, name, district):
    return {"store_id": store_id, "store_name": name, "district": district}


def _profile(user, store=False):
    meta = user.get("user_metadata") or {}
    if store is False:   # 계정 정보에 가게가 복사돼 있으면 표를 다시 읽지 않음
        store = ({"id": meta["store_id"], "name": meta.get("store_name"), "district": meta.get("district"),
                  "business_type": meta.get("business_type", "한식")} if meta.get("store_id") else _store_of(user["id"]))
    name = meta.get("name") or meta.get("full_name") or meta.get("nickname") or meta.get("preferred_username")   # 카카오는 닉네임
    return {"id": user["id"], "login_id": meta.get("login_id"), "name": name,
            "provider": (user.get("app_metadata") or {}).get("provider", "email"),
            "phone": meta.get("phone"), "alarm": bool(meta.get("alarm")),
            "store_id": store["id"] if store else None, "store_name": store["name"] if store else None,
            "district": store["district"] if store else None, "business_type": store["business_type"] if store else None,
            "place": meta.get("place"), "avatar": (meta.get("avatar_url") or meta.get("picture") or "").replace("http://", "https://", 1) or None}   # 카카오 사진은 http 로 옴 → https 사이트에서 막히지 않게


def _session(body):
    """Supabase 로그인 답 → 화면에 줄 것 (로그인 표 + 사장님 · 가게 정보)."""
    return {"access_token": body["access_token"], "refresh_token": body["refresh_token"],
            "expires_at": body.get("expires_at"), "user": _profile(body["user"])}


# ---------------------------------------------------------------

def signup(d):
    name = (d.get("name") or "").strip()
    login_id = (d.get("login_id") or "").strip()
    pw = d.get("password") or ""
    phone = _digits(d.get("phone"))
    store = (d.get("store") or "").strip()
    gu = (d.get("district") or "").strip()
    if not name:
        raise AuthError("이름을 입력해 주세요.")
    if not re.fullmatch(r"01\d{8,9}", phone):
        raise AuthError("휴대폰 번호를 확인해 주세요.")
    if not re.fullmatch(r"[A-Za-z0-9_]{4,30}", login_id):
        raise AuthError("아이디는 영문 · 숫자 4자 이상으로 정해 주세요.")
    if len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise AuthError("비밀번호는 영문 · 숫자를 섞어 8자 이상으로 정해 주세요.")
    if not store:
        raise AuthError("가게 이름을 입력해 주세요.")
    if gu not in DAEGU_GU:
        raise AuthError("가게가 있는 구 · 군을 골라 주세요.")
    if not d.get("terms_ok"):
        raise AuthError("필수 약관에 동의해 주세요.")
    if _by_phone(phone):
        raise AuthError("이미 가입한 휴대폰 번호예요. 로그인해 주세요.", 409)
    store_id = str(uuid.uuid4())
    r = _call("POST", "admin/users", admin=True, json={
        "email": _email(login_id), "password": pw, "email_confirm": True,
        "user_metadata": {"name": name, "login_id": login_id.lower(), "phone": phone, "alarm": bool(d.get("alarm")),
                          "place": (d.get("place") or "").strip(), **_store_meta(store_id, store, gu)}})
    if r.status_code in (409, 422) and "already" in r.text:
        raise AuthError("이미 쓰고 있는 아이디예요. 다른 아이디로 정해 주세요.", 409)
    if not r.ok:
        raise ApiError(f"계정을 만들지 못했어요 ({r.status_code})")
    user = r.json()
    try:
        db.insert("stores", [{"id": store_id, "owner_id": user["id"], "name": store, "district": gu, "is_demo": False}])
    except Exception:
        _call("DELETE", f"admin/users/{user['id']}", admin=True)   # 가게를 못 만들면 계정도 되돌림 (반쪽 가입 방지)
        raise
    return login(login_id, pw)


def login(login_id, password):
    login_id = (login_id or "").strip()
    if not login_id or not password:
        raise AuthError("아이디와 비밀번호를 입력해 주세요.")
    digits = _digits(login_id)
    if re.fullmatch(r"01\d{8,9}", digits):   # 휴대폰 번호로 로그인
        u = _by_phone(digits)
        email = u["email"] if u else None
    else:
        email = _email(login_id)
    r = _call("POST", "token", params={"grant_type": "password"}, json={"email": email, "password": password}) if email else None
    if r is None or r.status_code == 400:
        raise AuthError("아이디(휴대폰 번호) 또는 비밀번호가 맞지 않아요.", 401)
    if not r.ok:
        raise ApiError(f"로그인하지 못했어요 ({r.status_code})")
    return _session(r.json())


def refresh(refresh_token):
    r = _call("POST", "token", params={"grant_type": "refresh_token"}, json={"refresh_token": refresh_token or ""})
    if not r.ok:
        raise AuthError("로그인이 끝났어요. 다시 로그인해 주세요.", 401)
    return _session(r.json())


def user_of(token):
    """로그인 표 → 계정. 표가 없거나 만료면 AuthError(401)."""
    if not token:
        raise AuthError("로그인이 필요해요.", 401)
    r = _call("GET", "user", token=token)
    if not r.ok:
        raise AuthError("로그인이 끝났어요. 다시 로그인해 주세요.", 401)
    return r.json()


def _sub(token):
    """로그인 표 안의 계정 번호 (확인은 user_of 가 따로 함 — 여기선 가게 조회를 미리 시작하려고만 씀)."""
    try:
        part = token.split(".")[1]
        return _json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("sub")
    except Exception:
        return None


def me(token):
    """계정 정보에 가게가 복사돼 있으면 한 번만 다녀옴. 예전 계정(복사본 없음)은 로그인 확인과 가게 조회를 동시에."""
    sub = _sub(token or "")
    if not sub:
        return _profile(user_of(token))
    user = user_of(token)
    if (user.get("user_metadata") or {}).get("store_id"):
        return _profile(user)
    return _profile(user)


def kakao_url(site, next_path="/", talk=False):
    """카카오 로그인 화면 주소. 승인하면 <site>/?page=oauth&next=... 로 돌아오며 주소 # 뒤에 로그인 표가 붙음."""
    url, _ = _conf()
    back = f"{site.rstrip('/')}/?page=oauth&next={quote(next_path if next_path.startswith('/') else '/', safe='')}"
    # talk=True (마이페이지 '카카오로 연결'): 카카오톡 시세 알림(나에게 보내기)용 '카카오톡 메시지 전송' 동의도 받음
    # 평소 로그인에는 붙이지 않음 — 카카오 앱 동의항목에서 켜기 전에 붙이면 카카오 로그인 자체가 오류(KOE205)
    scopes = "&scopes=talk_message" if talk else ""
    return f"{url}/auth/v1/authorize?provider=kakao{scopes}&redirect_to={quote(back, safe='')}"


def setup_store(token, d):
    """카카오로 처음 온 사장님: 가게(이름 · 구) · 약관 · 알림 동의를 한 번 받음. 이미 가게가 있으면 그대로."""
    user = user_of(token)
    if not _store_of(user["id"]):
        name = (d.get("name") or "").strip()
        store = (d.get("store") or "").strip()
        gu = (d.get("district") or "").strip()
        if not name:
            raise AuthError("이름을 입력해 주세요.")
        if not store:
            raise AuthError("가게 이름을 입력해 주세요.")
        if gu not in DAEGU_GU:
            raise AuthError("가게가 있는 구 · 군을 골라 주세요.")
        if not d.get("terms_ok"):
            raise AuthError("필수 약관에 동의해 주세요.")
        store_id = str(uuid.uuid4())
        db.insert("stores", [{"id": store_id, "owner_id": user["id"], "name": store, "district": gu, "is_demo": False}])
        meta = {**(user.get("user_metadata") or {}), "name": name, "alarm": bool(d.get("alarm")), "place": (d.get("place") or "").strip(),
                **_store_meta(store_id, store, gu)}
        r = _call("PUT", f"admin/users/{user['id']}", admin=True, json={"user_metadata": meta})
        if not r.ok:
            raise ApiError(f"사장님 정보를 저장하지 못했어요 ({r.status_code})")
        user = r.json()
    return _profile(user)


def logout(token):
    if token:
        _call("POST", "logout", token=token)   # 이 계정의 로그인 유지 표를 모두 무효로


def withdraw(token):
    """계정 삭제 → 가게 · 메뉴 · 영수증 · 재고 · 판매 기록이 함께 지워짐. 영수증 사진 파일은 따로 지움."""
    user = user_of(token)
    for s in db.select("stores", owner_id=f"eq.{user['id']}", select="id"):
        for p in db.select("purchases", store_id=f"eq.{s['id']}", select="image_path"):
            if p.get("image_path"):
                db.remove_file(p["image_path"])
    r = _call("DELETE", f"admin/users/{user['id']}", admin=True)
    if not r.ok:
        raise ApiError(f"탈퇴하지 못했어요 ({r.status_code})")
