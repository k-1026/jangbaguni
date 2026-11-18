// 화면 파일(mobile/)을 앱 안에 넣을 www/ 로 복사 (서버가 /mobile/ · /static/ 으로 내주는 모양 그대로)
import { cpSync, rmSync, mkdirSync, existsSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = join(dirname(fileURLToPath(import.meta.url)), "..");   // salpi_agent/mobile
const www = join(here, "www");
rmSync(www, { recursive: true, force: true, maxRetries: 8, retryDelay: 300 });   // Android Studio 가 폴더를 잠깐 잡고 있어도 다시 시도
mkdirSync(join(www, "mobile"), { recursive: true });

cpSync(join(here, "index.html"), join(www, "index.html"));
cpSync(join(here, "app.css"), join(www, "mobile", "app.css"));
cpSync(join(here, "js"), join(www, "mobile", "js"), { recursive: true });
cpSync(join(here, "img"), join(www, "mobile", "img"), { recursive: true });
const webImg = join(here, "..", "web", "img");
if (existsSync(webImg)) cpSync(webImg, join(www, "static", "img"), { recursive: true });
// 앱 알림(Firebase): google-services.json 이 있는 빌드만 알림 켜기를 보여 줌 (없이 켜면 앱이 꺼짐)
const hasFirebase = existsSync(join(here, "android", "app", "google-services.json"));
writeFileSync(join(www, "mobile", "js", "core", "build.js"), `export const HAS_FIREBASE = ${hasFirebase};\n`);
console.log(`www/ 준비 완료 (앱 알림 Firebase: ${hasFirebase ? "있음" : "없음 — android/app/google-services.json 을 넣고 다시 sync"})`);
