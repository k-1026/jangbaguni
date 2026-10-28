# 팀 작업 규칙 (Claude가 따를 것)

자세한 설명은 [README.md](README.md)와 [git-convention.md](git-convention.md) 참고. 팀원 대부분이 비개발자이므로, 안내할 때는 개발 용어 대신 쉬운 말(작업 공간 · 저장 기록 · 합치기 · 할 일 카드)을 쓸 것.

## 지금 이 저장소 — `main` 하나로 운영 (README 규칙)

1. **작업 전 pull**: 작업을 시작하면 먼저 팀원 변경을 받아올 것 (오래된 상태로 작업하면 push 거부 · 충돌이 남).
2. **작은 커밋 · 바로 push**: 커밋 1개 = 의미 있는 변경 1개(노트 1~2개). 하루치를 몰아 커밋하지 않음.
3. **커밋 메시지**: `feat:`(새 파일·기능) / `fix:`(잘못된 내용 수정) / `docs:`(노트·문서)로 시작하는 "종류: 무엇을" 한 줄. 필요하면 둘째 줄부터 이유. 커밋 전에 바뀐 파일 목록을 먼저 보여 줄 것.
   - 예: `docs: 서문시장 노트 추가`, `fix: 근대골목 출처 URL 수정`, `feat: keyword_map 산업 유형 추가`
4. **같은 파일 동시 수정 피하기**: 각자 맡은 하위 폴더 · 파일에만 저장. 공용 파일(`keyword_map.md` · `CLAUDE.md`)은 팀에 알린 뒤 한 사람이 수정.

## 브랜치를 쓰는 앱 저장소부터 (git-convention 규칙)

**작업 공간(브랜치) 구조** — 아래에서 위로 합쳐짐. `main`에서 직접 작업 금지.

```
main (완성본)
└─ integration (모두의 작업을 합쳐 확인)
   └─ 팀원 이름 작업대 (예: kim)
      └─ 할 일 카드별 작업 공간 (예: kim/1-login, kim/2-search-bar)
```

**커밋 메시지**: `종류: 할 일 카드 번호 + 무엇을(한글)`, 종류는 첫 글자만 대문자.
- `Feat`(새로 만들기) — 예: `Feat: S14P11D103-27 로그인 기능 추가`
- `Fix`(고치기) — 예: `Fix: S14P11D103-30 로그인 오류 수정`
- `Refactor`(겉 동작은 같고 속 구조만 정리) — 예: `Refactor: S14P11D103-31 로그인 부분 구조 정리`

**작업 순서**
1. 내 이름 작업대로 이동해 최신 내용 받기: `git checkout kim` → `git pull origin kim`
2. 할 일 카드 하나당 작업 공간 하나 만들기: `git checkout -b kim/2-search-bar`
3. 작업 후 위 규칙대로 커밋
4. GitLab에 올리기: `git push origin kim/2-search-bar`
5. GitLab에서 Merge Request 생성 (Base: `kim` ⬅️ Compare: `kim/2-search-bar`) → 팀원 확인 후 합치기
6. 개인 작업대가 정리되면 `integration`에, 문제없으면 `main`에 반영
