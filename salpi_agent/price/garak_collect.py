"""가락시장 야채 값을 매일 받아 보관함에 쌓기 — "가락에서 먼저 올랐어요" 문구 · 가락 선행 실험용.

실행:  .venv\\Scripts\\python -m price.garak_collect              (최근 14일 받아 보관함 forecast/garak_recent.json 에 합침)
       .venv\\Scripts\\python -m price.garak_collect --dry-run    (보관함에 올리지 않고 받은 결과만 보기)
       .venv\\Scripts\\python -m price.garak_collect --days 30
매일 새벽 GitHub 예약 실행(.github/workflows/daily-learn.yml)이 학습 전에 돌림.

- 자료: aT 일별 도·소매 가격(perDay = KAMIS 조사가) 서울(sgg_cd 1101) 가락도매 중도매 "상품" — 대구 학습 자료(1109_5y)와 같은 출처 · 같은 정의
- perDay는 약 2일 늦게 올라오므로 매번 최근 14일을 다시 받아 덮어씀 (늦게 올라온 값 · 고쳐진 값 반영)
- 보관 모양: {"updated": 날짜, "items": {대구 품목 이름: {"2026-11-21": [[품종, 단위, 단위크기, 값], ...]}}} — 120일치만 남김
- 품목: 가락 선행 시차 표(plan/forecast/1123_garak_lead_lag.md)와 같은 야채 14품목
"""
import argparse
import json
import os
from datetime import timedelta

from sources import data_sources as ds
from sources import supabase_db

BUCKET, FILE = "models", "forecast/garak_recent.json"   # 학습 모델과 같은 비공개 보관함
KEEP_DAYS = 120
SEOUL_SGG = "1101"
# 대구 품목 이름 → (가락 품목 이름, 분류 코드, 품목 코드).  분류 코드 = 품목 코드 첫 자리 + "00"
ITEMS = {"양파": ("양파", "200", "245"), "대파": ("파", "200", "246"), "배추": ("배추", "200", "211"), "무": ("무", "200", "231"),
         "양배추": ("양배추", "200", "212"), "감자": ("감자", "100", "152"), "당근": ("당근", "200", "232"),
         "애호박": ("호박", "200", "224"), "오이": ("오이", "200", "223"), "깻잎": ("깻잎", "200", "253"),
         "상추": ("상추", "200", "214"), "시금치": ("시금치", "200", "213"), "토마토": ("토마토", "200", "225"),
         "청양고추": ("풋고추", "200", "242")}


def fetch_item(ctgry, item, start, end):
    url = os.getenv("AT_PERDAY_ENDPOINT", "https://apis.data.go.kr/B552845/perDay") + "/price"
    out, page = [], 1
    while True:
        body = ds._get_json(url, {"returnType": "JSON", "numOfRows": 1000, "pageNo": page,
                                  "cond[exmn_ymd::GTE]": start.strftime("%Y%m%d"), "cond[exmn_ymd::LTE]": end.strftime("%Y%m%d"),
                                  "cond[ctgry_cd::EQ]": ctgry, "cond[item_cd::EQ]": item, "cond[sgg_cd::EQ]": SEOUL_SGG},
                            "AT_PERDAY_API_KEY")["response"]["body"]
        rows = ds._items(body)
        out += rows
        if page * 1000 >= int(body.get("totalCount") or 0) or not rows:
            return out
        page += 1


def collect(days):
    end = ds.kst_today()
    start = end - timedelta(days)
    got = {}
    for name, (_, ctgry, code) in ITEMS.items():
        for r in fetch_item(ctgry, code, start, end):
            if r.get("mrkt_nm") == "가락도매" and r.get("se_nm") == "중도매" and r.get("grd_nm") == "상품":
                d = r["exmn_ymd"]
                iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                got.setdefault(name, {}).setdefault(iso, []).append([r.get("vrty_nm"), r.get("unit"), r.get("unit_sz"), float(r["exmn_dd_prc"])])
    return got, end


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    got, end = collect(a.days)
    for name in ITEMS:
        days = sorted(got.get(name, {}))
        print(f"  {name}: {len(days)}일 ({days[0]} ~ {days[-1]})" if days else f"  {name}: 받은 값 없음")
    if a.dry_run:
        print("dry-run: 보관함에 올리지 않음")
        return
    raw = supabase_db.download(BUCKET, FILE)
    store = json.loads(raw) if raw else {"updated": None, "items": {}}
    for name, by_day in got.items():
        store["items"].setdefault(name, {}).update(by_day)    # 받은 날짜는 통째로 덮어씀
    cut = (end - timedelta(KEEP_DAYS)).isoformat()
    store["items"] = {n: {d: v for d, v in sorted(by.items()) if d >= cut} for n, by in store["items"].items()}
    store["updated"] = end.isoformat()
    supabase_db.upload(BUCKET, FILE, json.dumps(store, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), "application/json")
    print(f"보관함 {FILE} 저장 ({sum(len(v) for v in store['items'].values())}건)")


if __name__ == "__main__":
    main()
