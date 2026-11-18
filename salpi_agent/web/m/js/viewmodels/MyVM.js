// 마이페이지 상태: 내 정보 · 앱 설치 · 앱 알림(휴대폰 알림)
import { observable, resource } from "../core/observable.js";
import { Api, login, logout } from "../core/api.js";

const IS_APP = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const IS_IOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
const CAN_PUSH = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

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

  return {
    me, push, installPrompt,
    signedIn: () => !!login(),
    isApp: IS_APP, isIOS: IS_IOS, canPush: CAN_PUSH,
    load() { return me.load(); },
    async refreshPush() {
      if (!CAN_PUSH() || !login()) { push.set({ ...push.get(), loading: false }); return; }
      try {
        const [st, s] = await Promise.all([Api.pushStatus(), sub().catch(() => null)]);
        push.set({ loading: false, on: !!s && Notification.permission === "granted", ready: st.ready, publicKey: st.public_key,
          denied: Notification.permission === "denied", last: st.last_sent, devices: st.devices, error: null });
      } catch (e) { push.set({ ...push.get(), loading: false, error: e.message }); }
    },
    async enablePush() {
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
