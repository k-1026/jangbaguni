// Model: 살피 서버 API (서버가 Supabase · 공공 API 와 연결 — 비밀 키는 휴대폰에 두지 않음)
// 로그인 정보는 데스크톱 웹과 같은 자리(salpi_login)를 써서, 한 번 로그인하면 웹 · 앱 모두 로그인 상태

const LOGIN_KEY = "salpi_login";
const cache = new Map();   // 짧게 보관 (탭을 오갈 때 다시 받지 않게) — 키마다 [시각, 값]

export function login() {
  try { return JSON.parse(localStorage.getItem(LOGIN_KEY) || sessionStorage.getItem(LOGIN_KEY) || "null"); } catch (e) { return null; }
}

export function logout() {
  const u = login();
  if (u?.access_token) fetch("/api/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${u.access_token}` }, keepalive: true }).catch(() => {});
  try { localStorage.removeItem(LOGIN_KEY); sessionStorage.removeItem(LOGIN_KEY); } catch (e) { /* 저장 못 함 */ }
  cache.clear();
}

export const loginUrl = (back) => `/?page=login&next=${encodeURIComponent(back || location.pathname + location.hash)}`;

async function call(url, { method = "GET", body, auth = false, signal } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const u = login();
    if (!u?.access_token) throw Object.assign(new Error("로그인이 필요해요"), { status: 401 });
    headers.Authorization = `Bearer ${u.access_token}`;
  }
  const r = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined, signal });
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
  receiptRead: (image) => post("/api/receipt/read", { image, mime: "image/jpeg" }, false),
  receiptSave: (body) => post("/api/receipt/save", body, false).then((r) => { forget("/api/costs"); forget("/api/demand"); return r; }),
  pushStatus: () => call("/api/push/status", { auth: true }),
  pushSubscribe: (sub) => post("/api/push/subscribe", sub),
  pushUnsubscribe: (endpoint) => post("/api/push/unsubscribe", { endpoint }),
  pushTest: () => post("/api/push/test", {}),
};
