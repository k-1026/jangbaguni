"""시연용 가상 가게 1년 치 더미 데이터 만들기 → data/dummy_store/ (+ --apply 로 Supabase 시연 가게에 넣기).

실제 사장님의 메뉴 · 영수증 · 판매량을 구할 수 없어서, 판매량 학습을 시연하려고 만든 **가상 데이터**다.
- 가게: 살피 시연 한식당 (대구 달서구, 일요일 휴무, seed.sql 의 시연 가게)
- 메뉴 5개 · 레시피 (seed 의 3개 + 김치볶음밥 · 순두부찌개)
- 판매량: 1년 치 (홀 · 배달). 아래 '판매량을 움직이는 요인'을 일부러 넣고, 나머지는 무작위 흔들림
- 영수증: 매주 월요일 1장. 야채 단가는 **실제 대구 북부도매시장 경락가** × 가게 웃돈, 그 밖의 재료는 기준값에서 천천히 움직임
  seed.sql 의 영수증 4장(10/12 · 10/19 · 10/26 · 11/2)은 시연용 영수증 그림과 같아야 해서 그대로 둠
- 재고: 1년 동안 산 양 − 쓴 양을 따라가서 마지막 날 남은 양

판매량을 움직이는 요인 (가상 규칙, 학습 모델이 이걸 찾아내는지 보는 시연용)
  요일(금 · 토 ↑ · 월 ↓) · 공휴일(↓, 설 · 추석 연휴는 휴무) · 기온(추우면 찌개 ↑) · 비(홀 ↓ · 배달 ↑) · 폭염(↓)
  삼성 라이온즈 대구 홈경기(배달 ↑) · 대구 축제 기간(↑) · 월급날 무렵(25~28일 ↑) · 천천히 느는 손님(1년 +6%)
  날씨 · 공휴일 · 홈경기 · 축제 날짜는 실제 자료 (기상청 · 천문연구원 · KBO 일정 · 대구 축제 파일)

실행:  .venv\\Scripts\\python -m demand.dummy_store            (파일만 만들기)
       .venv\\Scripts\\python -m demand.dummy_store --apply    (파일을 만들고 Supabase 시연 가게에 넣기 · 시연 가게 판매 · 영수증 · 재고를 바꿈)
"""
import argparse
import csv
import math
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # 저장소 맨 위
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "dummy_store"
SEED = 20261118

STORE = "00000000-0000-0000-0000-000000000001"
CLOSED_WEEKDAY = 6   # 일요일

# 메뉴 · 판매가 · 하루 기본 그릇 수(홀 + 배달) · 배달 비중 · 찌개인가(추우면 더 팔림)
MENUS = [
    ("김치찌개", 9000, 95, 0.30, True),
    ("제육볶음", 9000, 65, 0.35, False),
    ("된장찌개", 8000, 48, 0.25, True),
    ("김치볶음밥", 8000, 35, 0.45, False),
    ("순두부찌개", 9000, 40, 0.25, True),
]
NEW_MENUS = {"김치볶음밥": "밥", "순두부찌개": "찌개"}

# 1인분 레시피 (재료, 기준 단위 양, 손질 손실). seed.sql 레시피에 공기밥(쌀 110g)을 더하고 제육은 고기 200g · 9,000원으로 (현실에 가깝게, 원가율 40%를 넘는 메뉴가 하나 있게)
RECIPES = {
    "김치찌개": [("배추김치", 0.150, 0), ("돼지고기 앞다리", 0.040, 0), ("두부", 0.25, 0), ("양파", 0.0075, 0),
                ("대파", 0.010, 0.10), ("고춧가루", 0.005, 0), ("쌀", 0.110, 0)],
    "제육볶음": [("돼지고기 앞다리", 0.200, 0), ("양파", 0.080, 0), ("대파", 0.020, 0.10), ("청양고추", 0.005, 0),
                ("고추장", 0.030, 0), ("고춧가루", 0.008, 0), ("깐마늘", 0.010, 0), ("쌀", 0.110, 0)],
    "된장찌개": [("된장", 0.040, 0), ("두부", 0.25, 0), ("애호박", 0.050, 0.05), ("감자", 0.050, 0.15),
                ("양파", 0.030, 0), ("청양고추", 0.003, 0), ("쌀", 0.110, 0)],
    "김치볶음밥": [("쌀", 0.120, 0), ("배추김치", 0.080, 0), ("돼지고기 앞다리", 0.030, 0), ("양파", 0.020, 0),
                 ("대파", 0.010, 0.10), ("계란", 1, 0)],
    "순두부찌개": [("두부", 0.5, 0), ("돼지고기 앞다리", 0.020, 0), ("양파", 0.020, 0), ("대파", 0.010, 0.10),
                 ("고춧가루", 0.006, 0), ("애호박", 0.030, 0.05), ("계란", 1, 0), ("쌀", 0.110, 0)],
}

# 새로 넣는 재료 (items 표에 없을 때만)
NEW_ITEMS = [("계란", "계란·가공", "개", "냉장", False, None)]

# 영수증 품목: 재료 → (영수증에 적는 이름, 1개 = 기준 단위 몇 개). seed.sql item_aliases 와 같은 이름을 씀
PACKS = {
    "양파": ("깐양파 15kg", 15), "돼지고기 앞다리": ("돈앞다리 1kg", 1), "두부": ("국산두부 1모", 1),
    "배추김치": ("포기김치 10kg", 10), "대파": ("대파 1kg", 1), "청양고추": ("청양고추 1kg", 1),
    "애호박": ("애호박 1개", 0.3), "감자": ("감자 10kg", 10), "된장": ("재래된장 2kg", 2),
    "고추장": ("태양초고추장 3kg", 3), "고춧가루": ("고춧가루(중국) 1kg", 1), "깐마늘": ("깐마늘 1kg", 1),
    "쌀": ("쌀 20kg", 20), "계란": ("계란 1판(30구)", 30),
}
NEW_ALIASES = [("계란 1판(30구)", "계란", 30)]
# 오래 두고 쓰는 재료: 다 떨어져 갈 때만 삼 (나머지는 매주 한 주 치)
KEEP = {"된장", "고추장", "고춧가루", "깐마늘", "쌀"}

# 야채 단가 = 실제 북부도매시장 중도매가(상품, kg당) × 가게 웃돈 (웃돈은 seed 10/12 영수증 단가 ÷ 그날 도매가로 맞춤)
WHOLESALE_FILES = {"양파": ("onion", None), "대파": ("green_onion", "대파"), "청양고추": ("cheongyang_pepper", "청양고추"),
                   "감자": ("potato", "수미(노지)"), "애호박": ("zucchini", None)}
# 그 밖의 재료 단가(기준 단위당 원): 날짜별 기준점 사이를 잇고 ±2% 흔들림 (seed 영수증 단가에 맞춤)
ANCHORS = {
    "돼지고기 앞다리": [("2025-11-17", 10800), ("2026-03-01", 10400), ("2026-07-01", 11200), ("2026-10-12", 11500),
                    ("2026-11-02", 12800), ("2026-11-09", 13700), ("2026-11-17", 14400)],
    "두부": [("2025-11-17", 1100), ("2026-04-01", 1200), ("2026-11-17", 1200)],
    "배추김치": [("2025-11-17", 3600), ("2026-02-01", 3700), ("2026-10-12", 3800), ("2026-11-17", 3900)],
    "된장": [("2025-11-17", 6800), ("2026-11-17", 7000)],
    "고추장": [("2025-11-17", 6800), ("2026-11-17", 7000)],
    "고춧가루": [("2025-11-17", 13500), ("2026-11-17", 14000)],
    "깐마늘": [("2025-11-17", 10500), ("2026-11-17", 11000)],
    "쌀": [("2025-11-17", 2900), ("2026-11-17", 3100)],
    "계란": [("2025-11-17", 210), ("2026-03-01", 230), ("2026-11-17", 240)],
}

# seed.sql 영수증 4장 (그림과 같아야 해서 그대로)
SEED_RECEIPTS = {
    "2026-10-12": [("깐양파 15kg", 1, 19500), ("돈앞다리 1kg", 12, 138000), ("국산두부 1모", 45, 54000),
                   ("포기김치 10kg", 2, 76000), ("대파 1kg", 3, 9000), ("청양고추 1kg", 1, 9500), ("애호박 1개", 10, 15000),
                   ("감자 10kg", 1, 26000), ("재래된장 2kg", 1, 14000), ("태양초고추장 3kg", 1, 21000),
                   ("고춧가루(중국) 1kg", 1, 14000), ("깐마늘 1kg", 1, 11000)],
    "2026-10-19": [("깐양파 15kg", 1, 22500), ("돈앞다리 1kg", 12, 144000), ("국산두부 1모", 45, 54000), ("대파 1kg", 3, 9600)],
    "2026-10-26": [("깐양파 15kg", 1, 25500), ("돈앞다리 1kg", 12, 150000), ("국산두부 1모", 45, 54000), ("포기김치 10kg", 2, 76000)],
    "2026-11-02": [("깐양파 15kg", 1, 28500), ("돈앞다리 1kg", 12, 153600), ("대파 1kg", 3, 10500)],
}
SUPPLIER = "동네 식자재 도매상"


# ---------------------------------------------------------------
# 실제 자료: 날씨 · 공휴일 · 홈경기 · 축제 · 도매가
# ---------------------------------------------------------------

def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_weather(start, end):
    """{날짜: (평균 기온, 비 mm, 최고 기온)} — 5년 치 파일 + 그 뒤는 기상청 API."""
    w = {}
    with open(RAW / "1109_5y" / "1109_weather_daegu_daily.csv", encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            d = date.fromisoformat(r["tm"])
            if start <= d <= end:
                w[d] = (_f(r["avgTa"]), _f(r["sumRn"]) or 0.0, _f(r["maxTa"]))
    try:
        from sources import data_sources as ds
        for r in ds.weather_days(30):
            d = date.fromisoformat(r["date"])
            if start <= d <= end and d not in w:
                w[d] = (r["avg_temp"], r["rain_mm"] or 0.0, r["max_temp"])
    except Exception as e:
        print(f"[날씨] API 실패, 파일에 있는 날까지만: {e}")
    return w


def load_holidays(start, end):
    """{날짜: 이름} — 천문연구원 API, 실패하면 seed.sql 과 같은 목록."""
    try:
        from sources import data_sources as ds
        return {date(int(h["date"][:4]), int(h["date"][4:6]), int(h["date"][6:])): h["name"]
                for h in ds.holidays_between(start, end)}
    except Exception as e:
        print(f"[공휴일] API 실패, 기본 목록: {e}")
        base = {"2025-12-25": "기독탄신일", "2026-01-01": "1월1일", "2026-02-16": "설날", "2026-02-17": "설날",
                "2026-02-18": "설날", "2026-03-02": "대체공휴일", "2026-05-05": "어린이날", "2026-05-25": "대체공휴일",
                "2026-06-03": "지방선거", "2026-08-17": "대체공휴일", "2026-09-24": "추석", "2026-09-25": "추석",
                "2026-09-26": "추석", "2026-10-05": "대체공휴일", "2026-10-09": "한글날", "2026-12-25": "기독탄신일"}
        return {date.fromisoformat(k): v for k, v in base.items() if start <= date.fromisoformat(k) <= end}


def load_home_games():
    """삼성 라이온즈 대구 홈경기 날짜 (2026 KBO 일정 파일)."""
    out = set()
    with open(RAW / "1103_kbo_schedule_2026.csv", encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            if r["홈팀"] == "삼성" and r["구장"] == "대구" and r.get("비고", "") != "취소":
                out.add(date.fromisoformat(r["날짜"]))
    return out


def load_festivals():
    """대구 축제 기간 [(시작, 끝, 이름)] — 30일 넘게 이어지는 행사는 뺌 (늘 있는 것과 같아서)."""
    out = []
    with open(RAW / "1103_daegu_festival_data.csv", encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            try:
                a, b = date.fromisoformat(r["축제시작일자"]), date.fromisoformat(r["축제종료일자"])
            except ValueError:
                continue
            if (b - a).days <= 30:
                out.append((a, b, r["축제명"]))
    return out


def load_wholesale(name):
    """{날짜: kg당 중도매가(상품)} — 북부도매시장."""
    fname, variety = WHOLESALE_FILES[name]
    out = {}
    with open(RAW / "1109_5y" / f"1109_price_daily_{fname}.csv", encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            if r["se_nm"] != "중도매" or r["grd_nm"] != "상품" or r["unit"] != "kg" or r["mrkt_nm"] != "북부도매":
                continue
            if variety and r["vrty_nm"] != variety:
                continue
            d = date(int(r["exmn_ymd"][:4]), int(r["exmn_ymd"][4:6]), int(r["exmn_ymd"][6:]))
            out.setdefault(d, float(r["exmn_dd_prc"]) / float(r["unit_sz"]))
    return out


def near(series, d):
    """d 이전 가장 가까운 날의 값 (파일 끝 뒤는 마지막 값)."""
    ks = [k for k in series if k <= d]
    return series[max(ks)] if ks else series[min(series)]


def anchor_price(name, d):
    pts = [(date.fromisoformat(a), v) for a, v in ANCHORS[name]]
    if d <= pts[0][0]:
        return pts[0][1]
    for (a, va), (b, vb) in zip(pts, pts[1:]):
        if a <= d <= b:
            return va + (vb - va) * (d - a).days / max(1, (b - a).days)
    return pts[-1][1]


# ---------------------------------------------------------------
# 만들기
# ---------------------------------------------------------------

def calendar(start, end):
    """날짜마다 판매량 요인 (학습 · 예측이 같이 씀)."""
    weather, hol, games, fests = load_weather(start, end), load_holidays(start, end), load_home_games(), load_festivals()
    big = {d for d, n in hol.items() if "설" in n or "추석" in n}
    cal = {}
    d = start
    while d <= end:
        t, rain, tmax = weather.get(d, (None, 0.0, None))
        cal[d] = {"weekday": d.weekday(), "holiday": d in hol, "holiday_name": hol.get(d, ""),
                  "closed": d.weekday() == CLOSED_WEEKDAY or d in big,
                  "avg_temp": t, "rain_mm": rain, "max_temp": tmax,
                  "home_game": d in games, "festival": any(a <= d <= b for a, b, _ in fests),
                  "payday": 25 <= d.day <= 28}
        d += timedelta(1)
    return cal


def make_sales(cal, rng):
    """[(날짜, 메뉴, 채널, 그릇 수)] — 위 요인을 곱하고 무작위 흔들림."""
    WD = {0: 0.90, 1: 0.95, 2: 1.00, 3: 1.00, 4: 1.22, 5: 1.12}
    start = min(cal)
    rows = []
    for d, c in sorted(cal.items()):
        if c["closed"]:
            continue
        day_shock = rng.gauss(0, 0.05)   # 그날 가게 전체가 같이 흔들림
        t = c["avg_temp"] if c["avg_temp"] is not None else 13.0
        for name, _price, base, deliv, stew in MENUS:
            m = WD[c["weekday"]] * (1 + 0.06 * (d - start).days / 365)
            if c["holiday"]:
                m *= 0.65
            m *= 1 + (0.012 if stew else -0.004) * (15 - t)        # 추우면 찌개 ↑, 더우면 볶음밥 · 제육 조금 ↑
            if c["max_temp"] is not None and c["max_temp"] >= 33:
                m *= 0.90
            if c["festival"]:
                m *= 1.05
            if c["payday"]:
                m *= 1.05
            noise = math.exp(day_shock + rng.gauss(0, 0.08))
            hall_share, deliv_share = 1 - deliv, deliv
            if c["rain_mm"] >= 5:
                hall_share *= 0.80
                deliv_share *= 1.40
            if c["home_game"]:
                deliv_share *= 1.30
            for ch, share in (("홀", hall_share), ("배달", deliv_share)):
                rows.append((d, name, ch, max(0, round(base * m * share * noise))))
    return rows


def make_receipts(cal, sales, rng):
    """매주 월요일 영수증 + 재고 흐름. → (영수증 [(날짜, [(이름, 개수, 금액)])], 남은 재고 {재료: 양})."""
    use = defaultdict(lambda: defaultdict(float))   # 날짜 → 재료 → 쓴 양
    for d, name, _ch, q in sales:
        for item, qty, loss in RECIPES[name]:
            use[d][item] += q * qty / (1 - loss)
    wholesale = {n: load_wholesale(n) for n in WHOLESALE_FILES}
    seed_day = date(2026, 10, 12)
    markup = {}
    for line in SEED_RECEIPTS["2026-10-12"]:
        item = next(i for i, p in PACKS.items() if p[0] == line[0])
        if item in wholesale:
            markup[item] = line[2] / (line[1] * PACKS[item][1]) / near(wholesale[item], seed_day)

    def unit_price(item, d):
        if item in wholesale:
            p = near(wholesale[item], d) * markup[item]
        else:
            p = anchor_price(item, d)
        return p * (1 + rng.gauss(0, 0.02))

    stock = defaultdict(float, {i: 0.0 for i in PACKS})
    receipts = []
    days = sorted(cal)
    for d in days:
        if d.weekday() == 0:   # 월요일: 이번 주(월~토) 쓸 양을 삼
            week = [d + timedelta(k) for k in range(7)]
            need = {i: sum(use[x][i] for x in week) for i in PACKS}
            if str(d) in SEED_RECEIPTS:
                lines = list(SEED_RECEIPTS[str(d)])
                bought = {next(i for i, p in PACKS.items() if p[0] == n): c * PACKS[next(i for i, p in PACKS.items() if p[0] == n)][1]
                          for n, c, _a in lines}
            else:
                lines, bought = [], {}
                for item, (label, size) in PACKS.items():
                    want = need[item] * 1.05 - stock[item]
                    if item in KEEP:
                        want = need[item] * 2 - stock[item] if stock[item] < need[item] * 1.2 else 0
                    if want <= 0:
                        continue
                    count = math.ceil(want / size)
                    price = unit_price(item, d)
                    roll = rng.random()
                    if item in wholesale and roll < 0.08:
                        price *= 1.25 + rng.random() * 0.1   # 가끔 비싸게 삼 (급하게 · 다른 가게)
                    elif item in wholesale and roll < 0.13:
                        price *= 0.88                         # 가끔 싸게 삼 (행사 · 묶음)
                    amount = int(round(price * count * size, -2))
                    lines.append((label, count, amount))
                    bought[item] = count * size
            if lines:
                receipts.append((d, lines))
            for i, q in bought.items():
                stock[i] += q
        for i, q in use[d].items():
            stock[i] = max(0.0, stock[i] - q)
    return receipts, {i: round(q, 3) for i, q in stock.items()}


def build(end=None):
    end = end or date.today() - timedelta(1)
    start = end - timedelta(365)
    rng = random.Random(SEED)
    cal = calendar(start, end)
    sales = make_sales(cal, rng)
    receipts, stock = make_receipts(cal, sales, rng)
    return {"start": start, "end": end, "calendar": cal, "sales": sales, "receipts": receipts, "stock": stock}


def write(data):
    OUT.mkdir(parents=True, exist_ok=True)

    def w(name, header, rows):
        with open(OUT / name, "w", encoding="utf-8-sig", newline="") as fp:
            wr = csv.writer(fp)
            wr.writerow(header)
            wr.writerows(rows)

    w("menus.csv", ["메뉴", "판매가", "하루_기본_그릇수", "배달_비중"], [(n, p, b, dl) for n, p, b, dl, _s in MENUS])
    w("recipes.csv", ["메뉴", "재료", "1인분_양(기준단위)", "손질_손실"], [(m, i, q, l) for m, r in RECIPES.items() for i, q, l in r])
    w("calendar.csv", ["날짜", "요일", "휴무", "공휴일", "평균기온", "비mm", "최고기온", "삼성_홈경기", "축제", "월급날무렵"],
      [(d, "월화수목금토일"[c["weekday"]], int(c["closed"]), c["holiday_name"], c["avg_temp"], c["rain_mm"], c["max_temp"],
        int(c["home_game"]), int(c["festival"]), int(c["payday"])) for d, c in sorted(data["calendar"].items())])
    w("sales_daily.csv", ["날짜", "메뉴", "채널", "그릇수"], data["sales"])
    w("receipts.csv", ["날짜", "판매처", "품목", "개수", "금액"],
      [(d, SUPPLIER, n, c, a) for d, lines in data["receipts"] for n, c, a in lines])
    w("inventory.csv", ["재료", "남은_양(기준단위)"], sorted(data["stock"].items()))


# ---------------------------------------------------------------
# Supabase 시연 가게에 넣기
# ---------------------------------------------------------------

def apply(data):
    from sources import supabase_db as db
    items = {i["name"]: i["id"] for i in db.select("items", select="id,name")}
    new = [{"name": n, "category": c, "base_unit": u, "storage_type": s, "price_comparable": pc, "note": note}
           for n, c, u, s, pc, note in NEW_ITEMS if n not in items]
    if new:
        db.insert("items", new)
        items = {i["name"]: i["id"] for i in db.select("items", select="id,name")}
    db.upsert("item_aliases", [{"alias": a, "item_id": items[i], "base_qty_per_unit": q} for a, i, q in NEW_ALIASES], "alias")

    db.upsert("menus", [{"store_id": STORE, "name": n, "price": p, "category": NEW_MENUS.get(n, "찌개" if s else "볶음"),
                         "is_active": True} for n, p, _b, _d, s in MENUS], "store_id,name")
    menus = {m["name"]: m["id"] for m in db.select("menus", store_id=f"eq.{STORE}", select="id,name")}
    db.upsert("recipe_items", [{"menu_id": menus[m], "item_id": items[i], "qty_per_serving": q, "loss_rate": l}
                               for m, r in RECIPES.items() for i, q, l in r], "menu_id,item_id")

    db.delete("sales_daily", store_id=f"eq.{STORE}")
    rows = [{"store_id": STORE, "menu_id": menus[n], "sale_date": str(d), "channel": ch, "qty": q} for d, n, ch, q in data["sales"]]
    for k in range(0, len(rows), 1000):
        db.insert("sales_daily", rows[k:k + 1000])

    db.delete("purchases", store_id=f"eq.{STORE}", source="eq.demo")
    aliases = {a["alias"]: a for a in db.select("item_aliases", select="alias,item_id,base_qty_per_unit")}
    ps = db.insert("purchases", [{"store_id": STORE, "purchased_on": str(d), "supplier": SUPPLIER,
                                  "total_amount": sum(a for _n, _c, a in lines), "source": "demo"} for d, lines in data["receipts"]])
    by_day = {p["purchased_on"]: p["id"] for p in ps}
    lines = [{"purchase_id": by_day[str(d)], "item_id": aliases[n]["item_id"], "raw_name": n,
              "qty_base": c * float(aliases[n]["base_qty_per_unit"]), "amount": a}
             for d, ls in data["receipts"] for n, c, a in ls]
    for k in range(0, len(lines), 500):
        db.insert("purchase_items", lines[k:k + 500])

    nxt = data["end"] + timedelta((7 - data["end"].weekday()) % 7 or 7)   # 다음 월요일 입고
    db.upsert("inventory", [{"store_id": STORE, "item_id": items[i], "on_hand_qty": q, "next_delivery_date": str(nxt)}
                            for i, q in data["stock"].items()], "store_id,item_id")
    print(f"Supabase 시연 가게에 넣음: 메뉴 {len(menus)}개 · 판매 {len(rows):,}줄 · 영수증 {len(ps)}장 ({len(lines)}줄) · 재고 {len(data['stock'])}개")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Supabase 시연 가게에 넣기")
    ap.add_argument("--end", help="마지막 날 (기본: 어제)")
    a = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    data = build(date.fromisoformat(a.end) if a.end else None)
    write(data)
    days = len({d for d, *_ in data["sales"]})
    total = sum(q for *_, q in data["sales"])
    print(f"{data['start']} ~ {data['end']} · 영업일 {days}일 · 판매 {total:,}그릇 (하루 평균 {total / days:.0f}) · "
          f"영수증 {len(data['receipts'])}장 → {OUT}")
    if a.apply:
        apply(data)


if __name__ == "__main__":
    main()
