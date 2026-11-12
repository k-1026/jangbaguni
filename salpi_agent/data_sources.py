"""공공 API에서 시세·날씨·행사·공휴일을 받아오는 부분.

키와 주소는 저장소 맨 위 .env 에서 읽는다. 지난 날짜 데이터는 바뀌지 않으므로
cache/ 폴더에 저장해 두고 다시 부르지 않는다 (API 호출 횟수 절약).
"""

import json
import xml.etree.ElementTree as ET
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")   # 내 컴퓨터용. Vercel에서는 프로젝트 설정의 환경 변수를 씀
# Vercel은 /tmp 에만 파일을 쓸 수 있음 (서버가 새로 켜지면 비워짐)
CACHE_DIR = Path("/tmp/salpi_cache") if os.getenv("VERCEL") else ROOT / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DAEGU_MARKET = os.getenv("AT_WHSL_MRKT_CD", "220001")   # 대구 북부도매시장(매천시장)
DAEGU_SGG = os.getenv("AT_PERDAY_SGG_CD", "2200")       # perDay 대구 지역 코드
DAEGU_STN = os.getenv("KMA_ASOS_STN_ID", "143")         # 기상청 대구 관측소
DAEGU_LDONG = os.getenv("KTO_TOUR_LDONG_REGN_CD", "27") # 관광공사 대구 지역 코드

# 품목 목록: perDay(KAMIS 코드)와 정산정보(품목 이름)를 함께 적어 둠
# sale_sub: 정산정보 소분류 이름에 이 글자가 들어간 것만 사용 (다른 상품·수입산 섞임 방지)
# 코드 근거: data/raw/1028_data_collection_detail.json + perDay 응답으로 품목명 확인 (2026-11-03)
ITEMS = {
    "양파":     {"ctgry": "200", "item": "245", "vrty": None, "sale_name": "양파",   "sale_sub": None},
    "대파":     {"ctgry": "200", "item": "246", "vrty": None, "sale_name": "대파",   "sale_sub": None},
    "배추":     {"ctgry": "200", "item": "211", "vrty": None, "sale_name": "배추",   "sale_sub": None},
    "무":       {"ctgry": "200", "item": "231", "vrty": None, "sale_name": "무",     "sale_sub": None},
    "양배추":   {"ctgry": "200", "item": "212", "vrty": None, "sale_name": "양배추", "sale_sub": None},
    "감자":     {"ctgry": "100", "item": "152", "vrty": None, "sale_name": "감자",   "sale_sub": None},
    "당근":     {"ctgry": "200", "item": "232", "vrty": None, "sale_name": "당근",   "sale_sub": "당근(일반)"},  # 수입 제외
    "애호박":   {"ctgry": "200", "item": "224", "vrty": "01", "sale_name": "호박",   "sale_sub": "애호박"},
    "오이":     {"ctgry": "200", "item": "223", "vrty": None, "sale_name": "오이",   "sale_sub": None},
    "청양고추": {"ctgry": "200", "item": "242", "vrty": "03", "sale_name": "풋고추", "sale_sub": "청양"},
    "깻잎":     {"ctgry": "200", "item": "253", "vrty": None, "sale_name": "깻잎",   "sale_sub": "깻잎(일반)"},  # 깻잎순 제외
    "상추":     {"ctgry": "200", "item": "214", "vrty": None, "sale_name": "상추",   "sale_sub": None},
    "시금치":   {"ctgry": "200", "item": "213", "vrty": None, "sale_name": "시금치", "sale_sub": None},
    "토마토":   {"ctgry": "200", "item": "225", "vrty": None, "sale_name": "토마토", "sale_sub": None},
    "가지":     {"ctgry": "200", "item": "251", "vrty": None, "sale_name": "가지",   "sale_sub": None},
}

# 육류 · 수산물: 대구 북부도매시장 정산정보(경매)에는 없어서 aT 일별 도·소매가(perDay, KAMIS 조사)만 씀
# → 경매 반입량이 없으니 7일 예측은 하지 않고 시세 변화만 보여 줌. ITEMS와 섞지 않음
# se: 소매 / 중도매, grd: 쓸 등급 코드(None이면 전부 평균)
# 이름은 menu_cost.REFERENCE_PRICES 이름과 같게 둠 (메뉴 원가 계산에서 그대로 바꿔 씀)
# 코드 근거: perDay 대구 응답으로 품목 · 품종 · 단위 확인 (2026-11-12)
# 육류는 KAMIS에 대구 · 전국 모두 소매가만 있음 (도매는 경매 경락가뿐) → 대시보드는 사장님이 실제로 사는 부위별 소매가
# 경락가(협신식품)는 예측 이유(먼저 움직이는 가격 · 경매 물량)와 재료 페이지 등급표에만 씀 (EKAPE_LINKS)
EXTRA_ITEMS = {
    "한우 등심":          {"group": "육류", "ctgry": "500", "item": "4301", "vrty": "22", "se": "소매", "grd": "3"},  # 1등급 100g
    "한우 양지":          {"group": "육류", "ctgry": "500", "item": "4301", "vrty": "40", "se": "소매", "grd": "3"},  # 1등급 100g (국거리)
    "수입 소고기 갈비살": {"group": "육류", "ctgry": "500", "item": "4401", "vrty": "37", "se": "소매", "grd": "1"},  # 미국산 100g
    "돼지고기 앞다리": {"group": "육류",   "ctgry": "500", "item": "4304", "vrty": "25", "se": "소매",   "grd": None},  # 100g
    "돼지고기 삼겹살": {"group": "육류",   "ctgry": "500", "item": "4304", "vrty": "27", "se": "소매",   "grd": None},  # 100g
    "닭고기":          {"group": "육류",   "ctgry": "500", "item": "9901", "vrty": "99", "se": "소매",   "grd": None},  # 육계 1kg
    "계란":            {"group": "육류",   "ctgry": "500", "item": "9903", "vrty": "23", "se": "소매",   "grd": "1"},   # XL 30구 일반란
    "오징어":          {"group": "수산물", "ctgry": "600", "item": "619",  "vrty": "05", "se": "중도매", "grd": None},  # 원양 냉동, 북부도매 kg
    "고등어":          {"group": "수산물", "ctgry": "600", "item": "611",  "vrty": "02", "se": "중도매", "grd": None},  # 냉동, 북부도매 10kg
    "새우젓":          {"group": "수산물", "ctgry": "600", "item": "650",  "vrty": "00", "se": "소매",   "grd": None},  # 1kg
    # 중도매가는 대구 북부도매시장, 등급이 여러 개면 하나로 고정 (등급이 빠진 날 값이 튀지 않게)
    "갈치":            {"group": "수산물", "ctgry": "600", "item": "613",  "vrty": "02", "se": "중도매", "grd": "21"},  # 냉동 中, kg
    "명태":            {"group": "수산물", "ctgry": "600", "item": "615",  "vrty": "02", "se": "중도매", "grd": "21"},  # 냉동 中, 20kg
    "굴":              {"group": "수산물", "ctgry": "600", "item": "644",  "vrty": "00", "se": "중도매", "grd": None},  # kg
    "홍합":            {"group": "수산물", "ctgry": "600", "item": "658",  "vrty": "02", "se": "중도매", "grd": None},  # 안깐홍합, kg
    "새우":            {"group": "수산물", "ctgry": "600", "item": "654",  "vrty": "01", "se": "중도매", "grd": None},  # 흰다리(수입), 2kg
    "마른멸치":        {"group": "수산물", "ctgry": "600", "item": "638",  "vrty": "00", "se": "중도매", "grd": "28"},  # 2kg
    "멸치액젓":        {"group": "수산물", "ctgry": "600", "item": "651",  "vrty": "00", "se": "소매",   "grd": None},  # 1kg
    "김":              {"group": "수산물", "ctgry": "600", "item": "641",  "vrty": "00", "se": "중도매", "grd": None},  # 마른김 1속
    "마른미역":        {"group": "수산물", "ctgry": "600", "item": "642",  "vrty": "00", "se": "중도매", "grd": None},  # kg
}

FOODSPRING_SEARCH = "https://www.foodspring.co.kr/search/all"


def foodspring_url(item_name):
    """식봄 검색 결과로 연결 (살피는 판매하지 않고 연결만 함)."""
    return requests.Request("GET", FOODSPRING_SEARCH, params={"key": item_name}).prepare().url


class ApiKeyMissing(RuntimeError):
    pass


def _key(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise ApiKeyMissing(f".env 의 {name} 가 비어 있어요")
    return value


class ApiError(RuntimeError):
    """API 호출 실패 (오류 문장에 인증키가 찍히지 않게 주소를 뺌)."""


_api_slots = threading.Semaphore(3)   # 공공데이터포털에 동시에 보내는 요청은 서버 전체에서 3개까지 (넘으면 429)


def _get_json(url, params, key_name, key_param="serviceKey"):
    params = {key_param: _key(key_name), **params}
    for attempt in range(5):
        try:
            with _api_slots:
                r = requests.get(url, params=params, timeout=40)
            if r.status_code == 429:          # 한꺼번에 너무 많이 부름 → 조금 쉬었다가 다시
                raise requests.HTTPError("429")
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            if attempt == 4:
                code = getattr(getattr(e, "response", None), "status_code", None) or str(e)[:3]
                raise ApiError(f"{url.rsplit('/', 2)[-2]} 호출 실패 ({code})") from None
            time.sleep(2 ** (attempt + 1))   # 2 · 4 · 8 · 16초 쉬고 다시


_cache_locks, _cache_locks_guard = {}, threading.Lock()


def _cached(name, max_age_hours, fetch):
    """max_age_hours=None 이면 영구 보관 (지난 날짜용). 같은 이름은 한 번만 받고 나머지는 기다림."""
    with _cache_locks_guard:
        lock = _cache_locks.setdefault(name, threading.Lock())
    with lock:
        path = CACHE_DIR / f"{name}.json"
        if path.exists():
            age = (time.time() - path.stat().st_mtime) / 3600
            if max_age_hours is None or age < max_age_hours:
                return json.loads(path.read_text(encoding="utf-8"))
        data = fetch()
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data


def _items(body):
    items = (body or {}).get("items") or {}
    item = items.get("item", []) if isinstance(items, dict) else []
    return [item] if isinstance(item, dict) else item


# ---------------------------------------------------------------
# aT 정산정보: 대구 북부도매시장 하루 경락 결과
# ---------------------------------------------------------------

_SALE_FIELDS = ("gds_mclsf_nm", "gds_sclsf_nm", "grd_nm", "unit_nm", "totprc", "unit_tot_qty")


def _fetch_sale_day(day):
    url = os.getenv("AT_SALE_ENDPOINT", "https://apis.data.go.kr/B552845/katSale") + "/trades"

    def page(n):
        return _get_json(url, {
            "returnType": "JSON", "numOfRows": 1000, "pageNo": n,
            "cond[whsl_mrkt_cd::EQ]": DAEGU_MARKET,
            "cond[trd_clcln_ymd::EQ]": day.isoformat(),
        }, "AT_SALE_API_KEY")["response"]["body"]

    first = page(1)
    pages = -(-int(first.get("totalCount") or 0) // 1000)   # 올림
    with ThreadPoolExecutor(max_workers=1) as pool:          # 한 날짜 안에서는 차례로 (동시 요청을 줄임)
        rest = list(pool.map(page, range(2, pages + 1)))
    return [{f: r.get(f) for f in _SALE_FIELDS} for body in [first, *rest] for r in _items(body)]


def sale_day(day):
    """하루치 정산 결과 (휴장일은 빈 목록)."""
    recent = (date.today() - day).days <= 2   # 최근 이틀은 늦게 올라오는 값이 있어 3시간마다 갱신
    return _cached(f"sale_{day.isoformat()}", 3 if recent else None, lambda: _fetch_sale_day(day))


def sale_days(days):
    """오늘부터 거꾸로 days일치 정산 결과를 {날짜: rows}로."""
    dates = [date.today() - timedelta(d) for d in range(days)]
    with ThreadPoolExecutor(max_workers=4) as pool:       # 공공데이터포털은 한꺼번에 많이 부르면 429로 막음
        results = pool.map(sale_day, dates)
    return dict(zip(dates, results))


# ---------------------------------------------------------------
# aT 일별 도·소매 가격정보 (perDay): KAMIS 조사가격, 대구
# ---------------------------------------------------------------

def perday_prices(item_name, days=35):
    cfg = ITEMS.get(item_name) or EXTRA_ITEMS[item_name]
    start, end = date.today() - timedelta(days), date.today()

    def fetch():
        url = os.getenv("AT_PERDAY_ENDPOINT", "https://apis.data.go.kr/B552845/perDay") + "/price"
        params = {
            "returnType": "JSON", "numOfRows": 1000, "pageNo": 1,
            "cond[exmn_ymd::GTE]": start.strftime("%Y%m%d"),
            "cond[exmn_ymd::LTE]": end.strftime("%Y%m%d"),
            "cond[ctgry_cd::EQ]": cfg["ctgry"], "cond[item_cd::EQ]": cfg["item"],
            "cond[sgg_cd::EQ]": DAEGU_SGG,
        }
        if cfg["vrty"]:
            params["cond[vrty_cd::EQ]"] = cfg["vrty"]
        body = _get_json(url, params, "AT_PERDAY_API_KEY")["response"]["body"]
        return _items(body)

    return _cached(f"perday_{cfg['item']}_{cfg['vrty']}_{end.isoformat()}_{days}", 6, fetch)


# ---------------------------------------------------------------
# 기상청 ASOS 일자료 (대구, 어제까지)
# ---------------------------------------------------------------

def weather_days(days=21):
    end = date.today() - timedelta(1)
    start = end - timedelta(days - 1)

    def fetch():
        url = os.getenv("KMA_ASOS_ENDPOINT", "https://apis.data.go.kr/1360000/AsosDalyInfoService") + "/getWthrDataList"
        body = _get_json(url, {
            "dataType": "JSON", "dataCd": "ASOS", "dateCd": "DAY", "pageNo": 1, "numOfRows": 100,
            "startDt": start.strftime("%Y%m%d"), "endDt": end.strftime("%Y%m%d"), "stnIds": DAEGU_STN,
        }, "KMA_ASOS_API_KEY")["response"]["body"]

        def num(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        return [{"date": r["tm"], "avg_temp": num(r.get("avgTa")), "min_temp": num(r.get("minTa")),
                 "max_temp": num(r.get("maxTa")), "rain_mm": num(r.get("sumRn")) or 0.0,
                 "humidity": num(r.get("avgRhm")), "cloud": num(r.get("avgTca")),   # 전운량 0~10
                 "snow_cm": num(r.get("ddMefs")) or 0.0} for r in _items(body)]

    return _cached(f"weather_sky_{end.isoformat()}_{days}", 6, fetch)


# ---------------------------------------------------------------
# 한국관광공사 행사·축제 (대구)
# ---------------------------------------------------------------

def _events_raw():
    """오늘 기준 60일 전부터 시작한 대구 행사 전부 (12시간마다 갱신)."""
    today = date.today()

    def fetch():
        url = os.getenv("KTO_TOUR_ENDPOINT", "https://apis.data.go.kr/B551011/KorService2") + "/searchFestival2"
        body = _get_json(url, {
            "MobileOS": "ETC", "MobileApp": "salpi", "_type": "json", "numOfRows": 200, "pageNo": 1,
            "eventStartDate": (today - timedelta(60)).strftime("%Y%m%d"), "lDongRegnCd": DAEGU_LDONG,
        }, "KTO_TOUR_API_KEY")["response"]["body"]
        return [{"title": r.get("title"), "start": r.get("eventstartdate"), "end": r.get("eventenddate"),
                 "addr": r.get("addr1"), "content_id": r.get("contentid"), "image": r.get("firstimage2") or r.get("firstimage")}
                for r in _items(body)]

    return _cached(f"events2_{today.isoformat()}", 12, fetch)


def events_between(start, end):
    """start~end(date) 기간과 하루라도 겹치는 행사."""
    a, z = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    return [e for e in _events_raw() if (e["end"] or "") >= a and (e["start"] or "") <= z]


def daegu_events(days_ahead=14):
    return events_between(date.today(), date.today() + timedelta(days_ahead))


def month_events():
    """오늘부터 이달 말일까지 열리는 행사 (이미 끝난 행사는 뺌)."""
    today = date.today()
    month_end = (today.replace(day=28) + timedelta(4)).replace(day=1) - timedelta(1)
    return events_between(today, month_end)


def event_detail(content_id):
    """행사 하나 자세히: 소개 · 장소 · 시간 · 요금 · 홈페이지 (관광공사 공통정보 + 소개정보, 하루 보관)."""
    import re
    url = os.getenv("KTO_TOUR_ENDPOINT", "https://apis.data.go.kr/B551011/KorService2")
    base = {"MobileOS": "ETC", "MobileApp": "salpi", "_type": "json", "contentId": content_id}

    def fetch():
        common = _items(_get_json(url + "/detailCommon2", base, "KTO_TOUR_API_KEY")["response"]["body"])
        intro = _items(_get_json(url + "/detailIntro2", {**base, "contentTypeId": 15}, "KTO_TOUR_API_KEY")["response"]["body"])
        c, i = (common or [{}])[0], (intro or [{}])[0]
        clean = lambda t: re.sub(r"<br\s*/?>", "\n", re.sub(r"<(?!br)[^>]+>", "", str(t or ""))).strip()
        return {
            "content_id": content_id, "title": c.get("title"), "image": c.get("firstimage") or c.get("firstimage2"),
            "overview": clean(c.get("overview")), "addr": c.get("addr1"), "tel": c.get("tel") or i.get("sponsor1tel"),
            "homepages": list(dict.fromkeys(re.findall(r"https?://[^\s\"'<>]+", str(c.get("homepage") or "")))),
            "start": i.get("eventstartdate"), "end": i.get("eventenddate"), "place": clean(i.get("eventplace")),
            "playtime": clean(i.get("playtime")), "fee": clean(i.get("usetimefestival")), "program": clean(i.get("program")),
            "sponsor": clean(i.get("sponsor1")),
        }

    return _cached(f"event_{content_id}", 24, fetch)


# ---------------------------------------------------------------
# 한국소비자원 생필품 가격 정보 (참가격) — 마트 · 슈퍼 · 백화점 · 편의점 판매가
# 실시간이 아니라 달마다 파일(uddi:...)이 하나씩 올라옴 → 목록(Swagger)에서 가장 최근 파일을 찾음
# ---------------------------------------------------------------
KCA_DOCS = "https://infuser.odcloud.kr/oas/docs?namespace=15083256/v1"


def kca_latest_file():
    """가장 최근 파일 {uddi, date}. 목록은 하루 보관 (이름 끝 날짜: 20261023 · 09/24/2021 두 가지 모양)."""
    import re

    def fetch():
        r = requests.get(KCA_DOCS, timeout=40)
        r.raise_for_status()
        files = []
        for path, ops in r.json()["paths"].items():
            title = ops.get("get", {}).get("summary", "")
            m = re.search(r"(\d{4})(\d{2})(\d{2})$", title) or re.search(r"(\d{2})/(\d{2})/(\d{4})$", title)
            if m:
                y, mo, d = m.groups() if len(m.group(1)) == 4 else (m.group(3), m.group(1), m.group(2))
                files.append({"uddi": path.rsplit("/", 1)[-1], "date": f"{y}-{mo}-{d}"})
        return max(files, key=lambda f: f["date"])

    return _cached("kca_files", 24, fetch)


def kca_rows(uddi):
    """파일 하나 전부 (약 24만 줄, 1만 줄씩 나눠 받음)."""
    url = os.getenv("KCA_PRICE_ENDPOINT", "https://api.odcloud.kr/api/15083256/v1") + "/" + uddi
    page = lambda p: _get_json(url, {"page": p, "perPage": 10000}, "KCA_PRICE_API_KEY")
    first = page(1)
    pages = -(-first["totalCount"] // 10000)
    with ThreadPoolExecutor(3) as pool:
        rest = list(pool.map(page, range(2, pages + 1)))
    return [r for body in [first, *rest] for r in body["data"]]


# ---------------------------------------------------------------
# 한국천문연구원 특일 정보 (공휴일)
# ---------------------------------------------------------------

def holidays_between(start, end):
    """start~end(date) 사이 공휴일."""
    months, d = set(), start.replace(day=1)
    while d <= end:
        months.add((d.year, d.month))
        d = (d + timedelta(32)).replace(day=1)

    def fetch(y, m):
        url = os.getenv("KASI_SPCDE_ENDPOINT", "https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService") + "/getRestDeInfo"
        body = _get_json(url, {"solYear": y, "solMonth": f"{m:02d}", "_type": "json", "numOfRows": 50},
                         "KASI_SPCDE_API_KEY", key_param="ServiceKey")["response"]["body"]
        return [{"date": str(r["locdate"]), "name": r["dateName"]} for r in _items(body) if r.get("isHoliday") == "Y"]

    result = []
    for y, m in sorted(months):
        result += _cached(f"holidays_{y}_{m:02d}", 24 * 7, lambda y=y, m=m: fetch(y, m))
    a, z = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    return [h for h in result if a <= h["date"] <= z]


def holidays(days_ahead=30):
    return holidays_between(date.today(), date.today() + timedelta(days_ahead))


# ---------------------------------------------------------------
# 축산물품질평가원 축산물경락가격정보: 대구 협신식품 경매가 (육류 예측의 '먼저 움직이는 가격' · '경매 물량')
#   beefGrade: 소고기 부위별(등심 · 양지 …) 등급별 경락가 kg당 · 상자 수 (abattCd 로 시장 지정)
#   pigGrade : 돼지 도체 등급별 경락가 kg당 · 마릿수 (시장별 값이 c_<코드>Amt · c_<코드>Cnt 칸으로 한꺼번에 옴)
# 하루치씩 불러야 날짜별 값이 나옴 (기간을 넣으면 그 기간 평균 하나). 요청마다 하루 1,000번 한도
# → 주말(경매 없음)은 부르지 않고, 지난 날짜는 한 번 받으면 영구 보관
# ---------------------------------------------------------------

EKAPE_MARKET = "0302"   # 협신식품 (대구 북구 축산물 도매시장)
EKAPE_MARKET_NAME = "협신식품(대구)"
# 육류 소매 품목 → 참고할 경락가. 한우는 같은 부위 1등급(hanAvg_2), 돼지는 부위 경매가 없어 도체(등외 제외 평균)
EKAPE_LINKS = {
    "한우 등심":       {"op": "beefGrade", "cut": "등심", "price": "hanAvg_2", "count": "hanBoxCnt", "what": "한우 등심 1등급", "count_unit": "상자"},
    "한우 양지":       {"op": "beefGrade", "cut": "양지", "price": "hanAvg_2", "count": "hanBoxCnt", "what": "한우 양지 1등급", "count_unit": "상자"},
    "돼지고기 앞다리": {"op": "pigGrade", "grade": "등외제외", "what": "돼지 도체(등외 제외 평균)", "count_unit": "마리"},
    "돼지고기 삼겹살": {"op": "pigGrade", "grade": "등외제외", "what": "돼지 도체(등외 제외 평균)", "count_unit": "마리"},
}
BEEF_GRADES = [("1++", "0"), ("1+", "1"), ("1", "2"), ("2", "3"), ("3", "4")]   # 등급 → hanAvg_<n> · han_<n>Cnt
PIG_GRADES = ["1+", "1", "2", "등외"]


def _ekape_get(op, day, **params):
    """XML 응답 → item 목록. 실패하면 키가 보이지 않는 오류 문장으로."""
    url = f"{os.getenv('EKAPE_ENDPOINT', 'http://data.ekape.or.kr/openapi-data/service/user/grade').rstrip('/')}/auct/{op}"
    ymd = day.strftime("%Y%m%d")
    params = {"serviceKey": _key("EKAPE_API_KEY"), "startYmd": ymd, "endYmd": ymd, **params}
    for attempt in range(4):
        try:
            with _api_slots:
                r = requests.get(url, params=params, timeout=40)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            code = root.findtext(".//resultCode")
            if code not in (None, "00"):
                raise ApiError(f"축산물품질평가원 {op} 오류 ({code} {root.findtext('.//resultMsg')})")
            return [{c.tag: c.text for c in it} for it in root.iter("item")]
        except ApiError:
            raise
        except (requests.RequestException, ET.ParseError) as e:
            if attempt == 3:
                code = getattr(getattr(e, "response", None), "status_code", None) or type(e).__name__
                raise ApiError(f"축산물품질평가원 {op} 호출 실패 ({code})") from None
            time.sleep(2 ** (attempt + 1))


def _num(v):
    try:
        return float(v) if v not in (None, "", "0") else None
    except ValueError:
        return None


def _fetch_ekape_day(day):
    """하루치: {"beef": {부위: {price_<칸>, count}}, "pig": {등급: {price, count, all_price, all_count}}}"""
    beef = {}
    for x in _ekape_get("beefGrade", day, abattCd=EKAPE_MARKET):
        cut = x.get("cutmeatName")
        if cut in ("등심", "양지"):
            beef[cut] = {k: _num(v) for k, v in x.items() if k.startswith(("hanAvg", "hanBoxCnt", "han_"))}
    pig = {}
    for x in _ekape_get("pigGrade", day):
        pig[x.get("gradeNm")] = {"price": _num(x.get(f"c_{EKAPE_MARKET}Amt")), "count": _num(x.get(f"c_{EKAPE_MARKET}Cnt")),
                                 "all_price": _num(x.get("CTotAmt")), "all_count": _num(x.get("CTotCnt"))}
    return {"beef": beef, "pig": pig}


def ekape_day(day):
    recent = (date.today() - day).days <= 2   # 최근 이틀은 늦게 올라오는 값이 있어 3시간마다 갱신
    return _cached(f"ekape2_{day.isoformat()}", 3 if recent else None, lambda: _fetch_ekape_day(day))


def ekape_days(days=35):
    """오늘부터 거꾸로 days일 중 평일만 {날짜: 하루치}. 키가 없으면 빈 값 (육류 화면은 소매가만으로 동작)."""
    if not os.getenv("EKAPE_API_KEY", "").strip():
        return {}
    dates = [d for d in (date.today() - timedelta(n) for n in range(days)) if d.weekday() < 5]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = pool.map(ekape_day, dates)
    return dict(zip(dates, results))

