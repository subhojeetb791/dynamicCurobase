const CACHE='dynamic-curo-v7';
const ASSETS=[
  '/',
  '/index.html',
  '/style.css',
  '/portal.css',
  '/app.js',
  '/portal.js',
  '/icons.js',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png'
];
self.addEventListener('install',e=>{
  e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)));
  self.skipWaiting();
});
self.addEventListener('activate',e=>{
  e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET') return;
  // Never cache API responses. Every /api/* GET is an authenticated,
  // per-session payload (profile, attendance, user lists, parent portal).
  // Caching them meant that after logging out on a shared school machine the
  // previous user's data stayed in Cache Storage and was served straight back
  // to the next user whenever the network hiccuped or they went offline.
  // Static shell assets are all this cache is for.
  const url=new URL(e.request.url);
  if(url.origin!==self.location.origin || url.pathname.startsWith('/api/')) return;
  e.respondWith(
    fetch(e.request).then(r=>{
      const clone=r.clone();
      caches.open(CACHE).then(c=>c.put(e.request, clone));
      return r;
    }).catch(()=>caches.match(e.request).then(m=>m||caches.match('/')))
  );
});
