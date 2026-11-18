// 앱 빌드 정보 — 웹(서버)에서는 늘 이 값. 안드로이드 앱은 npm run sync 때 scripts/sync-www.mjs 가 다시 써서 넣음
// HAS_FIREBASE: android/app/google-services.json 이 있어 앱 알림(FCM)을 쓸 수 있는 빌드인지 (없이 알림을 켜면 앱이 꺼짐)
export const HAS_FIREBASE = false;
