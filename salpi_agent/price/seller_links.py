"""사러 가기 판매처 주소 (11/24 확정) — GET /api/buy-links?item=양파

- 판매처 6곳: 식봄 · 쿠팡 · 농협몰 · 이마트몰 · 롯데마트 제타 · 배민상회 (화면 '어디서 살까요?' 창과 같은 순서)
- 재료가 있으면 그 재료 **상품 목록(검색 결과)**, 없으면 각 사이트 첫 화면
- 상품 **상세 페이지**는 '더 싼 곳'(price/cheaper.py)이 식봄 상품 주소(goods/detail/번호)로 바로 연결
- 쿠팡 파트너스: .env 의 COUPANG_ACCESS_KEY · COUPANG_SECRET_KEY 가 있으면 쿠팡 주소를 파트너스 주소(link.coupang.com)로 바꿈
  (쿠팡 파트너스 Open API '딥링크'. 키는 파트너스 센터 → 추가 기능 → 파트너스 API, 최종 승인 뒤 발급)
  키가 없거나 바꾸기에 실패하면 일반 쿠팡 주소 + affiliate = false → 화면은 대가성 안내 문구를 안 보여 줌
- 목록 순서는 수수료와 상관없이 그대로 (plan/bm/1123_affiliate_fee.md '중립성')
"""
import hashlib
import hmac
import os
import time
from urllib.parse import quote

import requests

SHOPS = [
    {"name": "식봄", "logo": "foodspring", "home": "https://www.foodspring.co.kr", "search": "https://www.foodspring.co.kr/search/all?key={q}"},
    {"name": "쿠팡", "logo": "coupang", "home": "https://www.coupang.com", "search": "https://www.coupang.com/np/search?q={q}"},
    {"name": "농협몰", "logo": "nonghyup", "home": "https://www.nonghyupmall.com",
     "search": "https://www.nonghyupmall.com/BC1F010M/srchTotalList.nh?searchTerm_main={q}&CHAN_C=1101&chanC=1101"},
    {"name": "이마트몰", "logo": "emart", "home": "https://emart.ssg.com", "search": "https://emart.ssg.com/search.ssg?query={q}"},
    {"name": "롯데마트 제타", "logo": "zetta", "home": "https://lottemartzetta.com", "search": "https://lottemartzetta.com/products/search?q={q}"},
    {"name": "배민상회", "logo": "baemin", "home": "https://mart.baemin.com", "search": "https://mart.baemin.com/search/result?w={q}"},
]
AD_NOTE = "쿠팡 링크는 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."

COUPANG_HOST = "https://api-gateway.coupang.com"
COUPANG_DEEPLINK = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"
_deeplinks = {}   # 원래 주소 → (파트너스 주소, 받은 시각). 같은 재료는 하루 동안 다시 안 바꿈
DEEPLINK_TTL = 24 * 3600


def _coupang_keys():
    ak, sk = os.getenv("COUPANG_ACCESS_KEY", "").strip(), os.getenv("COUPANG_SECRET_KEY", "").strip()
    return (ak, sk) if ak and sk else (None, None)


def _coupang_auth(method, path, ak, sk):
    """쿠팡 Open API 서명 (CEA HmacSHA256): signed-date + method + path + query 를 비밀 키로 서명."""
    signed = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
    sig = hmac.new(sk.encode(), f"{signed}{method}{path}".encode(), hashlib.sha256).hexdigest()
    return f"CEA algorithm=HmacSHA256, access-key={ak}, signed-date={signed}, signature={sig}"


def coupang_deeplink(url):
    """쿠팡 주소 → 파트너스 주소. 키가 없거나 실패하면 None (일반 주소를 그대로 씀)."""
    ak, sk = _coupang_keys()
    if not ak:
        return None
    hit = _deeplinks.get(url)
    if hit and time.time() - hit[1] < DEEPLINK_TTL:
        return hit[0]
    try:
        r = requests.post(COUPANG_HOST + COUPANG_DEEPLINK, json={"coupangUrls": [url]}, timeout=10,
                          headers={"Authorization": _coupang_auth("POST", COUPANG_DEEPLINK, ak, sk),
                                   "Content-Type": "application/json;charset=UTF-8"})
        data = (r.json().get("data") or []) if r.ok else []
        short = (data[0].get("shortenUrl") or data[0].get("landingUrl")) if data else None
    except (requests.RequestException, ValueError):
        short = None
    if short:
        _deeplinks[url] = (short, time.time())
    else:
        print(f"[쿠팡 파트너스] 주소 바꾸기 실패, 일반 주소 사용: {url}", flush=True)
    return short


def links(item=None, foodspring_url=None):
    """판매처마다 {name, logo, url, affiliate}. 재료가 없으면 첫 화면."""
    q = quote((item or "").strip())
    out = []
    for s in SHOPS:
        url = s["search"].format(q=q) if q else s["home"]
        if s["logo"] == "foodspring" and foodspring_url:
            url = foodspring_url
        affiliate = False
        if s["logo"] == "coupang":
            deep = coupang_deeplink(url)
            if deep:
                url, affiliate = deep, True
        out.append({"name": s["name"], "logo": s["logo"], "url": url, "affiliate": affiliate})
    return {"item": item or None, "shops": out, "ad_note": AD_NOTE if any(s["affiliate"] for s in out) else None}
