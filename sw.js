const CACHE_NAME = "pwa-cache-v1";
const APP_SHELL = [
  "./",
  "./index.html"
];

// ===== 安裝：預快取核心頁面 =====
self.addEventListener("install", event => {
  self.skipWaiting(); // 新版直接進入等待階段
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(APP_SHELL);
    })
  );
});

// ===== 啟用：清掉舊 cache =====
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.map(key => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim()) // 立即接管頁面
  );
});

// ===== 請求策略 =====
self.addEventListener("fetch", event => {
  const req = event.request;

  // 👉 只處理 GET
  if (req.method !== "GET") return;

  // 👉 HTML（最重要）：永遠優先拿最新
  if (req.headers.get("accept")?.includes("text/html")) {
    event.respondWith(networkFirst(req));
    return;
  }

  // 👉 其他資源：快取優先（加速）
  event.respondWith(cacheFirst(req));
});

// ===== 策略：HTML 用（避免舊版） =====
async function networkFirst(request) {
  try {
    const fresh = await fetch(request);
    const cache = await caches.open(CACHE_NAME);
    cache.put(request, fresh.clone()); // 更新 cache
    return fresh;
  } catch (e) {
    const cached = await caches.match(request);
    return cached || caches.match("./index.html");
  }
}

// ===== 策略：靜態資源用 =====
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const fresh = await fetch(request);
    const cache = await caches.open(CACHE_NAME);
    cache.put(request, fresh.clone());
    return fresh;
  } catch (e) {
    return cached;
  }
}
