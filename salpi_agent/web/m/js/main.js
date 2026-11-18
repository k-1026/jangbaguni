// 살피 모바일 앱 시작점: 스플래시 → 아래 네비게이션 → 첫 화면(홈 대시보드)
// 화면(View)은 탭을 처음 열 때만 받아 옴(import) → 첫 실행에 필요한 코드만 받음
import { splash, bottomNav } from "./components/index.js";
import { createRouter } from "./core/router.js";
import { homeVM } from "./viewmodels/HomeVM.js";
import { installPrompt } from "./viewmodels/MyVM.js";

const sp = splash();
const nav = bottomNav(document.getElementById("m-nav"));
const router = createRouter(document.getElementById("m-main"), {
  home: () => import("./views/HomeView.js"),
  mart: () => import("./views/MartView.js"),
  store: () => import("./views/StoreView.js"),
  my: () => import("./views/MyView.js"),
}, { onChange: (tab) => nav.select(tab) });

// 첫 화면 시세가 오면 스플래시를 내림 (못 받아도 2.5초 뒤 내림)
homeVM().load().finally(sp.hide);
router.start();

// 설치형 앱: 백그라운드 작업(알림 · 빠르게 열기) · 안드로이드 "앱 설치" 기회 받아 두기
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt.set(e); });
addEventListener("appinstalled", () => installPrompt.set(null));
