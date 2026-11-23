"""서울(1101) · 대구(2200) 채소 과거 일별 가격 받기 (aT 일별 도·소매 perDay, KAMIS 조사가) — 대구 예측 정확도 비교용.
쓰는 법: python fetch_veg_past.py            (서울 2016-01~2019-12, 대구 2016-01~2020-12)
월 단위로 저장하고 이미 받은 달은 건너뜀(이어받기). 키는 저장소 루트 .env 에서 읽고 파일에 남기지 않음.
"""
import csv, json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
env = {}
for l in (REPO / ".env").read_text(encoding="utf-8").splitlines():
    m = re.match(r"([A-Z0-9_]+)=(.*)", l.strip())
    if m:
        env[m[1]] = m[2].strip().strip("\"'")
URL = env["AT_PERDAY_ENDPOINT"] + "/price"
KEY = env["AT_PERDAY_API_KEY"]
COLS = ["exmn_ymd", "ctgry_nm", "item_cd", "item_nm", "vrty_cd", "vrty_nm", "grd_nm", "se_nm", "mrkt_nm", "unit", "unit_sz", "exmn_dd_prc"]
# 품목 코드 (서울 합본 1112 기준). 분류 코드는 품목 코드 첫 자리 + "00" (151→100 식량작물, 211→200 채소류, 315→300 특용작물 …)
ITEMS = {"고구마": "151", "감자": "152", "배추": "211", "양배추": "212", "시금치": "213", "상추": "214", "얼갈이배추": "215",
         "오이": "223", "호박": "224", "토마토": "225", "무": "231", "당근": "232", "열무": "233", "건고추": "241", "풋고추": "242",
         "붉은고추": "243", "양파": "245", "파": "246", "생강": "247", "미나리": "252", "깻잎": "253", "부추": "254", "피망": "255",
         "파프리카": "256", "깐마늘(국산)": "258", "양상추": "262", "느타리버섯": "315", "팽이버섯": "316", "새송이버섯": "317",
         "방울토마토": "422", "콩나물": "818"}
PLAN = {"seoul_1101": ("1101", 2016, 2019), "daegu_2200": ("2200", 2016, 2020)}


def get(params):
    for t in range(8):
        try:
            q = urllib.parse.urlencode({"serviceKey": KEY, "returnType": "JSON", "numOfRows": 1000, **params})
            txt = urllib.request.urlopen(URL + "?" + q, timeout=60).read().decode()
            b = json.loads(txt)["response"]
            if b["header"]["resultCode"] not in ("0", "00"):
                raise RuntimeError(b["header"]["resultMsg"])
            return b["body"]
        except Exception as e:
            if t == 7:
                raise
            time.sleep(2 * 2 ** t)


def year_rows(sgg, y, item):
    rows, p = [], 1
    while True:
        b = get({"pageNo": p, "cond[exmn_ymd::GTE]": f"{y}0101", "cond[exmn_ymd::LTE]": f"{y}1231",
                 "cond[ctgry_cd::EQ]": item[0] + "00", "cond[item_cd::EQ]": item, "cond[sgg_cd::EQ]": sgg})
        it = (b.get("items") or {}).get("item", []) if isinstance(b.get("items"), dict) else []
        rows += it
        if p * 1000 >= int(b.get("totalCount") or 0) or not it:
            return rows
        p += 1
        time.sleep(0.2)


for name, (sgg, y0, y1) in PLAN.items():
    out = HERE / name
    out.mkdir(exist_ok=True)
    for y in range(y0, y1 + 1):
        f = out / f"{name}_{y}.csv"
        if f.exists():
            continue
        rows = []
        for nm, code in ITEMS.items():
            got = year_rows(sgg, y, code)
            if not got:
                print("  (없음)", name, y, nm, flush=True)
            rows += got
        with open(f, "w", encoding="utf-8-sig", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(COLS)
            w.writerows([[r.get(c, "") for c in COLS] for r in rows])
        print(name, y, len(rows), "rows", flush=True)
