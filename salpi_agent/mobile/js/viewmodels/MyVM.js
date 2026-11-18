// 마이페이지 상태: 내 정보 · 앱 설치 · 앱 알림(휴대폰 알림)
import { observable, resource } from "../core/observable.js";
import { Api, login, logout, IS_NATIVE, plugin } from "../core/api.js";
import { HAS_FIREBASE } from "../core/build.js";

const IS_APP = () => IS_NATIVE || matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const IS_IOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
// 휴대폰 알림: 브라우저 · 설치형 웹앱은 웹 푸시, 안드로이드 앱(Capacitor)은 Firebase(FCM)
const CAN_WEB_PUSH = () => !IS_NATIVE && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
const CAN_PUSH = () => (IS_NATIVE ? HAS_FIREBASE : CAN_WEB_PUSH());

// ── 안드로이드 앱 알림 (Firebase) ─────────────────────────────
const FCM_KEY = "salpi_fcm_token";   // 이 기기가 서버에 맡긴 알림 표
const CHANNEL = { id: "salpi_alerts", name: "시세 알림", description: "매일 아침 내 메뉴 재료 시세 · 원가율", importance: 4, visibility: 1 };
const readFcm = () => { try { return localStorage.getItem(FCM_KEY); } catch (e) { return null; } };
const writeFcm = (t) => { try { t ? localStorage.setItem(FCM_KEY, t) : localStorage.removeItem(FCM_KEY); } catch (e) { /* 저장 못 함 */ } };
const nativePush = () => plugin("PushNotifications");
let waitToken = null;   // register() 뒤 'registration' 이벤트로 오는 표를 기다리는 중

// 앱을 켤 때 한 번 (main.js): 표 받기 · 알림 누르면 그 화면 열기 · 바뀐 표는 서버에 다시 맡김
export function initNativePush(openUrl) {
  if (!IS_NATIVE || !HAS_FIREBASE) return;
  const P = nativePush();
  P.addListener("registration", ({ value }) => {
    if (waitToken) { waitToken.resolve(value); waitToken = null; return; }
    if (value && readFcm() && value !== readFcm() && login()) Api.fcmSubscribe(value).then(() => writeFcm(value)).catch(() => {});
  });
  P.addListener("registrationError", (e) => {
    if (waitToken) { waitToken.reject(new Error(`휴대폰이 알림 표를 주지 않았어요 (${e?.error || "알 수 없음"})`)); waitToken = null; }
  });
  P.addListener("pushNotificationActionPerformed", ({ notification }) => openUrl(notification?.data?.url || ""));
  if (readFcm()) P.checkPermissions().then((r) => r.receive === "granted" && P.register()).catch(() => {});
}

function fcmToken() {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => { waitToken = null; reject(new Error("휴대폰이 알림 표를 주지 않았어요. 잠시 뒤 다시 켜 주세요")); }, 20000);
    waitToken = { resolve: (v) => { clearTimeout(t); resolve(v); }, reject: (e) => { clearTimeout(t); reject(e); } };
    nativePush().register().catch((e) => waitToken?.reject(e));
  });
}

// 시세 알림 종류 · 기본값 (데스크톱 웹 마이페이지와 같은 저장 자리 salpi_alert_prefs)
const PREFS_KEY = "salpi_alert_prefs";
export const ALERT_TYPES = [
  ["all", "모든 시세가 오르고 내릴 때", "지난주보다 3% 넘게 움직인 농산물을 알려 드려요"],
  ["up", "값이 오를 때만", "지난주보다 10% 넘게 오른 농산물"],
  ["down", "값이 내렸을 때만", "지난주보다 10% 넘게 내린 농산물"],
  ["unusual", "평소랑 다를 때만", "하루 사이에 평소보다 크게 움직인 농산물"],
  ["weekly", "주 1회 대시보드 리포트", "한 주 시세를 한 번에 정리해 드려요"],
];
const DEFAULT_PREFS = { mine: true, all: false, up: true, down: false, unusual: true, weekly: true };
const readPrefs = () => { try { return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") }; } catch (e) { return { ...DEFAULT_PREFS }; } };

// 안드로이드 크롬이 주는 "앱 설치" 기회 (main.js 가 받아 둠)
export const installPrompt = observable(null);

const b64 = (s) => Uint8Array.from(atob((s + "=".repeat((4 - (s.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));

export function createMyVM() {
  const me = resource(Api.me);
  const push = observable({ loading: true, on: false, ready: false, denied: false, last: null, devices: 0, error: null });

  async function sub() {
    const reg = await navigator.serviceWorker.getRegistration("/");
    return reg ? reg.pushManager.getSubscription() : null;
  }

  const prefs = observable(readPrefs());
  const kakao = observable({ loading: true, error: null, data: null });

  return {
    me, push, installPrompt, prefs, kakao,
    setPref(key, on) {
      const next = { ...prefs.get(), [key]: on };
      try { localStorage.setItem(PREFS_KEY, JSON.stringify(next)); } catch (e) { /* 저장 못 함 */ }
      prefs.set(next);
    },
    async refreshKakao() {
      if (!login()) return;
      try { kakao.set({ loading: false, error: null, data: await Api.kakaoStatus() }); }
      catch (e) { kakao.set({ loading: false, error: e.message, data: null }); }
    },
    async kakaoOn(on) { await Api.kakaoOn(on); return this.refreshKakao(); },
    async kakaoConnect() { return (await Api.kakaoLink()).url; },
    async kakaoTest() { return Api.kakaoTest(); },
    async kakaoUnlink() { await Api.kakaoUnlink(); return this.refreshKakao(); },
    signedIn: () => !!login(),
    isApp: IS_APP, isIOS: IS_IOS, canPush: CAN_PUSH, hasFirebase: HAS_FIREBASE,
    load() { return me.load(); },
    async refreshPush() {
      if (!CAN_PUSH() || !login()) { push.set({ ...push.get(), loading: false }); return; }
      if (IS_NATIVE) {
        try {
          const [st, perm] = await Promise.all([Api.pushStatus(), nativePush().checkPermissions()]);
          push.set({ loading: false, on: perm.receive === "granted" && !!readFcm() && st.fcm_devices > 0, ready: st.fcm_ready,
            denied: perm.receive === "denied", last: st.last_sent, devices: st.devices, error: null });
        } catch (e) { push.set({ ...push.get(), loading: false, error: e.message }); }
        return;
      }
      try {
        const [st, s] = await Promise.all([Api.pushStatus(), sub().catch(() => null)]);
        push.set({ loading: false, on: !!s && Notification.permission === "granted", ready: st.ready, publicKey: st.public_key,
          denied: Notification.permission === "denied", last: st.last_sent, devices: st.devices, error: null });
      } catch (e) { push.set({ ...push.get(), loading: false, error: e.message }); }
    },
    async enablePush() {
      if (IS_NATIVE) {
        try {
          const P = nativePush();
          let perm = (await P.checkPermissions()).receive;
          if (perm !== "granted") perm = (await P.requestPermissions()).receive;
          if (perm !== "granted") return this.refreshPush();
          await P.createChannel(CHANNEL).catch(() => {});
          const tok = await fcmToken();
          await Api.fcmSubscribe(tok);
          writeFcm(tok);
        } catch (e) { push.set({ ...push.get(), error: `앱 알림을 켜지 못했어요: ${e.message}` }); return; }
        return this.refreshPush();
      }
      try {
        if ((await Notification.requestPermission()) !== "granted") return this.refreshPush();
        const reg = await navigator.serviceWorker.register("/sw.js");
        await navigator.serviceWorker.ready;
        const s = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(push.get().publicKey) });
        await Api.pushSubscribe(s.toJSON());
      } catch (e) { push.set({ ...push.get(), error: `앱 알림을 켜지 못했어요: ${e.message}` }); return; }
      return this.refreshPush();
    },
    async disablePush() {
      if (IS_NATIVE) {
        try { await Api.fcmUnsubscribe(readFcm()); } catch (e) { /* 이미 꺼짐 */ }
        await nativePush().unregister().catch(() => {});
        writeFcm(null);
        return this.refreshPush();
      }
      const s = await sub().catch(() => null);
      try { if (s) { await Api.pushUnsubscribe(s.endpoint); await s.unsubscribe(); } } catch (e) { /* 이미 꺼짐 */ }
      return this.refreshPush();
    },
    async testPush() { return Api.pushTest(); },
    async install() {
      const p = installPrompt.get();
      if (!p) return;
      p.prompt();
      await p.userChoice;
      installPrompt.set(null);
    },
    logout() { logout(); me.state.set({ loading: false, error: null, data: null }); },
  };
}

let vm;
export const myVM = () => (vm ||= createMyVM());
