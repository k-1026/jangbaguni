"""공공 API에서 시세·날씨·행사·공휴일을 받아오는 부분.

키와 주소는 저장소 맨 위 .env 에서 읽는다. 지난 날짜 데이터는 바뀌지 않으므로
cache/ 폴더에 저장해 두고 다시 부르지 않는다 (API 호출 횟수 절약).
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")
CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(exist_ok=True)

DAEGU_MARKET = os.getenv("AT_WHSL_MRKT_CD", "220001")   # 대구 북부도매시장(매천시장)
DAEGU_SGG = os.getenv("AT_PERDAY_SGG_CD", "2200")       # perDay 대구 지역 코드
DAEGU_STN = os.getenv("KMA_ASOS_STN_ID", "143")         # 기상청 대구 관측소
DAEGU_LDONG = os.getenv("KTO_TOUR_LDONG_REGN_CD", "27") # 관광공사 대구 지역 코드

# 품목 목록: perDay(KAMIS 코드)와 정산정보(품목 이름)를 함께 적어 둠
# sale_sub: 정산정보 소분류 이름에 이 글자가 들어간 것만 사용 (다른 상품·수입산 섞임 방지)
# 코드 근거: research/industry_food/1028_data_collection_detail.json
ITEMS = {
    "양파":     {"ctgry": "200", "item": "245", "vrty": None, "sale_name": "양파",   "sale_sub": None},
    "대파":     {"ctgry": "200", "item": "246", "vrty": None, "sale_name": "대파",   "sale_sub": None},
    "양배추":   {"ctgry": "200", "item": "212", "vrty": None, "sale_name": "양배추", "sale_sub": None},
    "청양고추": {"ctgry": "200", "item": "242", "vrty": "03", "sale_name": "풋고추", "sale_sub": "청양"},
    "당근":     {"ctgry": "200", "item": "232", "vrty": None, "sale_name": "당근",   "sale_sub": "당근(일반)"},  # 수입 제외
    "깻잎":     {"ctgry": "200", "item": "253", "vrty": None, "sale_name": "깻잎",   "sale_sub": "깻잎(일반)"},  # 깻잎순 제외
}


class ApiKeyMissing(RuntimeError):
    pass


def _key(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise ApiKeyMissing(f".env 의 {name} 가 비어 있어요")
    return value


def _get_json(url, params, key_name, key_param="serviceKey"):
    params = {key_param: _key(key_name), **params}
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=40)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))


def _cached(name, max_age_hours, fetch):
    """max_age_hours=None 이면 영구 보관 (지난 날짜용)."""
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
    rows, page = [], 1
    while True:
        body = _get_json(url, {
            "returnType": "JSON", "numOfRows": 1000, "pageNo": page,
            "cond[whsl_mrkt_cd::EQ]": DAEGU_MARKET,
            "cond[trd_clcln_ymd::EQ]": day.isoformat(),
        }, "AT_SALE_API_KEY")["response"]["body"]
        batch = _items(body)
        rows += [{f: r.get(f) for f in _SALE_FIELDS} for r in batch]
        if not batch or len(rows) >= int(body.get("totalCount") or 0):
            return rows
        page += 1


def sale_day(day):
    """하루치 정산 결과 (휴장일은 빈 목록)."""
    recent = (date.today() - day).days <= 2   # 최근 이틀은 늦게 올라오는 값이 있어 3시간마다 갱신
    return _cached(f"sale_{day.isoformat()}", 3 if recent else None, lambda: _fetch_sale_day(day))


def sale_days(days):
    """오늘부터 거꾸로 days일치 정산 결과를 {날짜: rows}로."""
    dates = [date.today() - timedelta(d) for d in range(days)]
    with ThreadPoolExecutor(max_workers=6) as pool:
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
                 "humidity": num(r.get("avgRhm"))} for r in _items(body)]

    return _cached(f"weather_{end.isoformat()}_{days}", 6, fetch)


# ---------------------------------------------------------------
# 한국관광공사 행사·축제 (대구)
# ---------------------------------------------------------------

def daegu_events(days_ahead=14):
    today = date.today()

    def fetch():
        url = os.getenv("KTO_TOUR_ENDPOINT", "https://apis.data.go.kr/B551011/KorService2") + "/searchFestival2"
        body = _get_json(url, {
            "MobileOS": "ETC", "MobileApp": "salpi", "_type": "json", "numOfRows": 200, "pageNo": 1,
            "eventStartDate": (today - timedelta(60)).strftime("%Y%m%d"), "lDongRegnCd": DAEGU_LDONG,
        }, "KTO_TOUR_API_KEY")["response"]["body"]
        return [{"title": r.get("title"), "start": r.get("eventstartdate"), "end": r.get("eventenddate"),
                 "addr": r.get("addr1")} for r in _items(body)]

    events = _cached(f"events_{today.isoformat()}", 12, fetch)
    until = (today + timedelta(days_ahead)).strftime("%Y%m%d")
    now = today.strftime("%Y%m%d")
    return [e for e in events if (e["end"] or "") >= now and (e["start"] or "") <= until]


# ---------------------------------------------------------------
# 한국천문연구원 특일 정보 (공휴일)
# ---------------------------------------------------------------

def holidays(days_ahead=30):
    today = date.today()
    months = sorted({(d.year, d.month) for d in (today, today + timedelta(days_ahead))})

    def fetch(y, m):
        url = os.getenv("KASI_SPCDE_ENDPOINT", "https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService") + "/getRestDeInfo"
        body = _get_json(url, {"solYear": y, "solMonth": f"{m:02d}", "_type": "json", "numOfRows": 50},
                         "KASI_SPCDE_API_KEY", key_param="ServiceKey")["response"]["body"]
        return [{"date": str(r["locdate"]), "name": r["dateName"]} for r in _items(body) if r.get("isHoliday") == "Y"]

    result = []
    for y, m in months:
        result += _cached(f"holidays_{y}_{m:02d}", 24 * 7, lambda y=y, m=m: fetch(y, m))
    start, until = today.strftime("%Y%m%d"), (today + timedelta(days_ahead)).strftime("%Y%m%d")
    return [h for h in result if start <= h["date"] <= until]
