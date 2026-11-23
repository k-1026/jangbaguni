"""주산지 날씨 받기 (기상청 ASOS 일자료) — '주산지 날씨' 예측 실험(M5 · R5)용.
실행 (저장소 맨 위 폴더에서): python data/raw/1123_production_weather/fetch_production_weather.py
- 품목별 주산지 관측소: salpi_agent/sources/data_sources.py 의 PRODUCTION_STATIONS (ASOS 관측소가 없는 곳은 가까운 관측소)
- 기간: 2021-01-01 ~ 어제 (대구 북부도매 1109_5y 자료와 같은 시작일)
- 결과: 1123_production_weather_daily.csv — 관측소 · 날짜 한 줄 (stn_id, stn_name, date, 기온 · 강수 · 습도 · 적설) + 1123_production_stations.csv — 품목 → 관측소 연결표
- 키는 .env 의 KMA_ASOS_API_KEY (커밋하지 않음). 관측소 한 곳 5년 치가 2번 호출 안팎 → 전체 20번 안팎"""
import csv, sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "salpi_agent"))
from sources.data_sources import PRODUCTION_STATIONS, kst_today, production_weather_days   # noqa: E402
from datetime import timedelta                                                                # noqa: E402


def main():
    start, end = date(2021, 1, 1), kst_today() - timedelta(1)
    names = {}
    for item, spots in PRODUCTION_STATIONS.items():
        for name, stn in spots:
            names.setdefault(stn, name)
    daily = {}
    for item in PRODUCTION_STATIONS:
        got = production_weather_days(item, start=start, end=end)   # 같은 관측소는 캐시를 같이 써서 한 번만 받음
        for (name, stn), (region, rows) in zip(PRODUCTION_STATIONS[item], got.items()):
            daily.setdefault(stn, rows)
        print(f"{item}: {', '.join(f'{r}({len(v)}일)' for r, v in got.items())}", flush=True)
    with open(HERE / "1123_production_weather_daily.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stn_id", "stn_name", "date", "avg_temp", "min_temp", "max_temp", "rain_mm", "humidity", "snow_cm"])
        for stn, rows in sorted(daily.items()):
            for r in rows:
                w.writerow([stn, names[stn], r["date"], r["avg_temp"], r["min_temp"], r["max_temp"], r["rain_mm"], r["humidity"], r["snow_cm"]])
    with open(HERE / "1123_production_stations.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item", "region", "stn_id"])
        for item, spots in PRODUCTION_STATIONS.items():
            for name, stn in spots:
                w.writerow([item, name, stn])
    print(f"관측소 {len(daily)}곳 · {sum(map(len, daily.values()))}줄 저장")


if __name__ == "__main__":
    main()
