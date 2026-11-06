// 가상 사장님 10명의 행동 성격표. 시뮬레이터만 읽고, 분류기(classify.mjs)는 이 파일을 보지 않는다.
// A: 전형적인 사장님 / B: 판단이 어려운 사장님
//
// plan      발주 습관. days = 매주 정해진 요일(0=일~6=토), every = 평균 며칠마다
// spread    every 발주 간격의 흔들림(일), slip = days 발주가 하루 밀릴 확률
// weekly    주간 식재료 구매액(원), items = 사는 품목 수
// cover     습관 발주량 ÷ 다음 발주까지 실제 필요량 (1 미만이면 자주 모자람)
// visit     하루에 앱에 들어올 확률, accept = 추천을 봤을 때 그대로 따를 확률
// click     알림을 누를 확률, wait = '기다리기'를 누른 뒤 발주를 미룰 확률
// log       실제 발주가 영수증으로 기록될 확률 (우리 앱이 볼 수 있는 몫)
// report    재료가 떨어졌을 때 신고할 확률, urgent = 신고 후 바로 추가 발주할 확률
// declineWeek  이 주부터 접속과 기록이 줄어듦, stopWeek = 이 주부터 기록이 끊김
// monthly   한 달에 한 번만 들어와 가장 최근 영수증 1장만 올림

export const PERSONAS = [
  { id: "S1-A", truth: "S1", name: "수성구 백반집", plan: { every: 2.8, spread: 0.9 }, weekly: 1400000, items: 8, cover: 1.0,
    visit: 0.8, accept: 0.5, click: 0.6, wait: 0.7, log: 0.92, report: 0.5, urgent: 0.5 },
  { id: "S1-B", truth: "S1", name: "달서구 국밥집", plan: { every: 3.5, spread: 1.0 }, weekly: 1300000, items: 8, cover: 1.0,
    visit: 0.6, accept: 0.4, click: 0.3, wait: 0.5, log: 0.92, report: 0.5, urgent: 0.5 },

  { id: "S2-A", truth: "S2", name: "북구 기사식당", plan: { days: [1, 4], slip: 0 }, weekly: 1500000, items: 7, cover: 1.05,
    visit: 0.5, accept: 0.2, click: 0.05, wait: 0.05, log: 0.95, report: 0.4, urgent: 0.4 },
  { id: "S2-B", truth: "S2", name: "동구 분식집", plan: { days: [2, 5], slip: 0.12 }, weekly: 900000, items: 6, cover: 1.05,
    visit: 0.5, accept: 0.4, click: 0.1, wait: 0.1, log: 0.95, report: 0.4, urgent: 0.4 },

  { id: "S3-A", truth: "S3", name: "성서공단 위탁급식", plan: { days: [1], slip: 0.05 }, weekly: 3200000, items: 15, cover: 1.1,
    visit: 0.4, accept: 0.5, click: 0.15, wait: 0.1, log: 0.92, report: 0.3, urgent: 0.3 },
  { id: "S3-B", truth: "S3", name: "칠곡 프랜차이즈 3호점", plan: { every: 14, spread: 1.5 }, weekly: 2600000, items: 14, cover: 1.1,
    visit: 0.3, accept: 0.4, click: 0.15, wait: 0.1, log: 0.92, report: 0.3, urgent: 0.3 },

  { id: "S4-A", truth: "S4", name: "중구 찌개집", plan: { every: 3.5, spread: 1.2 }, weekly: 1200000, items: 8, cover: 0.78,
    visit: 0.6, accept: 0.1, click: 0.15, wait: 0.1, log: 0.92, report: 0.9, urgent: 0.8 },
  { id: "S4-B", truth: "S4", name: "서구 돼지국밥", plan: { every: 3.5, spread: 1.0 }, weekly: 1100000, items: 6, cover: 0.9,
    visit: 0.6, accept: 0.15, click: 0.15, wait: 0.1, log: 0.92, report: 0.9, urgent: 0.8 },

  // S5-A는 처음엔 평범하게 쓰다가 3개월째부터 멀어지는 사장님 (6개월 추적 시험용)
  { id: "S5-A", truth: "S5", name: "남구 한정식", plan: { days: [1, 4], slip: 0.05 }, weekly: 1600000, items: 8, cover: 1.05,
    visit: 0.6, accept: 0.25, click: 0.15, wait: 0.1, log: 0.92, report: 0.4, urgent: 0.4, declineWeek: 9, stopWeek: 17 },
  // S5-B는 월 1회만 들어오지만 장사와 발주는 계속한다. 정답은 "이탈 아님"
  { id: "S5-B", truth: "활동 중", name: "수성구 칼국수", plan: { days: [2], slip: 0.1 }, weekly: 1000000, items: 6, cover: 1.05,
    visit: 0, accept: 0, click: 0.05, wait: 0, log: 0, report: 0, urgent: 0, monthly: true },
];
