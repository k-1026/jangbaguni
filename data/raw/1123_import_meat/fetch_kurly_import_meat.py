"""마켓컬리에서 수입 고기(돼지 · 닭 · 오리 · 소) 상품 · 원산지 · 가격 받기 — 돼지고기 · 닭고기 외국산 대체 재료 가격 자료용.
실행 (저장소 맨 위 폴더에서): python data/raw/1123_import_meat/fetch_kurly_import_meat.py
- 검색: api.kurly.com 검색 API (고기 종류별 검색어, 첫 페이지 최대 96개) → 상품마다 상세 API (원산지 product_origin · 용량 volume · 판매가)
- 식봄 · 쿠팡 · 이마트몰은 자동 접속을 막아(빈 응답 · 403 · Access Denied) 읽지 못함 (2026-11-23). 마켓컬리만 열려 있음
- 가격은 컬리 판매가(회원 할인 전 기본 판매가). kg당 = 판매가 ÷ 용량(g) × 1000 — 용량을 못 읽으면 비움
- 결과: 1123_kurly_import_meat.csv (상품 한 줄), 1123_kurly_import_meat_summary.txt (고기 종류 × 원산지 요약)
- 상세 호출은 0.3초씩 쉬며 천천히 (서버에 부담 주지 않게)"""
import csv, re, statistics, sys, time
from collections import defaultdict
from pathlib import Path
import requests

HERE = Path(__file__).resolve().parent
HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9"}
SEARCH = "https://api.kurly.com/search/v4/sites/market/normal-search"
DETAIL = "https://api.kurly.com/showroom/v2/products/{}"

KEYWORDS = {
    "돼지": ["수입 삼겹살", "수입 돼지고기", "수입 앞다리살", "수입 목살", "냉동 삼겹살", "미국산 돼지고기", "스페인산 돼지고기", "독일산 돼지고기", "캐나다산 돼지고기"],
    "닭": ["수입 닭고기", "브라질산 닭", "냉동 닭다리살", "수입 닭가슴살", "수입 닭정육", "태국산 닭", "냉동 닭"],
    "오리": ["오리고기", "훈제오리", "오리 슬라이스", "수입 오리"],
    "소": ["수입 소고기", "미국산 소고기", "호주산 소고기", "수입 갈비살", "수입 양지", "수입 등심", "수입 채끝", "수입 차돌박이"],
}
KIND_WORDS = {"돼지": ("돼지", "삼겹", "목살", "앞다리", "항정", "갈매기", "오겹", "돈육", "포크"), "닭": ("닭", "치킨"), "오리": ("오리",),
              "소": ("소고기", "쇠고기", "갈비", "양지", "등심", "채끝", "차돌", "안심", "우둔", "설도", "척아이롤", "부채살", "한우", "비프", "스테이크")}


def get(url, **params):
    for t in range(4):
        try:
            r = requests.get(url, params=params or None, headers=HEAD, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (403, 404):
                return None
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 * 2 ** t)
    return None


def kind_of(name, searched):
    for k in ("오리", "닭", "돼지", "소"):   # 이름에 있는 종류를 먼저, 없으면 검색한 종류
        if any(w in name for w in KIND_WORDS[k]):
            return k
    return searched


def grams(volume, name):
    s = f"{volume or ''} {name}"
    m = re.search(r"([\d.]+)\s*(kg|g)\b", s, re.I)
    if not m:
        return None
    v = float(m.group(1))
    return v * 1000 if m.group(2).lower() == "kg" else v


COUNTRIES = ("미국", "호주", "뉴질랜드", "캐나다", "브라질", "칠레", "스페인", "독일", "덴마크", "네덜란드", "프랑스", "폴란드", "헝가리", "이탈리아",
             "태국", "중국", "베트남", "러시아", "우루과이", "아르헨티나", "파라과이", "멕시코", "영국", "아일랜드")
DOMESTIC = re.compile(r"국내|(?<![가-힣])국산|한우|한돈|육우")   # '미국산' · '중국산' 의 '국산'은 국내산이 아님


def origin_final(origin, name, category=""):
    """원산지 칸이 '상세정보 참조' 같으면 이름에서 나라를 찾음. 못 찾으면 '확인 불가'."""
    for c in COUNTRIES:
        if re.search(c + r"(산|)", origin or ""):
            return c + "산"
    if DOMESTIC.search(origin or ""):
        return "국내산"
    for c in COUNTRIES:
        if c + "산" in name:
            return c + "산"
    if DOMESTIC.search(name):
        return "국내산"
    if "수입" in category:   # 컬리 카테고리가 수입육이면 나라는 몰라도 수입산
        return "수입산(나라 미표기)"
    return "확인 불가"


def summarize(rows):
    grp = defaultdict(list)
    for r in rows:
        if r["category"].startswith(("반려동물", "밀키트", "냉장/냉동 식품", "양념육")):   # 사료 · 가공식품은 제외 (원재료 가격이 아님)
            continue
        grp[(r["kind"], r["origin_final"])].append(r["price_per_kg"])
    lines = []
    for k, v in sorted(grp.items()):
        ok = [x for x in v if x != ""]
        lines.append(f"{k[0]} · {k[1]}: {len(v)}개 · kg당 가격 있는 것 {len(ok)}개" + (f" · 가운데값 {int(statistics.median(ok)):,}원/kg" if ok else ""))
    return lines


def main():
    if "--summary-only" in sys.argv:   # 이미 받은 CSV로 요약만 다시 만들기
        with open(HERE / "1123_kurly_import_meat.csv", encoding="utf-8-sig") as f:
            rows = [{**r, "origin_final": origin_final(r["origin"], r["name"], r["category"]), "price_per_kg": int(r["price_per_kg"]) if r["price_per_kg"] else ""}
                    for r in csv.DictReader(f)]
        write(rows)
        return
    found = {}   # 상품번호 → 검색한 종류
    for kind, words in KEYWORDS.items():
        for w in words:
            j = get(SEARCH, keyword=w, page=1, sort_type=4)
            n = 0
            for sec in ((j or {}).get("data") or {}).get("listSections") or []:
                for it in sec["data"]["items"]:
                    found.setdefault(it["no"], (kind, it["name"]))
                    n += 1
            print(f"검색 {kind} · {w}: {n}개", flush=True)
            time.sleep(0.3)
    print(f"상품 {len(found)}개 상세 받기", flush=True)
    rows = []
    for i, (no, (kind, name)) in enumerate(found.items(), 1):
        j = get(DETAIL.format(no))
        time.sleep(0.3)
        d = (j or {}).get("data")
        if not d:
            continue
        name = d.get("name") or name
        sp = d.get("showable_prices") or {}
        price = sp.get("sales_price") or d.get("base_price") or d.get("discounted_price")
        g = grams(d.get("volume"), name)
        cats = d.get("category_names") or []
        rows.append({"no": no, "kind": kind_of(name, kind), "name": name, "origin": (d.get("product_origin") or "").strip(), "origin_final": origin_final((d.get("product_origin") or "").strip(), name, " > ".join(cats)),
                     "volume": d.get("volume") or "", "grams": g or "", "price": price or "", "retail_price": d.get("retail_price") or "",
                     "price_per_kg": round(price / g * 1000) if price and g else "", "unit_price_text": d.get("unit_price_text") or "",
                     "category": " > ".join(c for c in cats if c != "CATEGORY"), "url": f"https://www.kurly.com/goods/{no}"})
        if i % 50 == 0:
            print(f"상세 {i}/{len(found)}", flush=True)
    write(rows)


def write(rows):
    out = HERE / "1123_kurly_import_meat.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    lines = summarize(rows)
    (HERE / "1123_kurly_import_meat_summary.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"저장: {out.name} ({len(rows)}개)")


if __name__ == "__main__":
    sys.exit(main())
