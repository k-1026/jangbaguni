# 화면 ↔ 서버 약속 (자료 모양, 11/16)

> 왜: 서버(이하영)가 끝나길 기다리지 않고 **화면(이성이)을 먼저 만들기 위해**, 서버가 돌려줄 자료 모양을 미리 정함
> 쓰는 법: 화면은 아래 예시를 `salpi_agent/web/mock/<이름>.json` 샘플 파일로 두고 먼저 만듦 → 서버가 생기면 주소만 바꿈 (11/26)
> 모양을 바꿔야 하면: 바꾸는 사람이 이 문서를 먼저 고치고 팀에 알림
> 일정: [README](../README.md)

| # | 화면 | 주소 | 서버 | 화면 | 샘플 파일 |
|---|---|---|---|---|---|
| 1 | 원가율 3가지 제안 · 대체 재료 | `GET /api/costs` | 이하영 11/17 | 이성이 11/18 | `mock/costs.json` |
| 2 | 영수증 싸게 · 비싸게 판정 | `POST /api/receipt/read` · `GET /api/receipt/{id}` 의 `items[].verdict` | 이하영 11/18 | 이성이 11/19 | `mock/receipt_verdict.json` |
| 3 | 더 싼 판매처 | `GET /api/cheaper?item=양파` | 이하영 11/18 | 이성이 11/19 | `mock/cheaper.json` |
| 4 | 재고 입력 · 수정 | `GET /api/inventory` · `PUT /api/inventory/{item_id}` | 이하영 11/18 | 이성이 11/18 | `mock/inventory.json` |
| 5 | 가게 정보 (고정비) | `GET /api/store` · `PUT /api/store` | 이하영 11/24 | 이성이 11/17 | `mock/store.json` |
| 6 | 로그인 상태 | `GET /api/me` | 이하영 11/23 ~ 24 | 이성이 11/24 | `mock/me.json` |
| 7 | 유료 잠금 | 잠긴 기능이 **402** 로 답함 | 이하영 11/24 | 이성이 11/24 | `mock/locked.json` |
| 8 | 앞으로 7일 날씨 | `GET /api/context` 의 `weather_forecast` | **윤가언** 11/17 ~ 18 | 이성이 11/23 | 서버 있음 |
| 9 | AI 예측 성적 카드 | `GET /api/model` | ✅ 있음 | 이성이 11/23 | 서버 있음 |

---

## 1. 원가율 3가지 제안 · 대체 재료 — `GET /api/costs`

`menus[]` 에 지금 있는 값(원가율 · 남는 돈 · swap)에 `suggestions` 가 더해짐. 원가율 40% 이상이면 3가지 다, 아니면 해당하는 것만.

```json
{
  "target_ratio_pct": 30, "alert_ratio_pct": 40,
  "menus": [{
    "menu_id": 2, "menu": "제육볶음", "price": 10000, "cost_per_serving": 4200, "cost_ratio_pct": 42.0, "margin": 5800,
    "verdict": "높아요",
    "swap": {"from": "양파", "to": "양배추", "share_pct": 50, "saving_per_serving": 32, "new_ratio_pct": 41.7, "new_margin": 5832,
             "to_price": 1690, "price_basis": "도매 시세 비율로 환산", "from_change_pct": 10.2, "to_change_pct": 2.6,
             "reason": "양파가 10/12 이후 +77% 올라 1인분 재료비가 30원 늘었어요"},
    "suggestions": [
      {"type": "price", "title": "판매가 조정", "detail": "11,000원으로 올리면 원가율 38.2%", "new_price": 11000, "new_ratio_pct": 38.2},
      {"type": "swap",  "title": "대체 재료", "detail": "양파 절반을 양배추로 바꾸면 1인분 32원 아껴요", "new_ratio_pct": 41.7},
      {"type": "menu",  "title": "마진 좋은 메뉴 밀기", "detail": "된장찌개 원가율 13.7% · 남는 돈 6,918원", "menu": "된장찌개"}
    ]
  }]
}
```

## 2. 영수증 단가 판정 — 영수증 품목마다 `verdict`

```json
{"raw_name": "양파 1망", "item": "양파", "qty_base": 3.0, "unit": "kg", "unit_price": 2300,
 "verdict": {"label": "비싸게", "paid_per_unit": 2300, "unit": "kg",
             "wholesale_per_unit": 902, "shop_per_unit": 1900, "shop": "식봄",
             "diff_won": 1200, "approx": false, "note": "식봄보다 kg당 400원 비싸요"}}
```
- `label`: `싸게` · `보통` · `비싸게` · `모름` (단위를 못 읽으면 모름)
- `approx: true` 면 화면에 "약" 표시 (개 · 포기를 kg로 환산한 값)
- `diff_won`: 싸게 샀으면 아낀 돈(+), 비싸게 샀으면 더 낸 돈

## 3. 더 싼 판매처 — `GET /api/cheaper?item=양파`

```json
{"item": "양파", "unit": "kg", "paid_per_unit": 2300,
 "sellers": [
   {"name": "식봄 · ○○상회 양파 10kg", "price_per_unit": 1650, "approx": false, "url": "https://...", "affiliate": false, "retail": false},
   {"name": "쿠팡 · 양파 3kg", "price_per_unit": 1990, "approx": false, "url": "https://...", "affiliate": true, "retail": true}
 ]}
```
- kg당 가격 순, **산 값보다 싼 곳만**. `affiliate: true` 면 "제휴" 표시, `retail: true` 면 "소매가" 표시
- ✅ 서버 있음 (11/17, `salpi_agent/cheaper.py`). 위 칸에 더해 오는 것:

```json
{"item": "양파", "unit": "kg", "paid_per_unit": 2300, "paid_source": "최근 영수증", "paid_date": "2026-11-04", "paid_approx": false,
 "sellers": [{"name": "식봄 · 피양파 (국내산, 250g내외/개, 15Kg/망)", "price_per_unit": 1199, "approx": false,
              "url": "https://www.foodspring.co.kr/goods/detail/737331", "affiliate": false, "retail": false,
              "pack_price": 17990, "pack": "15kg", "free_delivery": null, "note": null, "saving_per_unit": 1101, "saving_pct": 47.9}],
 "checked": 4, "skipped_unknown_unit": 0, "data_date": "2026-11-17", "message": null}
```
- `paid_source`: `최근 영수증` → 없으면 `대구 소매 평균(KAMIS)` → `?paid=2300` 으로 주면 `직접 입력`
- `approx: true` 면 "약 ○원/kg" (포기 · 개 · 단을 환산표로 바꾼 값, `note`에 근거). 환산이 들어간 비교는 **10% 넘게 쌀 때만** 넣음
- `pack_price` · `pack`: 실제 파는 묶음 값 (예: 15kg 17,990원) — 대용량은 다 못 쓸 수 있으니 함께 보여 주기
- `data_date`: `null` 이면 지금 받은 식봄 값, 날짜면 그날 저장한 값 (식봄이 자동 접속을 막을 때) → "11/17 기준" 표시
- 판매처는 지금 식봄만 (대형마트 참가격에는 야채 · 과일이 없음). 쿠팡 · 네이버는 가격 받기(R8) 뒤에 추가
- 지원 품목이 아니거나 식봄을 못 받으면 `sellers: []` + `message`

## 4. 재고 — `GET /api/inventory` · `PUT /api/inventory/{item_id}`

```json
{"items": [{"item_id": 3, "name": "양파", "unit": "kg", "on_hand": 4.5, "next_delivery_date": "2026-11-20",
            "updated_at": "2026-11-17T09:10:00+09:00", "source": "직접 입력"}]}
```
- 고칠 때 보내는 것: `{"on_hand": 5.0, "next_delivery_date": "2026-11-20"}`
- `source`: `직접 입력` · `영수증` (영수증 저장 시 자동으로 늘어난 경우)

## 5. 가게 정보 (고정비) — `GET /api/store` · `PUT /api/store`

```json
{"name": "살피 시연 한식당", "monthly": {"rent": 1500000, "electricity": 250000, "labor": 3000000, "gas": 150000,
 "delivery": 400000, "water": 60000, "packaging": 120000}, "vat_included": true}
```
- 단위: 원 / 월. 서버가 생기기 전에는 화면에서 브라우저에 임시로 기억해도 됨

## 6. 로그인 상태 — `GET /api/me`

```json
{"logged_in": true, "name": "김사장", "store_id": "00000000-0000-0000-0000-000000000001",
 "plan": "free", "receipt_free_left": 3}
```
- `plan`: `free` · `plus`

## 7. 유료 잠금 — 잠긴 기능이 HTTP **402** 로 답함

```json
{"locked": true, "message": "이 기능은 유료 플랜 사장님만 사용 가능해요", "receipt_free_left": 0, "plan_price": 19900}
```

## 8. 앞으로 7일 날씨 — `GET /api/context` 의 `weather_forecast` (윤가언)

```json
"weather_forecast": [
  {"date": "2026-11-17", "min": 9, "max": 16, "rain_pct_am": 30, "rain_pct_pm": 60, "sky": "비", "sky_am": "흐림", "sky_pm": "비", "source": "단기"},
  {"date": "2026-11-21", "min": -3, "max": 5, "rain_pct_am": 10, "rain_pct_pm": 10, "sky": "맑음", "sky_am": "맑음", "sky_pm": "맑음", "source": "중기"}
]
```
- 오늘 ~ 3일 뒤 = 기상청 단기예보 (격자 nx 89 · ny 90), 4 ~ 6일 뒤 = 중기예보 (육상 11H10000 · 기온 11H10701). 키: `.env` `KMA_VILAGE_*` · `KMA_MID_*`
- ✅ 서버 있음 (11/17). 오늘부터 7일, 날짜 순
- `sky` = 오전 · 오후 중 더 궂은 쪽 (맑음 < 구름많음 < 흐림 < 비 · 눈). 오전 · 오후 따로 쓰려면 `sky_am` · `sky_pm`
- 중기예보 하늘은 "구름많고 비"처럼 길게 올 수 있음. 값이 없으면 `null`
- 예보를 못 받으면 `weather_forecast: []` (나머지 날씨 · 공휴일 · 행사는 그대로 옴) → 화면은 "예보를 불러오지 못했어요"

## 9. AI 예측 성적 카드 — `GET /api/model` (있음)

- `on_screen.야채.metrics` = `{opposite_pct, mae_pp, range_hit_pct}` (지표 3개) · `version` · `trained_at`
- `history[]` = 매일 학습 기록: `diagnosis`(AI 진단) · `experiments[]`(실험 · 교체 여부) · `promoted`
