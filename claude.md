# 팀 작업 규칙 (Claude가 따를 것)

자세한 설명은 [git-convention.md](git-convention.md) 참고. 팀원 대부분이 비개발자이므로, 안내할 때는 개발 용어 대신 쉬운 말(작업 공간 · 저장 기록 · 올리기 · 합치기 요청 · 합치기)을 쓰고, 명령어는 그대로 복사해 쓸 수 있게 보여 줄 것.

## 브랜치 (작업 공간)

```
main  배포 — 실제 사이트(Vercel)에 바로 반영. 직접 push 금지
dev   개발 통합 — 모든 기능 브랜치가 합쳐지는 곳. 직접 push 금지
feat/기능명   새 기능
fix/이슈명    버그 수정
hotfix/이슈명 급한 버그
docs/문서명   research/ · brand/ · ppt/ · 문서(md)
```

- **작업은 기능 단위 브랜치에서만.** 기능 하나 = 브랜치 하나 = PR 하나. 이름은 영어 소문자, 단어 사이 `-`, 이름만 보고 어떤 기능인지 알 수 있게
- 한 브랜치에서 다른 기능을 시작하려 하면 지금 기능을 먼저 PR로 마무리하고 새 브랜치를 만들자고 안내
- 기능 브랜치는 항상 최신 `dev`에서 만든다

## 작업을 시작할 때

1. `git status`로 지금 브랜치와 안 올린 변경 확인
2. `git checkout dev` → `git pull origin dev`
3. 무슨 작업인지 듣고 브랜치 이름을 제안해 만든다: `git checkout -b feat/기능명`
4. 이미 기능 브랜치에서 이어서 하면 `git pull origin dev`로 팀원 변경부터 받는다

## 커밋 규칙

- 형식: `type : (위치/기능) 설명` — type은 소문자 영어, 설명은 한글 가능
- type: `create` `add` `delete` `feat` `fix` `build` `chore` `docs` `style` `refactor` `test` `release` `rename` `comment`
- 예: `feat : web/alert 시세 알림 설정 토글 추가`, `fix : demand/forecast 내일 날짜를 한국 시간 기준으로 수정`, `docs : research/place_tour 서문시장 노트 추가`
- 커밋 1개 = 의미 있는 변경 1개. **커밋 전에 바뀐 파일 목록을 먼저 보여 줄 것**
- `.env`(키 파일) · 키 값은 절대 커밋하지 않는다

## "다 했어" · "커밋 푸시해줘"라고 하면 — PR 등록 · 머지 안내까지 끝까지 진행

1. **브랜치 확인**: `main` · `dev`에 있으면 변경을 그대로 가지고 기능 브랜치로 옮긴다 (`git checkout -b feat/기능명`). 이름은 작업 내용을 보고 정하고 사용자에게 알린다
2. **커밋**: 바뀐 파일 목록을 보여 주고 위 규칙대로 커밋 (의미 단위로 나눠서)
3. **최신 dev 합치기**: `git pull origin dev`. 충돌이 나면 어느 파일 어느 부분인지 알리고, 어느 쪽을 살릴지 확인한 뒤 해결 · 커밋
4. **올리기**: `git push -u origin <브랜치>`
5. **PR 등록** (보내는 곳 `dev`)
   - 제목: `[타입] 기능 이름 + 작업 내용` (예: `[feat] 시세 알림 설정 토글 추가`, `[fix] 채팅창 크기 조절 오류 수정`)
   - 본문: [.github/pull_request_template.md](.github/pull_request_template.md) 양식을 그대로 쓰고 채운다 — 변경 사항 체크, 상세 내용(무엇을 · 왜 · 어떻게 확인했는지), 체크리스트는 **실제로 한 것만** 체크, 화면을 바꿨으면 스크린샷을 붙이라고 안내
   - `gh` CLI가 로그인돼 있으면 `gh pr create --base dev --head <브랜치> --title "<제목>" --body-file <채운 본문 파일>`로 등록하고 PR 주소를 알려 준다
   - 없으면 `https://github.com/k-1026/jangbaguni/compare/dev...<브랜치>?expand=1` 링크를 주고, 채운 제목과 본문을 복사해 붙여 **Create pull request**를 누르라고 안내 (양식은 자동으로 뜸)
6. **머지 안내** (PR 만든 사람이 끝까지)
   - PR 페이지 → **Files changed** 확인 → 팀원 1명 확인(Approve)
   - **Merge pull request** → **Confirm merge** → **Delete branch**
   - "This branch has conflicts"가 뜨면 머지하지 말고 "충돌 풀어줘"라고 말해 달라고 안내
   - 머지된 PR은 Closed 목록에 보라색 **Merged**로 표시된다 (실패 아님)
7. **머지 후 정리**: 사용자가 "머지했어"라고 하면 `git checkout dev` → `git pull origin dev` → `git branch -d <브랜치>` 실행

## 배포 (dev → main)

- 평일 저녁 17:40(한국 시간)에 GitHub가 자동으로 `dev → main` PR을 만들고 머지한다 (`.github/workflows/daily-release.yml`, 배포 담당자 gkdud112837)
- 사용자가 "오늘 배포에 넣어 줘"라고 하면 17:40 전에 dev까지 머지되도록 안내. 급한 배포는 Actions 탭 → "평일 저녁 배포" → Run workflow
- 머지하면 Vercel이 실제 사이트를 다시 배포한다. 기능 브랜치 · dev에 push하면 미리보기 사이트만 생긴다

## 같은 파일 동시 수정 피하기

- 각자 맡은 기능 · 폴더만 고친다. 같은 파일(예: `salpi_agent/web/app.js`)을 여러 명이 고치면 충돌이 나므로 미리 팀에 알린다
- 공용 파일(`keyword_map.md` · `claude.md` · `git-convention.md`)은 팀에 알린 뒤 한 사람이 수정
