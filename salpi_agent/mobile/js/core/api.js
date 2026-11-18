// Model: 살피 서버 API (서버가 Supabase · 공공 API 와 연결 — 비밀 키는 휴대폰에 두지 않음)
// 로그인 정보는 데스크톱 웹과 같은 자리(salpi_login)를 써서, 한 번 로그인하면 웹 · 앱 모두 로그인 상태
// 안드로이드 앱(Capacitor)에서는 화면 파일이 폰 안에 있으므로 서버 주소(SITE)를 앞에 붙여 부름
import { observable } from "./observable.js";

const LOGIN_KEY = "salpi_login";
const cache = new Map();   // 짧게 보관 (탭을 오갈 때 다시 받지 않게) — 키마다 [시각, 값]

export const IS_NATIVE = !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());
export const SITE = "https://jangbaguni-ten.vercel.app";   // 실제 사이트 (앱이 시세 · 로그인 · 알림을 받아 오는 곳)
const base = IS_NATIVE ? SITE : "";
export const siteUrl = (path) => `${SITE}${path}`;

export function login() {
  try { return JSON.parse(localStorage.getItem(LOGIN_KEY) || sessionStorage.getItem(LOGIN_KEY) || "null"); } catch (e) { return null; }
}

// 지금 로그인한 사람 (헤더 · 화면이 구독해서 로그인 · 로그아웃 때 바로 바뀜)
export const session = observable(login());

export function saveLogin(s, keep = true) {
  const u = { id: s.user.login_id || s.user.name, provider: s.user.provider, name: s.user.name, store: s.user.store_name, store_id: s.user.store_id,
    profile: s.user, access_token: s.access_token, refresh_token: s.refresh_token, expires_at: s.expires_at, at: Date.now() };
  try { (keep ? localStorage : sessionStorage).setItem(LOGIN_KEY, JSON.stringify(u)); } catch (e) { throw new Error("이 기기에서는 로그인 상태를 기억할 수 없어요"); }
  session.set(u);
  return u;
}

// 카카오 로그인 (앱): 폰 브라우저(Chrome 탭)로 카카오 화면을 열고, 승인하면 com.salpi.mobile://oauth#표 로 앱이 다시 열림
// 플러그인은 앱 안에 이미 들어 있음. 이 앱은 Capacitor JS 번들 없이 화면을 불러와 registerPlugin 이 없으므로,
// 네이티브 브리지가 주는 Capacitor.Plugins (없으면 nativePromise / nativeCallback) 를 쓴다
export const plugin = (name) => {
  const C = window.Capacitor;
  if (C.Plugins?.[name]) return C.Plugins[name];
  if (typeof C.registerPlugin === "function") return C.registerPlugin(name);
  return {
    addListener: (eventName, cb) => { C.nativeCallback(name, "addListener", { eventName }, cb); return Promise.resolve({ remove() {} }); },
    open: (opts) => C.nativePromise(name, "open", opts),
  };
};
export const APP_OAUTH_PREFIX = "com.salpi.mobile://oauth";

export function kakaoLoginStart() {
  return plugin("Browser").open({ url: `${SITE}/api/auth/kakao?app=1` });
}

// 앱으로 돌아온 주소에서 로그인 표를 꺼내 저장. 돌려주는 값: { ok: true } | { ok: false, message, needStore? }
export async function finishKakaoLogin(url) {
  const h = new URLSearchParams((url.split("#")[1] || ""));
  if (!h.get("access_token")) return { ok: false, message: h.get("error_description") || "카카오 로그인을 하지 못했어요. 다시 해 주세요." };
  const token = h.get("access_token");
  const r = await fetch(`${base}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
  const user = await r.json().catch(() => ({}));
  if (!r.ok) return { ok: false, message: user.detail || "로그인을 확인하지 못했어요. 다시 해 주세요." };
  if (!user.store_id) return { ok: false, needStore: true, message: "처음이시네요! 웹에서 가게 정보를 한 번 등록하면 앱에서도 쓸 수 있어요" };
  const s = { user, access_token: token, refresh_token: h.get("refresh_token"),
    expires_at: Number(h.get("expires_at")) || Math.floor(Date.now() / 1000) + Number(h.get("expires_in") || 3600) };
  saveLogin(s, true);
  cache.clear();
  return { ok: true };
}

export function logout() {
  const u = login();
  if (u?.access_token) fetch(`${base}/api/auth/logout`, { method: "POST", headers: { Authorization: `Bearer ${u.access_token}` }, keepalive: true }).catch(() => {});
  try { localStorage.removeItem(LOGIN_KEY); sessionStorage.removeItem(LOGIN_KEY); } catch (e) { /* 저장 못 함 */ }
  cache.clear();
  session.set(null);
}

async function call(url, { method = "GET", body, auth = false, signal } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const u = login();
    if (!u?.access_token) throw Object.assign(new Error("로그인이 필요해요"), { status: 401 });
    headers.Authorization = `Bearer ${u.access_token}`;
  }
  const r = await fetch(base + url, { method, headers, body: body ? JSON.stringify(body) : undefined, signal });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.detail || "잠시 뒤 다시 해 주세요"), { status: r.status });
  return data;
}

// 같은 주소를 ttl(초) 동안 다시 받지 않음
export async function get(url, { ttl = 300, auth = false } = {}) {
  const hit = cache.get(url);
  if (hit && Date.now() - hit[0] < ttl * 1000) return hit[1];
  const value = await call(url, { auth });
  cache.set(url, [Date.now(), value]);
  return value;
}

export const post = (url, body, auth = true) => call(url, { method: "POST", body, auth });
export const put = (url, body, auth = true) => call(url, { method: "PUT", body, auth });
export const forget = (prefix) => { for (const k of cache.keys()) if (k.startsWith(prefix)) cache.delete(k); };

// 화면별 API (주소를 한곳에 모아 둠)
export const Api = {
  overview: () => get("/api/overview", { ttl: 600 }).then((d) => d.items || []),
  extra: () => get("/api/meat-seafood", { ttl: 600 }).then((d) => d.items || []),
  mart: () => get("/api/mart", { ttl: 3600 }),
  costs: () => get("/api/costs", { ttl: 120 }),
  demand: () => get("/api/demand", { ttl: 300 }),
  me: () => get("/api/auth/me", { ttl: 120, auth: true }),
  signIn: (id, password, keep = true) => post("/api/auth/login", { id, password }, false).then((s) => saveLogin(s, keep)),
  receiptRead: (image) => post("/api/receipt/read", { image, mime: "image/jpeg" }, false),
  receiptSave: (body) => post("/api/receipt/save", body, false).then((r) => { forget("/api/costs"); forget("/api/demand"); return r; }),
  myItems: () => get("/api/my-items", { ttl: 300, auth: true }),
  pushStatus: () => call("/api/push/status", { auth: true }),
  pushSubscribe: (sub) => post("/api/push/subscribe", sub),
  pushUnsubscribe: (endpoint) => post("/api/push/unsubscribe", { endpoint }),
  pushTest: () => post("/api/push/test", {}),
  kakaoStatus: () => call("/api/kakao/status", { auth: true }),
  kakaoOn: (on) => post("/api/kakao/on", { on }),
  kakaoLink: () => post("/api/kakao/link", {}),
  kakaoTest: () => post("/api/kakao/test", {}),
  kakaoUnlink: () => post("/api/kakao/unlink", {}),
};
