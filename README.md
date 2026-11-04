# 작업 규칙

브랜치 · PR로 작업합니다. 자세한 규칙은 [git-convention.md](git-convention.md).

## 1. 기능 하나 = 브랜치 하나
- `main`(실제 사이트) · `dev`(개발 통합)에는 직접 올리지 않음
- 최신 `dev`에서 기능 브랜치를 만들어 작업: `fe/feat/기능명` · `be/feat/기능명` · `fe/fix/이슈명` · `docs/작업명`

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
- push한 사람이 `dev`로 가는 PR을 직접 만듦 — 제목 `[FE : feat] 작업 내용`, 본문 양식은 자동으로 뜸
- 팀원 1명 확인 → **Merge pull request** → **Delete branch**
- Claude Code에 **"다 했어, 커밋 푸시해줘"** 라고 하면 커밋 → push → PR 등록 → 머지 안내까지 진행해 줌

## 5. 같은 파일 동시 수정 피하기
- 각자 맡은 기능 · 폴더만 고침. 같은 파일을 고칠 땐 미리 팀에 알림
- 공용 파일(`keyword_map.md` · `claude.md` · `git-convention.md`)은 팀에 알린 뒤 한 사람이 수정
