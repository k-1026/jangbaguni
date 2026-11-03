"""식봄(foodspring.co.kr) 검색 결과에서 실제 판매 상품 · 가격을 가져온다.

살피는 아무것도 팔지 않는다. 상품을 보여 주고 식봄 상품 페이지로 연결만 한다.
식봄 검색 페이지에 들어 있는 상품 데이터(__NEXT_DATA__)를 읽으며, 6시간마다 다시 받는다.
식봄은 배송 지역마다 판매자가 달라 실제 대구 가격과 다를 수 있다.
"""

import json
import re

import requests

from data_sources import FOODSPRING_SEARCH, ITEMS, _cached

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
DETAIL_URL = "https://www.foodspring.co.kr/goods/detail/{}"

# 검색어와 상품 이름 거르기 (예: '무' 검색에 '무세척 당근'이 섞이지 않게)
SEARCH_WORD = {"청양고추": "청양고추", "애호박": "애호박", "무": "세척무"}
NAME_MUST = {"무": re.compile(r"(^|[\s(★】\]])(세척)?무([\s(]|$)"), "오이": re.compile(r"오이(?!고추)"),
             "가지": re.compile(r"가지(?!버섯)"), "배추": re.compile(r"(?<!양)배추(?!김치)")}


def _kg(standard, name):
    m = re.search(r"([\d.]+)\s*kg", f"{standard or ''} {name}", re.I)
    return float(m.group(1)) if m else None


def _fetch(item):
    word = SEARCH_WORD.get(item, item)
    html = requests.get(FOODSPRING_SEARCH, params={"key": word}, headers=HEADERS, timeout=30).text
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    rec = json.loads(m.group(1))["props"]["pageProps"].get("initialRecords", {})
    goods = []
    for nid in dict.fromkeys(re.findall(r"/goods/detail/(\d+)", html)):   # 검색 순위 순서
        g = rec.get(f"goods_{nid}")
        price = rec.get(f"client:goods_{nid}:price") or {}
        if not g or not price.get("salePrice"):
            continue
        vendor = rec.get((g.get("vendor") or {}).get("__ref", ""), {})
        image = rec.get(f"client:goods_{nid}:images") or {}
        kg = _kg(g.get("standard"), g["name"])
        goods.append({
            "nid": int(nid), "name": g["name"], "standard": g.get("standard"),
            "sale_price": price["salePrice"], "original_price": price.get("originalPrice"),
            "discount_rate": price.get("discountRate"), "kg": kg,
            "price_per_kg": round(price["salePrice"] / kg) if kg else None,
            "vendor": vendor.get("name"), "image": image.get("listingUrl"),
            "free_delivery": g.get("isFreeDelivery"), "url": DETAIL_URL.format(nid),
        })
    return goods


def products(item, limit=4):
    """재료 하나의 식봄 상품 (이름이 맞는 것만, 국내산 먼저)."""
    try:
        goods = _cached(f"foodspring_{item}", 6, lambda: _fetch(item))
    except requests.RequestException:
        return []
    must = NAME_MUST.get(item)
    hits = [g for g in goods if (must.search(g["name"]) if must else item in g["name"])]
    hits.sort(key=lambda g: ("수입" in g["name"] or "중국" in g["name"], ))   # 검색 순위는 유지, 수입산은 뒤로
    return hits[:limit]


def all_products(limit=4):
    return {item: products(item, limit) for item in ITEMS}
