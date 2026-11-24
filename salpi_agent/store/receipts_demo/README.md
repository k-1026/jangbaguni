- 용도: 영수증 읽기(OCR) 시험 · 시연용 **가상 영수증** (실제 거래 아님, 이미지마다 "시연용" 표시)
- 품목 · 금액은 `supabase/seed.sql` 의 시연용 영수증 4장(10/12 · 10/19 · 10/26 · 11/2)과 같음
- `answers.json`: 정답지 (OCR 결과와 비교해 정확도 확인)
- `make.py`: 영수증을 다시 만들 때 사용 (HTML을 만들고 크롬으로 캡처)

| 파일 | 종류 | 시험하는 것 |
|---|---|---|
| receipt_1012_statement.png | 도매상 거래명세서 (12품목) | 품목이 많은 표 |
| receipt_1019_statement.png | 도매상 거래명세서 (4품목) | 기본 |
| receipt_1019_photo_tilted.png | 위 명세서를 기울여 흐리게 찍은 사진 | 사진 품질이 나쁠 때 |
| receipt_1026_mart.png | 마트 영수증 | 줄임말 품목명 (깐양파15K) |
| receipt_1102_handwritten.png | 시장 손글씨 간이영수증 | 손글씨 |
| receipt_1104_mart_up.png | 값이 오른 오늘 마트 영수증 (기본 데이터에 없음) | 저장하면 원가율이 오르는 시연 |
| receipt_1005 · 1109_statement.png | 거래명세서 (쌀 · 계란 · 식용유 · 배달비) | 묶음 단위(1판 30구 · 18L) · 재료 아닌 줄 |
| receipt_1116_statement_long.png | 거래명세서 16줄 | 긴 표 |
| receipt_1022_statement_dark · 1123 · 1101_statement_tilted.png | 어둡게 · 기울여 찍은 명세서 | 사진 품질 |
| receipt_1029 · 1111_mart.png | 마트 영수증 (줄임말 · 봉투 · 생수) | 줄임말 재료 맞추기 · 재료 아닌 줄 |
| receipt_1118_mart_tilted · 1120_mart_dark.png | 기울인 · 어두운 마트 영수증 | 사진 품질 |
| receipt_1107 · 1114_handwritten.png · 1121_handwritten_tilted · 1025_handwritten_dark.png | 손글씨 (청양 · 마늘(깐것) 같은 줄임말) | 손글씨 + 사진 품질 |

- 11/24: 20장으로 늘림 (OCR 정확도 시험, [plan/forecast/1124_ocr_accuracy.md](../../../plan/forecast/1124_ocr_accuracy.md)). 정답지에 맞는 재료(`item`) · 기준 양(`qty_base`)도 들어감
- 다시 만들기: `python make.py --png` (아직 그림이 없는 것만 크롬으로 캡처, 만든 html 은 지워도 됨)

- 실제 가게 영수증은 이 폴더에 넣지 말 것 (팀 저장소가 공개라서 누구나 볼 수 있음)
