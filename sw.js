'use strict';
// Namespace includes this app's scope to avoid deleting another Pages app's cache.
const PREFIX='asa-brief-'+encodeURIComponent(self.registration.scope)+'-';
const CACHE=PREFIX+'2.0.0-chat-mirror';
const SHELL=['./','./index.html','./assets/style.css','./assets/app.js','./manifest.webmanifest','./assets/icon-192.png','./assets/icon-512.png'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith(PREFIX)&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{
 const req=e.request,url=new URL(req.url);
 if(req.method!=='GET'||url.origin!==self.location.origin||!url.href.startsWith(self.registration.scope))return;
 const key=new Request(url.origin+url.pathname);
 e.respondWith((async()=>{
   const cache=await caches.open(CACHE);
   try{
     const response=await fetch(req,{cache:'no-store'});
     if(!response.ok)throw Error('http');
     await cache.put(key,response.clone());
     // Limit this app's cached files; saved articles are separately in localStorage.
     const keys=await cache.keys();
     if(keys.length>80){for(const old of keys.filter(k=>new URL(k.url).pathname.includes('/data/chat-briefs/') && !new URL(k.url).pathname.endsWith('/index.json')).slice(0,keys.length-80))await cache.delete(old);}
     return response;
   }catch(_){
     const cached=await cache.match(key);
     if(!cached)return new Response('オフラインです。オンラインで一度アプリを開いてください。',{status:503,headers:{'Content-Type':'text/plain;charset=utf-8'}});
     const headers=new Headers(cached.headers);headers.set('X-Asa-Offline','1');
     return new Response(await cached.arrayBuffer(),{status:200,headers});
   }
 })());
});
