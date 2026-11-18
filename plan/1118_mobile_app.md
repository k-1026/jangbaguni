# 살피 앱 (설치형) · 앱 알림 (11/18)

> 무엇: 지금 웹사이트를 **휴대폰에 설치하는 앱(PWA)**으로 만들고, 매일 아침 시세 알림을 **휴대폰 알림**으로 보냄
> 왜: 카카오톡 "나에게 보내기"는 카톡 정책상 '나와의 채팅'에 알림이 울리지 않음. 카카오 알림톡(채널)은 사업자등록 · 심사가 필요해 12/4 전엔 어려움
> 코드: [app_push.py](../salpi_agent/account/app_push.py) (알림 보내기) · [web/sw.js](../salpi_agent/web/sw.js) (앱 백그라운드 작업) · [web/manifest.webmanifest](../salpi_agent/web/manifest.webmanifest) (앱 이름 · 아이콘)

---

## 1. 사장님 입장

1. 휴대폰으로 https://jangbaguni-ten.vercel.app 열기 → 로그인
2. **앱 설치**
   - 안드로이드: 마이페이지 › 설정 › "살피 앱 · 알림"의 **앱 설치** 버튼 (안 보이면 크롬 메뉴 ⋮ → "앱 설치")
   - 아이폰: Safari 아래 **공유** → **홈 화면에 추가** (iOS 16.4 이상) → 홈 화면의 살피 아이콘으로 열기
3. 앱에서 마이페이지 › 설정 › **앱 알림 켜기** → "허용"
4. **지금 보내 보기** → 휴대폰에 "살피" 알림이 오면 끝. 다음 날부터 매일 아침 자동 (새벽 학습이 끝난 뒤, 하루 한 번)

알림 내용 = 카카오톡 알림과 같음: 내 메뉴 재료 중 다음 7일 오를 · 내릴 재료, 원가율 40% 넘은 메뉴. 누르면 나의 가게가 열림

## 2. 어떻게 동작하나

| 부분 | 하는 일 |
|---|---|
| 앱 정보 (`/manifest.webmanifest`) | 앱 이름 "살피", 살피 캐릭터 아이콘, 주소창 없이 앱처럼 열기 |
| 백그라운드 작업 (`/sw.js`) | 알림 받기 · 누르면 살피 열기, 화면 파일을 저장해 두어 빨리 열림 (시세 · 원가 자료는 늘 서버에서) |
| 구독 저장 | "앱 알림 켜기" → 휴대폰이 준 알림 주소를 그 계정에 저장 (기기마다, 최대 5대). 앱을 지운 기기는 보낼 때 자동으로 지움 |
| 매일 아침 | `daily-learn.yml` 마지막 단계 → `/api/jobs/alerts` → 앱 알림 + 카카오톡 (켠 사람만, 하루 한 번) |
| 열쇠 | `VAPID_PUBLIC_KEY` · `VAPID_PRIVATE_KEY` (.env · Vercel). **한 번 만들면 바꾸지 않기** — 바꾸면 모든 기기에서 알림을 다시 켜야 함 |

## 3. 안드로이드 설치 파일(APK)이 필요하면 (선택)

플레이 스토어 없이 "진짜 앱 파일"로 나눠 주고 싶을 때:
1. https://www.pwabuilder.com 에 `https://jangbaguni-ten.vercel.app` 넣기 → **Package for stores** → **Android** → 다운로드
2. 받은 압축 파일의 `.apk` 를 휴대폰에 설치 (출처를 알 수 없는 앱 허용)
3. 받은 `assetlinks.json` 을 우리 사이트 `/.well-known/assetlinks.json` 에 올리면 주소창이 사라짐 (Claude에게 요청)
- 플레이 스토어 등록은 개발자 계정(25달러) · 심사 며칠 → 발표 뒤 단계로
- 아이폰 앱 스토어는 맥 · 애플 개발자 계정(연 99달러) 필요 → 아이폰은 "홈 화면에 추가"로

## 4. 발표에서 말하기

- "사장님 휴대폰에 앱으로 설치되고, 매일 아침 내 메뉴 재료 시세가 알림으로 온다"
- 다음 단계: 사업자등록 뒤 **카카오 알림톡(살피 채널)**으로 바꿈 — 알림 내용 · 시간 · 내 메뉴 재료만 고르는 기능은 그대로, 보내는 길만 바뀜

## 5. 안드로이드 스튜디오로 열기 (android/ 폴더, TWA)

살피 모바일 화면(`/m/`)을 크롬 엔진으로 여는 **안드로이드 앱 프로젝트**. 화면 코드는 서버(`salpi_agent/mobile/`)에 있어서, 화면을 고쳐도 앱을 다시 만들 필요가 없음. 사이트 알림이 "살피" 앱 알림으로 옴

1. 안드로이드 스튜디오 → **Open** → 저장소의 `android` 폴더 → Gradle 동기화를 기다림 (처음엔 몇 분, Gradle 8.7 · AGP 8.5 를 받음)
2. 폰 연결: 폰 설정 → 휴대전화 정보 → 빌드번호 7번 → 개발자 옵션 → **USB 디버깅** 켜기 → USB 연결 → "허용"
3. 위쪽 기기 목록에서 내 폰 선택 → **▶ Run** → 폰에 "살피" 앱이 설치되고 열림 (흰 바탕 로고 → 홈 대시보드)
4. 열 주소 바꾸기: `android/app/build.gradle` 맨 위 `siteHost` 한 줄 (합치기 전에는 미리보기 주소 `jangbaguni-git-feat-mobile-app-usagi14.vercel.app`, 합친 뒤에는 `jangbaguni-ten.vercel.app`)
5. **주소창 없애기**: 안드로이드 스튜디오 오른쪽 Gradle → app → Tasks → android → **signingReport** → 나온 `SHA-256` 을 Vercel 환경 변수 `ANDROID_SHA256` 에 넣고 재배포 → 사이트 `/.well-known/assetlinks.json` 에 나오면 앱을 다시 열기 (안 넣어도 앱은 동작, 위에 주소창만 보임)
6. 설치 파일(APK): Build → Build App Bundle(s) / APK(s) → Build APK(s) → `android/app/build/outputs/apk/debug/app-debug.apk`

- 서명 열쇠(.jks)는 저장소에 올리지 않음 (`android/.gitignore`)
- 플레이 스토어에 올리려면 출시용 서명 열쇠로 Build → Generate Signed Bundle, 그 열쇠의 SHA-256 도 `ANDROID_SHA256` 에 쉼표로 추가
