// 살피 모바일 앱 시작점: 스플래시 → 맨 위 헤더 · 아래 네비게이션 → 첫 화면(홈 대시보드)
// 화면(View)은 탭을 처음 열 때만 받아 옴(import) → 첫 실행에 필요한 코드만 받음
import { splash, bottomNav, appHeader } from "./components/index.js";
import { createRouter } from "./core/router.js";
import { homeVM } from "./viewmodels/HomeVM.js";
import { installPrompt, initNativePush } from "./viewmodels/MyVM.js";
import { IS_NATIVE, plugin, APP_OAUTH_PREFIX, finishKakaoLogin, siteUrl } from "./core/api.js";

const sp = splash();
appHeader(document.getElementById("m-head"));
const nav = bottomNav(document.getElementById("m-nav"));
const TAB_OF = { item: "home", login: "my" };   // 이 화면들은 아래 메뉴에서 이 탭이 켜져 있게
const router = createRouter(document.getElementById("m-main"), {
  home: () => import("./views/HomeView.js"),
  mart: () => import("./views/MartView.js"),
  store: () => import("./views/StoreView.js"),
  my: () => import("./views/MyView.js"),
  item: () => import("./views/ItemView.js"),
  login: () => import("./views/LoginView.js"),
}, { onChange: (tab) => nav.select(TAB_OF[tab] || tab) });

// 첫 화면 시세가 오면 스플래시를 내림 (못 받아도 2.5초 뒤 내림)
homeVM().load().finally(sp.hide);
router.start();

// 안드로이드 앱: 카카오 로그인을 마친 브라우저가 com.salpi.mobile://oauth#표 로 앱을 다시 열면 여기서 받아 로그인 처리
if (IS_NATIVE) {
  plugin("App").addListener("appUrlOpen", async ({ url }) => {
    if (!url || !url.startsWith(APP_OAUTH_PREFIX)) return;
    const toastMod = await import("./components/index.js");
    try {
      const r = await finishKakaoLogin(url);
      if (r.ok) { toastMod.toast("로그인했어요"); location.hash = "#/my"; }
      else { toastMod.toast(r.message, 5000); if (r.needStore) window.open(siteUrl("/?page=login"), "_blank"); }
    } catch (err) { toastMod.toast(err.message || "로그인을 하지 못했어요", 5000); }
  });
}

// 안드로이드 앱 알림(Firebase): 알림을 누르면 그 화면으로 (서버가 보내는 주소 /m/#/store → #/store)
initNativePush((url) => { const h = url.includes("#") ? url.slice(url.indexOf("#")) : ""; location.hash = h || "#/home"; });

// 웹으로 열었을 때만: 설치형 앱(PWA) 백그라운드 작업 · "앱 설치" 기회 받아 두기 (안드로이드 앱 안에서는 필요 없음)
if (!IS_NATIVE) {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt.set(e); });
  addEventListener("appinstalled", () => installPrompt.set(null));
}
