/* SYNAPSE EARTH service worker: app shell + map data + visited tiles stay usable with no internet. */
const V='synapse-v18',SHELL=V+'-shell',DATA=V+'-data',TILES=V+'-tiles',MAX_TILES=900;
const PRE=['/','/vendor/leaflet.js','/vendor/leaflet.css','/api/world','/api/config'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(SHELL).then(c=>Promise.all(PRE.map(u=>c.add(u).catch(()=>{})))).then(()=>self.skipWaiting()))});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>!k.startsWith(V)).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
async function trim(cache){const ks=await cache.keys();if(ks.length>MAX_TILES)for(const k of ks.slice(0,ks.length-MAX_TILES))await cache.delete(k)}
async function netFirst(req,name){const c=await caches.open(name);try{const r=await fetch(req);if(r&&r.ok)c.put(req,r.clone());return r}catch(e){const h=await c.match(req,{ignoreSearch:false});if(h)return h;throw e}}
async function swr(req,name){const c=await caches.open(name),h=await c.match(req);const p=fetch(req).then(r=>{if(r&&r.ok)c.put(req,r.clone());return r}).catch(()=>null);return h||(await p)||new Response('{"error":"offline"}',{status:503,headers:{'Content-Type':'application/json'}})}
async function cacheFirst(req,name,limit){const c=await caches.open(name),h=await c.match(req);if(h)return h;try{const r=await fetch(req);if(r&&(r.ok||r.type==='opaque')){c.put(req,r.clone());if(limit)trim(c)}return r}catch(e){return new Response('',{status:504})}}
self.addEventListener('fetch',e=>{
  const r=e.request;if(r.method!=='GET')return;const u=new URL(r.url);
  if(u.origin===location.origin){
    if(u.pathname==='/'||u.pathname==='/index.html')return e.respondWith(netFirst(r,SHELL).catch(()=>caches.match('/')));
    if(u.pathname.startsWith('/vendor/'))return e.respondWith(cacheFirst(r,SHELL));
    if(/^\/api\/(world|config|regions|region-info|region-roads|catalog)/.test(u.pathname))return e.respondWith(swr(r,DATA));
    return;
  }
  if(/(tile\.openstreetmap\.org|arcgisonline\.com)/.test(u.hostname))return e.respondWith(cacheFirst(r,TILES,true));
});
