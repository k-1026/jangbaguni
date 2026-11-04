"""공공 API에서 시세·날씨·행사·공휴일을 받아오는 부분.

키와 주소는 저장소 맨 위 .env 에서 읽는다. 지난 날짜 데이터는 바뀌지 않으므로
cache/ 폴더에 저장해 두고 다시 부르지 않는다 (API 호출 횟수 절약).
"""

import json
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
# 코드 근거: research/industry_food/1028_data_collection_detail.json + perDay 응답으로 품목명 확인 (2026-11-03)
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
    cfg = ITEMS[item_name]
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
                 "addr": r.get("addr1")} for r in _items(body)]

    return _cached(f"events_{today.isoformat()}", 12, fetch)


def events_between(start, end):
    """start~end(date) 기간과 하루라도 겹치는 행사."""
    a, z = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    return [e for e in _events_raw() if (e["end"] or "") >= a and (e["start"] or "") <= z]


def daegu_events(days_ahead=14):
    return events_between(date.today(), date.today() + timedelta(days_ahead))


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
