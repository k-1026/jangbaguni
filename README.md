## 📌 팀원별 실습 결과물 안내 (강사님 참고)

본 Repository는 **장바구니 팀의 공통 프로젝트 및 통합 작업 공간**입니다.

11/5~11/6 기업 리서치 및 밸류체인 분석 실습은 팀원별로 개별 진행하였으며, **각 팀원의 세부 실습 과정 및 결과물은 개인 GitHub Repository를 참고해 주시면 감사하겠습니다.**

### 팀원별 GitHub Repository

| 구분 | GitHub Repository | 주요 내용 |
|---|---|---|
| 팀 공통 | [jangbaguni](https://github.com/k-1026/jangbaguni) | 공통 프로젝트 및 통합 작업 |
| 윤가언 | https://github.com/yoonkaeon-netizen/monchichi.git | 개인 실습 결과물(research/company/ibk기업은행 부분만 보시면 됩니다) | 
| 이소정 | https://github.com/so-jung0729/cj_ax.git | 개인 실습 결과물 |
| 이성이 | [Repository 주소 입력](URL 입력) | 개인 실습 결과물 |
| 이하영 | [jangbaguni](https://github.com/k-1026/jangbaguni) | 개인 실습 결과물 |

각 Repository에는 기업 리서치, 출처 검증, 밸류체인 분석 등 개인별 실습 내용과 산출물이 정리되어 있습니다.


# 진행 상황
11/5 과제: onepager.md(8칸 · 충돌 표 · 트랙 과제), verify.md(핵심 사실 5개 원문 대조 + DART 공시 대조 3건), 출처 42~48 추가
11/6 실습: valuechain/ — 활동 후보 → 이해관계자 → 신호 · 마커 → Mermaid v0 → 원페이지 대조 → v1, 발표용 valuechain_v1.html, analysis.md
우선 기회: 대구 도매 시세 7일 예측 · 구매 시점 알림 (영향 9 · 실현 가능성 9)
DART 2024 사업보고서로 대구센터 보유 · 1차 상품 비중 · 수입 비중 · 해외 법인 역할 확인

## 11/5~6 실습 결과 (jangbaguni · CJ프레시웨이)

> 트랙: 데이터 · 서비스(푸드) · 기업: CJ프레시웨이 · 경쟁사: 현대그린푸드 · 파일 위치: [research/company/cj_freshway/](research/company/cj_freshway/)

**11/5 기업 리서치 (Day 9)**
- 후보 3곳 비교 → CJ프레시웨이 선정 ([candidates.md](research/company/candidates.md)), 리서치 질문 10개 ([questions.md](research/company/cj_freshway/questions.md))
- 원문 14건 + 웹 출처를 모아 출처 48건 ([sources.md](research/company/cj_freshway/sources.md)) — **DART 2024 사업보고서(II 사업의 내용 · IX 종속회사) 원문 확보**, 2025 사업연도 보고서 · IR 원문은 아직
- 서브에이전트 4분할(A 사업 모델 · B 재무 · C 보도 · D 산업 · 대구) → 점검표 → D만 재실행 ([parts/](research/company/cj_freshway/parts/))
- 원페이지 8칸 취합 + 트랙 과제(이슈 3개 · 단계별 지표 후보) ([onepager.md](research/company/cj_freshway/onepager.md))
- 핵심 사실 5개 원문 대조 — 5개 모두 일치, DART 공시 대조 3건 추가(대구센터 보유 확인 등) ([verify.md](research/company/cj_freshway/verify.md))

**11/6 밸류체인 맵 (Day 10)** — [valuechain/](research/company/cj_freshway/valuechain/)
- 활동 후보 → 단계 5개 · 이해관계자 → 신호 근거 · 마커(병목 2 · 비용 2 · 기회 3) → Mermaid 초안 v0 → 원페이지 대조(불일치 9건) → v1
- 단계: 산지 · 도매시장 → 매입 · 소싱 → 유통 채널 · 플랫폼 → 주문 · 구매 → 물류 · 배송 (팀 자산: 대구 북부도매시장 · 달서구 한식당 사장님)
- **우선 기회: 대구 도매 시세 7일 예측 · 구매 시점 알림** (영향 9 · 실현 가능성 9)
- 발표용 한 장: [valuechain_v1.html](research/company/cj_freshway/valuechain/valuechain_v1.html) · 근거와 검증: [analysis.md](research/company/cj_freshway/valuechain/analysis.md)

**확인 끝난 것**: Mermaid 그림(v0 · v1) 브라우저에서 오류 없이 그려짐 · DART 2024 사업보고서로 1차 상품 비중 · 수입 비중 · 해외 법인 역할 · 대구센터 · 외상 판매 조건 확인


---

# 폴더 안내

| 폴더 | 내용 |
|---|---|
| [salpi_agent/](salpi_agent/) | 살피 웹사이트 · 챗봇 코드 (Vercel 배포) |
| [plan/](plan/) | 기획서 · 제안서 · 발표 자료 |
| [research/](research/) | 조사 노트 · 기업 리서치 · 키워드 맵 |
| [data/](data/) | 데이터 원본(CSV · JSON) · 시뮬레이션 분석 |
| [brand/](brand/) | 살피 그림 · 로고 · 영상, 챗봇 말투 규칙(`SKILL.md`) |
| [supabase/](supabase/) | DB 설계 · 시작 데이터 |

---

# 작업 규칙

브랜치 · PR로 작업합니다. 자세한 규칙은 [git-convention.md](git-convention.md).

## 1. 기능 하나 = 브랜치 하나
- `main`(실제 사이트) · `dev`(개발 통합)에는 직접 올리지 않음
- 최신 `dev`에서 기능 단위 브랜치를 만들어 작업: `feat/기능명` · `fix/이슈명` · `docs/문서명`
- 기능 하나 = 브랜치 하나 = PR 하나. 다음 기능은 새 브랜치에서

## 2. 작업 전 pull
- Claude Code를 열면 첫 요청은 "dev 최신으로 받아 줘"

## 3. 커밋 메시지
- `type : (위치/기능) 설명` — type은 소문자 영어 (`feat` `fix` `docs` `add` `refactor` …)

```
feat : web/alert 시세 알림 설정 토글 추가
fix : demand/forecast 내일 날짜를 한국 시간 기준으로 수정
docs : research/place_tour 서문시장 노트 추가
```

## 4. PR은 각자 만들고 머지까지
- push한 사람이 `dev`로 가는 PR을 직접 만듦 — 제목 `[feat] 기능 이름 + 작업 내용`, 본문 양식은 자동으로 뜸
- 팀원 1명 확인 → **Merge pull request** → **Delete branch**
- Claude Code에 **"다 했어, 커밋 푸시해줘"** 라고 하면 커밋 → push → PR 등록 → 머지 안내까지 진행해 줌

## 5. 같은 파일 동시 수정 피하기
- 각자 맡은 기능 · 폴더만 고침. 같은 파일을 고칠 땐 미리 팀에 알림
- 공용 파일(`keyword_map.md` · `claude.md` · `git-convention.md`)은 팀에 알린 뒤 한 사람이 수정
