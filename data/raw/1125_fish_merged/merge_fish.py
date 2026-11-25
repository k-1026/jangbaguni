"""수산물 대구 일별 가격 이어 붙이기: 5년 파일(~2025-08-29) + 1119 일별(2025-09-01~) → 학습용 한 파일.
실행 (저장소 맨 위 폴더에서): python data/raw/1125_fish_merged/merge_fish.py
- 앱이 쓰는 값(salpi_agent/sources/data_sources.py EXTRA_ITEMS)과 같은 품목 · 판매 단계 · 단위만 고름
- 날짜마다 같은 조건의 값이 여럿(시장 · 등급)이면 평균. 시장 · 등급이 바뀐 시점은 market · grade 열에 남김 (모델이 단계 변화를 볼 수 있게)
- 합치기 전 두 쪽의 단위가 같은지 확인하고, 다르면 멈춤
"""
import csv, lzma, statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE.parent
OLD = RAW / "1112_2020-2025_농수축산물_일자별_도소매가격.csv.xz"
NEW = RAW / "1119_meat_fish_daily" / "1119_meat_fish_daily_daegu.csv"
OUT = HERE / "1125_fish_daily_merged_daegu.csv"

# 앱 이름: (5년 파일 품목명, 품종명, 조사구분, 등급명 or None, 단위 / 1119 품목명, 품종명 or None, 판매단계, 등급코드 or None)
SERIES = {
    "고등어": dict(old=("고등어", "냉동", "도매", {"중품"}, "10kg"), new=("고등어", "중도매", {"05"}, "10kg")),
    "갈치":   dict(old=("갈치", "냉동", "도매", {"중품", "中"}, "1kg"), new=("갈치", "중도매", {"21"}, "1kg")),
    "명태":   dict(old=("명태", "냉동", "도매", {"중품", "中"}, "20kg"), new=("명태", "중도매", {"21"}, "20kg")),
    "새우":   dict(old=("새우", "흰다리(수입)", "도매", {"중품"}, "2kg"), new=("새우", "중도매", {"05"}, "2kg")),
    "굴":     dict(old=("굴", "굴", "도매", {"상품"}, "1kg"), new=("굴", "중도매", {"04"}, "1kg")),
    "홍합":   dict(old=("홍합", "안깐홍합(냉장)", "도매", {"상품"}, "1kg"), new=("홍합", "중도매", {"04"}, "1kg")),
    "새우젓": dict(old=("새우젓", "새우젓", "소매", {"상품"}, "1kg"), new=("새우젓", "소매", None, "1kg"), only_market="칠성"),   # 소매는 조사 가게가 날마다 달라 평균이 튐 → 칠성 한 곳으로 고정 (2021-02-15~, 앞의 동구는 값 수준이 달라 잇지 않음)
}

def iso(d):  # 20250829 -> 2025-08-29
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else d

rows = defaultdict(list)   # (앱이름, 날짜) -> [(가격, 시장, 등급, 단위, 출처)]
units = defaultdict(set)
with lzma.open(OLD, "rt", encoding="cp949", errors="replace") as f:
    r = csv.reader(f); next(r)
    for x in r:
        if x[5] != "대구":
            continue
        for app, s in SERIES.items():
            name, vr, se, grades, unit = s["old"]
            if s.get("only_market") and x[3] != s["only_market"]:
                continue
            if x[9] == name and x[11] == vr and x[13] == se and x[15] in grades and x[16]:
                # 도매는 도매출하단위(x[19:21]), 소매는 소매출하단위(x[21:23])
                u = (x[19] + x[20]) if se == "도매" else (x[21] + x[22])
                if u != unit and se == "도매":
                    continue
                rows[(app, iso(x[0]))].append((float(x[16]), x[3], x[15], unit, "5년 파일"))
                units[(app, "old")].add(unit)
with open(NEW, encoding="utf-8-sig") as f:
    for x in csv.DictReader(f):
        for app, s in SERIES.items():
            name, se, grades, unit = s["new"]
            if s.get("only_market") and x["mrkt_nm"] != s["only_market"]:
                continue
            if x["name"] == name and x["se_nm"] == se and (grades is None or x["grd_cd"] in grades) and x["price"]:
                rows[(app, x["date"])].append((float(x["price"]), x["mrkt_nm"], x["grd_nm"], x["unit_sz"] + x["unit"], "1119 일별"))
                units[(app, "new")].add(x["unit_sz"] + x["unit"])

for app in SERIES:   # 단위가 한 쪽이라도 다르면 이어 붙이면 안 됨
    assert units[(app, "old")] == units[(app, "new")], (app, units[(app, "old")], units[(app, "new")])

with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(["item", "date", "price", "unit", "stage", "market", "grade", "n_rows", "source"])
    for (app, d) in sorted(rows):
        v = rows[(app, d)]
        stage = SERIES[app]["old"][2]
        mk = "/".join(sorted({m for _, m, *_ in v})); gr = "/".join(sorted({g for _, _, g, *_ in v}))
        w.writerow([app, d, round(statistics.mean(p for p, *_ in v)), v[0][3], stage, mk, gr, len(v), v[0][4]])

# 확인용 요약
for app in SERIES:
    ds = sorted(d for (a, d) in rows if a == app)
    gaps = [(a, b) for a, b in zip(ds, ds[1:]) if (__import__("datetime").date.fromisoformat(b) - __import__("datetime").date.fromisoformat(a)).days > 10]
    print(app, ds[0], ds[-1], f"{len(ds)}일", "10일 넘는 빈 구간:", gaps[:5])
