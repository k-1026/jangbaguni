# 📚 Git Convention

본 문서는 프로젝트에서 사용하는 **Branch 전략과 Commit Message 규칙**을 정의한다.

> 용어 한 줄 정리
> - **브랜치(branch)**: 원본을 건드리지 않고 따로 작업하는 "복사본 작업 공간"
> - **커밋(commit)**: 작업 중간중간 남기는 "저장 기록" (무엇을 바꿨는지 메모 포함)
> - **푸시(push)**: 내 컴퓨터의 저장 기록을 팀 저장소(GitHub)에 올리기
> - **PR(Pull Request) = MR(Merge Request)**: "내 작업을 합쳐 주세요" 요청서
> - **머지(merge)**: 요청서를 확인한 뒤 실제로 합치기

---

# 🌿 Branch Strategy

본 프로젝트는 **Frontend / Backend 작업을 구분하되 하나의 개발 브랜치(dev)에서 통합하는 방식**을 사용한다.

프론트엔드와 백엔드 작업 구분을 위해 브랜치 이름에
**fe / be prefix**를 사용한다.

---

# 📂 Branch Structure

```
main - 배포 브랜치 (실제 사이트 https://jangbaguni-ten.vercel.app 에 바로 반영)
dev  - 개발 통합 브랜치

fe/feat/*
be/feat/*

fe/fix/*
be/fix/*

hotfix/*
docs/*
```

---

# 📌 Branch 역할

| 브랜치 | 설명 |
| --- | --- |
| main | 최종 배포 브랜치 (실제 사이트) |
| dev | 개발 통합 브랜치 |
| feat | 새로운 기능 개발 |
| fix | 버그 수정 |
| hotfix | 긴급 버그 수정 |
| docs | 문서 작업 (리서치 노트 · 기획 문서 · 발표 자료 포함) |

---

# 🏷 Branch Naming Rule

Frontend와 Backend 작업을 구분하기 위해
브랜치 이름에 **fe 또는 be**를 포함한다.

### 형식

```
fe/feat/기능명
be/feat/기능명

fe/fix/이슈명
be/fix/이슈명
```

- 기능명 · 이슈명은 **영어 소문자**, 단어 사이는 `-` (예: `receipt-detail`)
- **기능 하나 = 브랜치 하나.** 여러 기능을 한 브랜치에 몰아 작업하지 않는다

### 우리 저장소에서 fe / be 구분

| 고치는 곳 | prefix |
| --- | --- |
| `salpi_agent/web/` (화면 · 디자인) | `fe` |
| `salpi_agent/*.py` (서버 · 예측 · 챗봇), `supabase/` (저장소) | `be` |
| `research/` · `brand/` · `ppt/` · 문서(md) | `docs` |

### 예시

```
fe/feat/login-ui
fe/feat/alert-settings

be/feat/auth-api
be/feat/receipt-ocr

fe/fix/chat-resize-bug
be/fix/demand-timezone

docs/git-convention
docs/seomun-market-note
```

---

# 🔄 Branch Workflow

## 1️⃣ dev 브랜치에서 작업 브랜치 생성

```bash
git checkout dev
git pull origin dev
git checkout -b fe/feat/기능명
```

또는

```bash
git checkout -b be/feat/기능명
```

---

## 2️⃣ 기능 개발 진행

- 작업 중간에도 `git pull origin dev`로 팀원 변경을 자주 받아 충돌을 줄인다

---

## 3️⃣ 작업 완료 후 commit

```bash
git add .
git commit -m "feat : auth/login 로그인 API 구현"
```

- `.env`(키 파일)는 절대 커밋하지 않는다

---

## 4️⃣ 원격 저장소 push

```bash
git push origin fe/feat/기능명
```

---

## 5️⃣ Pull Request 생성

- **feature → dev 브랜치로 PR 생성** (push한 사람이 **각자 직접** 작성)
- PR을 만들면 **아래 템플릿이 본문에 자동으로 뜬다** (`.github/pull_request_template.md`)
- 코드 리뷰 후 merge

---

## 6️⃣ Merge (PR 만든 사람이 끝까지)

1. GitHub → **Pull requests** → 내 PR 열기
2. **Files changed**에서 바뀐 내용 확인, 팀원 1명에게 확인(Approve) 받기
3. 아래 초록 버튼 **Merge pull request** → **Confirm merge**
   - "This branch has conflicts"(충돌)가 뜨면 머지하지 말고 Claude에게 "충돌 풀어줘"
4. **Delete branch** 눌러 다 쓴 작업 브랜치 지우기
5. 내 컴퓨터 정리

```bash
git checkout dev
git pull origin dev
git branch -d fe/feat/기능명
```

> 머지가 끝난 PR은 **Closed** 목록으로 옮겨지고 보라색 **Merged** 표시가 붙는다. 실패가 아니다.

---

## 7️⃣ 배포 (dev → main)

- dev에 모인 작업을 실제 사이트에 올릴 때, 배포 담당자가 **dev → main PR**을 만든다
- 제목 예: `[INFRA : release] 11/5 시연 버전 배포`
- 머지하면 Vercel이 실제 사이트(main)를 자동으로 다시 배포한다
- dev나 기능 브랜치에 push하면 Vercel이 **미리보기 사이트**만 따로 만든다 (실제 사이트는 그대로)

---

# 🚨 Branch 규칙

- 직접 **dev · main 브랜치 push 금지**
- 모든 작업은 **feature 브랜치에서 진행**
- PR을 통해서만 merge
- 코드 리뷰 후 merge

> 저장소 관리자 설정 (한 번만): GitHub → Settings → Branches → **Add branch ruleset**
> → 대상 `main`, `dev` → **Require a pull request before merging** 체크 → 저장.
> 이렇게 하면 실수로 직접 push해도 GitHub가 막아 준다.

---

# 📝 Commit Convention

## 📌 Commit Type

| Type 키워드 | 사용 시점 |
| --- | --- |
| create | 프로젝트 최초 생성 |
| add | 새로운 파일 추가 |
| delete | 파일 삭제 |
| feat | 새로운 기능 추가 / 기존 기능 요구사항에 맞게 수정 |
| fix | 기능 버그 수정 |
| build | 빌드 관련 수정 |
| chore | 패키지 매니저 수정, 기타 설정 수정 (.gitignore 등) |
| docs | 문서 수정 |
| style | 코드 스타일, 포맷팅 수정 |
| refactor | 기능 변화 없는 코드 리팩터링 |
| test | 테스트 코드 추가 / 수정 |
| release | 버전 릴리즈 |
| rename | 파일 / 폴더 이름 변경 |
| comment | 주석 추가 / 수정 |

---

# 📌 Commit Message 작성 규칙

- Commit Message는 **최대한 구체적으로 작성**
    - **type 키워드는 소문자 영어로 작성** (설명은 한글 가능)
- **어떤 기능 / 어떤 위치 / 어떤 변경인지 명확하게 작성**
- 커밋 1개 = 의미 있는 변경 1개. 하루치를 몰아 커밋하지 않는다

### 작성 형식

```
type : (위치/기능) + 설명
```

### 예시

```
feat : auth/login 로그인 API 구현
feat : canvas/drawing 감정 드로잉 캔버스 기능 구현

fix : auth/jwt 토큰 만료 처리 오류 수정
fix : websocket/connection 소켓 연결 끊김 문제 해결

add : common/exception 전역 예외 처리 클래스 추가

refactor : user/service 변수명 및 로직 정리

docs : API 명세서 업데이트

style : 코드 포맷팅 수정

comment : login controller 주석 추가
```

우리 저장소 예시

```
feat : web/alert 시세 알림 설정 토글 추가
fix : demand/forecast 내일 날짜를 한국 시간 기준으로 수정
docs : research/place_tour 서문시장 노트 추가
```

---

# 🔀 Merge Request 규칙

모든 작업은 **Merge Request(MR)를 통해 dev 브랜치로 병합**한다. (GitHub에서는 Pull Request라고 부른다)

## MR 제목 규칙

MR 제목은 다음 형식을 따른다.

```
[파트 : 타입] 작업 내용
```

### 예시

- [BE : feat] JWT 발급 로직 구현
- [FE : feat] 로그인 페이지 UI 구현
- [INFRA : chore] GitLab MR 템플릿 추가
- [DOCS : docs] 서문시장 리서치 노트 추가

### 작성 규칙

- 작업 내용은 **가능한 한 한글로 작성**
- **APIResponse, JWT 등 기술 용어는 영어 사용 가능**
- 작업 내용을 **간결하고 명확하게 작성**

## MR 생성 규칙

- feature 브랜치 → dev 브랜치로 MR 생성
- dev / main 브랜치 직접 push 금지
- 코드 리뷰 후 merge 진행
- MR 작성 시 **프로젝트 MR Template을 반드시 사용** (PR을 만들면 자동으로 뜸)

---

# 📄 Merge Request Template 사용

모든 MR은 아래 템플릿을 기반으로 작성한다. 이 템플릿은 `.github/pull_request_template.md`에 있어서 **PR을 만들면 본문에 자동으로 채워진다.**

```
## 🔘 Part
- [ ] FE
- [ ] BE
- [ ] INFRA

---

## 🔍 변경 사항
- [ ] 새로운 기능 추가
- [ ] 버그 수정
- [ ] 코드 리팩토링
- [ ] 문서 수정
- [ ] 기타

---

## 📝 상세 내용
<!-- 변경 사항에 대해 구체적으로 작성해주세요 -->

---

## ✅ 체크리스트
- [ ] 빌드가 성공적으로 수행되었나요?
- [ ] 로컬에서 테스트를 완료했나요?
- [ ] 불필요한 콘솔 로그나 주석을 제거했나요?
- [ ] (필요 시) 문서를 업데이트했나요?

---

## 📸 스크린샷 (UI 변경 시)
<!-- UI 변경 사항이 있다면 전/후 스크린샷을 첨부해주세요 -->
```

---

# 🤖 Claude Code로 작업할 때

작업을 마치고 Claude Code에 **"다 했어, 커밋 푸시해줘"** 라고 말하면 Claude가 아래를 **끝까지** 진행한다. (Claude가 따르는 자세한 순서는 [claude.md](claude.md))

1. 지금 브랜치 확인 — `main` · `dev`에서 작업했으면 기능 브랜치(`fe/feat/…` 등)를 만들어 작업을 옮긴다
2. 바뀐 파일 목록을 보여 주고 규칙대로 커밋
3. `dev` 최신 내용을 받아 합치고(충돌이 나면 알려 주고 같이 해결) push
4. **PR 등록** — dev로 가는 PR을 템플릿을 채워 만든다 (못 만드는 환경이면 PR 만들기 링크와 채운 제목 · 본문을 준다)
5. **머지 안내** — 확인(Approve) → Merge pull request → Delete branch 순서와, 머지 후 내 컴퓨터 정리 명령을 알려 준다
