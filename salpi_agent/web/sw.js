// 살피 앱 백그라운드 작업 (서비스 워커) — /sw.js 로 열려서 사이트 전체(/)를 맡음
// 1) 앱 알림: 서버가 보낸 아침 시세 알림(push)을 휴대폰 알림으로 띄우고, 누르면 살피를 엶
// 2) 빠르게 열기: 화면 파일(app.js · style.css · 아이콘)은 저장해 두고 뒤에서 새로 받음. 시세 · 원가 같은 /api 는 늘 서버에서
const CACHE = "salpi-v1";
const SHELL = ["/", "/static/style.css", "/static/app.js", "/static/img/icon-192.png", "/static/img/logo.png",
  "/static/img/salpi_face.png", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => Promise.all(SHELL.map((u) => c.add(u).catch(() => {})))).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;   // 서버 자료는 건드리지 않음
  if (req.mode === "navigate") {   // 화면: 서버 먼저, 인터넷이 끊기면 저장해 둔 첫 화면
    e.respondWith(fetch(req).catch(() => caches.match("/")));
    return;
  }
  // 화면 파일: 저장해 둔 것을 바로 쓰고 뒤에서 새로 받아 둠
  e.respondWith(caches.open(CACHE).then(async (c) => {
    const hit = await c.match(req);
    const fresh = fetch(req).then((r) => { if (r.ok) c.put(req, r.clone()); return r; }).catch(() => hit);
    return hit || fresh;
  }));
});

// 앱 알림: { title, body, url }
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = { body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "살피", {
    body: d.body || "오늘 시세를 확인해 보세요", icon: "/static/img/icon-192.png", badge: "/static/img/badge-96.png",
    tag: d.tag || "salpi-morning", renotify: true, data: { url: d.url || "/?source=push" } }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((ws) => {
    for (const w of ws) if ("focus" in w) { w.navigate(url).catch(() => {}); return w.focus(); }
    return self.clients.openWindow(url);
  }));
});
