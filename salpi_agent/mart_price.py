"""대형마트 판매가: 한국소비자원 생필품 가격(참가격) 중 음식 재료만.

대형마트 · 슈퍼마켓 · 백화점 · 편의점에서 실제로 파는 값이라 도매 경락가와 다름.
2주마다 조사하고 달마다 파일 하나로 올라옴 → 가장 최근 파일 하나에서
최근 조사일 판매가와 2주 전(같은 파일의 앞 조사일) 대비 변화를 계산.
같은 회사 매장은 값이 거의 같아서(롯데슈퍼 160곳이 한 값) 매장 평균 대신 회사별 가격으로 봄.
"""

import re
from statistics import median
from urllib.parse import quote

from data_sources import kca_latest_file, kca_rows, _cached

# 음식 재료만 고르기: 상품명에 들어 있는 글자로 분류 (위에서부터 먼저 맞는 것)
# 2026-10 파일 592개 상품을 보고 정함. 과자 · 음료 · 술 · 커피 · 즉석밥 · 생활용품은 뺌
SKIP = ["3분", "컵밥", "컵반", "죽(", "볶음밥", "국밥", "곰탕", "육개장", "미역국", "콩나물국", "이유식", "진밥", "퓨레",
        "스프", "핫도그", "초밥", "식빵", "버터롤", "아몬드", "녹차", "잼", "젤리", "햇반", "오뚜기밥", "만쥬", "막걸리"]
CATEGORIES = [
    ("면 · 떡 · 쌀", ["밀가루", "부침가루", "소면", "국수", "당면", "파스타", "스파게티", "우동", "냉면", "떡볶이",
                    "라면", "탕면", "너구리", "왕뚜껑", "쌀(", "진상미", "진미(", "현미("]),
    ("김치 · 가공", ["김치", "단무지", "젓갈", "낙지젓", "명란젓", "오징어젓", "햄", "베이컨", "소시지", "비엔나", "스팸",
                   "만두", "돈까스", "돈카츠"]),
    ("수산", ["갈치", "고등어", "대하(", "오징어(", "부세", "참조기", "새우(", "연어", "참치", "맛살", "크래미", "어묵",
             "미역", "도시락김", "올리브김"]),
    ("식용유", ["카놀라유", "콩기름", "포도씨유", "식용유", "참기름"]),
    ("장 · 양념", ["고추장", "된장", "토장", "쌈장", "간장", "액젓", "고춧가루", "참깨", "식초", "소금", "다시다", "설탕",
                 "물엿", "올리고당", "마요네즈", "케찹", "와사비", "드레싱", "카레", "짜장", "맛선생"]),
    ("유제품 · 두부", ["두부", "우유", "버터", "치즈", "마가린"]),
    ("고기 · 달걀", ["돼지고기", "쇠고기 ", "훈제오리", "토종닭", "계란", "달걀", "유정란", "목초란"]),
    ("채소 · 버섯", ["감자(", "고구마(", "당근(", "대파(", "마늘(", "무(줄기", "배추(", "시금치(", "애호박", "양배추",
                   "양파(", "오이(", "상추(", "깻잎(", "쪽파", "풋고추", "버섯(", "콩나물"]),
]
CATEGORY_NAMES = [c for c, _ in CATEGORIES]

# 매장 이름 앞부분 → 회사 (2026-10 파일: 롯데슈퍼 160 · 이마트 125 · GS더프레시 124 · 현대백화점 14 · 농협 12 · 신세계 5 · 편의점 3)
CHAINS = {"롯데슈퍼": "롯데슈퍼", "GS더프레시": "GS더프레시", "GS25": "GS25", "이마트": "이마트", "현대백화점": "현대백화점",
          "신세계백화점": "신세계백화점", "(주)농협": "농협하나로마트", "세븐일레븐": "세븐일레븐", "CU": "CU"}
# 매장 이름으로 고른 대구 매장 (이름에 지역이 없는 곳은 빠질 수 있음)
DAEGU_STORES = {"이마트만촌점", "이마트반야월점", "이마트성서점", "이마트월배점", "이마트칠성점", "롯데슈퍼대구고산점",
                "롯데슈퍼대구대실점", "롯데슈퍼복현점", "롯데슈퍼수성점", "롯데슈퍼프리미엄황금점", "현대백화점대구점",
                "GS더프레시죽곡점", "GS더프레시본리점"}


# 회사 → 그 회사 온라인 장보기몰의 검색 결과 주소 (2026-11 실제로 열어 확인)
# 현대백화점 · GS더프레시 · 편의점은 맞는 온라인 장보기몰이 없어 뺌 → 몰이 있는 회사 중 가장 싼 곳으로 연결
SHOPS = {
    "이마트": ("이마트몰", "https://emart.ssg.com/search.ssg?query={q}"),
    "신세계백화점": ("SSG.COM", "https://www.ssg.com/search.ssg?query={q}"),
    "농협하나로마트": ("농협몰", "https://www.nonghyupmall.com/BC1F010M/srchTotalList.nh?searchTerm_main={q}&CHAN_C=1101&chanC=1101"),
    "롯데슈퍼": ("롯데마트 제타", "https://lottemartzetta.com/products/search?q={q}"),
}


def _search_word(name):
    """참가격 상품명 → 쇼핑몰 검색어. '곰표 밀가루 중력다목적용(1kg)' → '곰표 밀가루 중력다목적용 1kg'."""
    return " ".join(re.sub(r"[()\[\],]", " ", name).split())


def shop_link(item):
    """가장 싼 회사의 온라인몰 검색 결과로 가는 바로가기. 그 회사에 몰이 없으면 몰이 있는 회사 중 가장 싼 곳."""
    for c in item["chains"]:   # 이미 가격 낮은 순
        if c["chain"] in SHOPS:
            mall, url = SHOPS[c["chain"]]
            return {"chain": c["chain"], "mall": mall, "price": c["price"], "lowest": c["chain"] == item["low_chain"],
                    "url": url.format(q=quote(_search_word(item["name"])))}
    return None


def category(name):
    if any(s in name for s in SKIP):
        return None
    if name.startswith("쇠고기"):   # '쇠고기 다시다'처럼 뒤에 붙는 경우와 구분
        return "고기 · 달걀"
    return next((c for c, words in CATEGORIES if any(w in name for w in words)), None)


def chain(store):
    return next((c for prefix, c in CHAINS.items() if store.startswith(prefix)), store)


def _regular(r):
    """할인 · 1+1 표시가 없는 평소 가격."""
    return r.get("세일여부") != "Y" and r.get("원플러스원") != "Y"


def _by_chain(rows):
    """회사별 가격 = 그 회사 매장 값의 가운데 값."""
    groups = {}
    for r in rows:
        groups.setdefault(chain(r["판매업소"]), []).append(r)
    return {c: {"price": round(median(r["판매가격"] for r in g)), "stores": len(g), "channel": g[0]["제조사"]}
            for c, g in groups.items()}   # '제조사' 칸에 매장 종류(대형마트 · 슈퍼마켓 …)가 들어 있음


def _summary(rows):
    """한 파일의 행 → 음식 재료별 회사별 최근 판매가 · 2주 전 대비 · 대구 매장."""
    dates = sorted({r["조사일"] for r in rows})
    last, prev = dates[-1], (dates[-2] if len(dates) > 1 else None)
    by_item = {}
    for r in rows:
        cat = category(r["상품명"] or "")
        if cat and r.get("판매가격"):
            by_item.setdefault(r["상품명"], {"cat": cat, "rows": []})["rows"].append(r)

    items = []
    for name, v in by_item.items():
        now = [r for r in v["rows"] if r["조사일"] == last]
        if not now:
            continue
        regular = [r for r in now if _regular(r)] or now   # 전부 할인이면 할인가라도 씀
        before = _by_chain([r for r in v["rows"] if r["조사일"] == prev and _regular(r)])
        chains = []
        for c, x in _by_chain(regular).items():
            old = before.get(c, {}).get("price")
            chains.append({"chain": c, **x, "prev": old, "change_pct": round((x["price"] / old - 1) * 100, 1) if old else None})
        chains.sort(key=lambda x: x["price"])
        moved = [x["change_pct"] for x in chains if x["change_pct"] is not None]
        daegu = [r["판매가격"] for r in regular if r["판매업소"] in DAEGU_STORES]
        sale = [r["판매가격"] for r in now if not _regular(r)]
        items.append({
            "name": name, "category": v["cat"], "low": chains[0]["price"], "low_chain": chains[0]["chain"],
            "high": chains[-1]["price"], "typical": round(median(x["price"] for x in chains)), "chains": chains,
            "up_chains": sum(p > 0 for p in moved), "down_chains": sum(p < 0 for p in moved),
            "change_pct": round(median(moved), 1) if moved else None,   # 회사별 변화의 가운데 값
            "daegu": {"price": round(median(daegu)), "stores": len(daegu)} if daegu else None,
            "sale_min": min(sale) if sale else None,
        })
    items.sort(key=lambda x: (CATEGORY_NAMES.index(x["category"]), x["name"]))
    return {"date": last, "prev_date": prev, "categories": CATEGORY_NAMES, "items": items}


def mart_prices():
    """가장 최근 파일의 음식 재료 판매가 (파일마다 한 번만 계산해 보관)."""
    f = kca_latest_file()
    data = _cached(f"kca_{f['uddi']}", None, lambda: _summary(kca_rows(f["uddi"])))
    items = [{**x, "shop": shop_link(x)} for x in data["items"]]   # 링크는 보관한 계산 결과 위에 매번 붙임 (주소를 바꿔도 바로 반영)
    return {**data, "items": items, "file_date": f["date"], "source": "한국소비자원 생필품 가격 정보(참가격)"}
