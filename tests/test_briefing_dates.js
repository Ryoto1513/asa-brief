// Dependency-free production mirror date/security tests. No network or browser claim.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const elements=new Map();let now='2026-10-24T03:00:00Z';
class FixedDate extends Date{constructor(...a){super(...(a.length?a:[now]))}static now(){return new Date(now).getTime()}}
const context={console,URL,Intl,Date:FixedDate,Response,TextEncoder,Uint8Array,crypto:crypto.webcrypto,navigator:{onLine:true},location:{protocol:'file:',hostname:''},localStorage:{getItem:()=>null,setItem:()=>{}},document:{body:{classList:{toggle(){}},style:{}},documentElement:{style:{}},querySelector:s=>{if(!elements.has(s))elements.set(s,{innerHTML:'',focus(){}});return elements.get(s)},addEventListener(){}},window:{addEventListener(){},scrollTo(){}},setInterval(){},alert(){}};
vm.createContext(context);vm.runInContext(fs.readFileSync('assets/app.js','utf8').replace('render();refresh(false);',''),context);
const run=s=>vm.runInContext(s,context);
const body='本文\n\n改行を保持';const sha=crypto.createHash('sha256').update(body).digest('hex');
const brief=date=>({schema_version:1,edition_date:date,title:'合成テスト',body_markdown:body,body_sha256:sha,source_updated_at:'2026-10-24T02:00:00Z',blocks:[{type:'heading',level:1,inlines:[{type:'text',text:'見出し'}]},{type:'paragraph',inlines:[{type:'text',text:body}]}]});
const dates=['2026-10-24','2026-10-23'];const index={schema_version:1,dates,editions:dates.map(d=>({edition_date:d,body_sha256:sha,source_updated_at:brief(d).source_updated_at}))};
context.fixture=index;run('S.briefIndex=fixture');
context.fetch=async path=>new Response(JSON.stringify(brief(path.includes('2026-10-23')?'2026-10-23':'2026-10-24')));
(async()=>{
 assert.equal(run("validDate('2026-02-30')"),false);assert.equal(run('localToday()'),'2026-10-24');
 await run("selectArchive('2026-10-24')");assert.equal(run('S.brief.edition_date'),'2026-10-24');assert.ok(run('home()').includes(body));
 assert.equal(run('JSON.stringify(briefingDates())'),JSON.stringify(dates));
 await run("selectArchive('2099-01-01')");assert.equal(run('S.edition'),'2026-10-24');
 await run("selectArchive('2026-10-23')");assert.equal(run('S.edition'),'2026-10-23');
 // Slower old date cannot replace the latest requested date.
 let finish;context.fetch=path=>path.includes('2026-10-23')?new Promise(r=>finish=r):Promise.resolve(new Response(JSON.stringify(brief('2026-10-24'))));
 const pending=run("selectArchive('2026-10-23')");await run("selectArchive('2026-10-24')");finish(new Response(JSON.stringify(brief('2026-10-23'))));await pending;assert.equal(run('S.edition'),'2026-10-24');
 // Wrong date, body hash, source revision all fail closed and retain old selection.
 for(const bad of [{...brief('2026-10-23'),edition_date:'2026-10-22'},{...brief('2026-10-23'),body_markdown:'tampered'},{...brief('2026-10-23'),source_updated_at:'2026-10-24T03:00:00Z'}]){
  context.fetch=async()=>new Response(JSON.stringify(bad));await run("selectArchive('2026-10-23')");assert.equal(run('S.edition'),'2026-10-24');assert.equal(run('S.briefError'),'fetch');
 }
 // Midnight cannot show yesterday underneath Today, including failed refresh.
 run("S.edition='latest'");now='2026-10-24T15:00:01Z';assert.equal(run('localToday()'),'2026-10-25');assert.ok(!run('home()').includes('id="chatBrief"'));assert.equal(run('S.brief'),null);
 context.fetch=async()=>{throw Error('unavailable')};await run('refresh()');assert.ok(!run('home()').includes('id="chatBrief"'));
 run('S.briefIndex={dates:[],editions:[]}');await run("loadBriefDay('latest',++S.editionRequest)");assert.equal(run('S.briefState'),'waiting');assert.ok(run('home()').includes('本日分は未反映'));
 // Renderer only emits explicit safe token types; no raw HTML or private links.
 context.token={type:'text',text:'<img src=x onerror=alert(1)>'};assert.equal(run('briefInlines([token])'),'&lt;img src=x onerror=alert(1)&gt;');
 for(const url of ['javascript:alert(1)','http://example.com','https://chatgpt.com/c/a','https://chat.openai.com/a','https://127.0.0.1','https://example.local/a','https://example.internal/a','https://example.com:444/a','https://user:pass@example.com','https://example.com/?token=secret']){context.url=url;assert.throws(()=>run('briefURL(url)'),undefined,url)}
 assert.throws(()=>run("renderBriefBlocks([{type:'html',html:'<script>'}])"));
 assert.equal(run("briefAlign('center')"),'center');assert.throws(()=>run("briefAlign('background:url(x)')"));
 assert.ok(!run('tabs()').includes('data-tab="topics"'));assert.ok(!run('tabs()').includes('data-tab="saved"'));assert.ok(run('tabs()').includes('data-tab="earnings"'));
 console.log('Chat mirror date, identity, stale-response and security tests passed');
})().catch(e=>{console.error(e);process.exitCode=1});
