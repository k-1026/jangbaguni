# 가상 가게 데이터 (시연용 · 실제 가게 아님)

- 만든 곳: [salpi_agent/dummy_store.py](../../salpi_agent/dummy_store.py) — 실제 사장님의 메뉴 · 영수증 · 판매량을 구할 수 없어서 판매량 학습을 시연하려고 만든 **가상 데이터**
- 가게: 살피 시연 한식당 (대구 달서구, 일요일 휴무) · 기간: 1년 (마지막 날 = 만든 날 어제)
- 설명 · 학습 결과: [plan/forecast/1118_demand_learning.md](../../plan/forecast/1118_demand_learning.md)

| 파일 | 내용 |
|---|---|
| menus.csv | 메뉴 5개 · 판매가 · 하루 기본 그릇 수 · 배달 비중 |
| recipes.csv | 1인분 레시피 (기준 단위: kg · 모 · 개) |
| calendar.csv | 날짜별 요인: 휴무 · 공휴일 · 기온 · 비 · 삼성 홈경기 · 축제 · 월급날 무렵 (날씨 · 공휴일 · 경기 · 축제 날짜는 실제 자료) |
| sales_daily.csv | 날짜 · 메뉴 · 채널(홀/배달) · 그릇 수 |
| receipts.csv | 매주 월요일 영수증 줄 (야채 단가는 실제 북부도매시장 경락가 × 가게 웃돈) |
| inventory.csv | 마지막 날 남은 재고 |

다시 만들기: `salpi_agent\.venv\Scripts\python dummy_store.py` (Supabase 시연 가게에도 넣으려면 `--apply`)
