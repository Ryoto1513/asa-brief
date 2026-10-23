// Offline renderer-string tests. No browser/layout/Safari/network claim.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'../assets/app.js'),'utf8');
const context = vm.createContext({URL, Intl, Date});
// Load actual renderer definitions, not DOM event wiring or startup/network.
vm.runInContext(source.slice(0,source.indexOf('let installEvent=')),context);
const render=(name,value)=>{context.fixture=value;return vm.runInContext(`${name}(fixture)`,context)};
const article={id:'synthetic',quality:'editorial',title:'合成ニュース',lead:'要約の冒頭。'.repeat(100)+'要約の末尾。',selection_reason:'初稿時の参考評価（合成）',blocks:[]};
test('editorial card shows full standalone lead without editorial selection notice',()=>{
 const html=render('artCard',article);
 assert.ok(html.includes(article.lead));assert.ok(!html.includes(article.selection_reason));
 assert.ok(render('editorialNotes',article).includes(article.selection_reason));
});
test('RSS card selection reason unchanged',()=>{
 const rss={...article,quality:'headline'};
 assert.ok(render('artCard',rss).includes(rss.selection_reason));assert.equal(render('editorialNotes',rss),'');
});
test('supplements occur once at footer per block and retain title context',()=>{
 const a={...article,blocks:[{type:'text',title:'事実｜背景',paragraphs:['本文'],note:'補足の内容',refs:[1]},{type:'text',title:'分析｜影響',paragraphs:['分析本文'],note:'補足の内容',refs:[2]}]};
 context.fixture=a;
 const body=vm.runInContext("fixture.blocks.map(b=>richBlock(b,false)).join('')",context);
 assert.ok(!body.includes('補足の内容'));assert.ok(body.includes('href="#source-1"'));assert.ok(body.includes('href="#source-2"'));
 const footer=render('editorialNotes',a);
 assert.equal((footer.match(/補足の内容/g)||[]).length,2);
 assert.ok(footer.includes('事実｜背景'));assert.ok(footer.includes('分析｜影響'));
});
test('empty notes omitted and arbitrary note/title/selection content escaped',()=>{
 assert.equal(render('editorialNotes',{quality:'editorial',blocks:[{note:''},{note:'  '},{}]}),'');
 const html=render('editorialNotes',{quality:'editorial',selection_reason:'<script>x</script>',blocks:[{title:'<img>',note:'<svg onload="bad">&'}]});
 assert.ok(!html.includes('<script>'));assert.ok(!html.includes('<img>'));assert.ok(!html.includes('<svg'));
 assert.ok(html.includes('&lt;svg onload=&quot;bad&quot;&gt;&amp;'));
});
test('table numeric captions units periods and citations remain adjacent',()=>{
 context.fixture={type:'table',title:'事実｜数値',caption:'前年同月比・実績・%',headers:['指標','2026年9月 実績（%）'],rows:[['合成指標','2.1%']],note:'確認補足',refs:[1]};
 const html=vm.runInContext('richBlock(fixture,false)',context);
 for(const text of ['前年同月比・実績・%','2026年9月 実績（%）','2.1%','href="#source-1"'])assert.ok(html.includes(text));
 assert.ok(!html.includes('確認補足'));
});
test('article detail integrates footer notes after body and preserves five tabs',()=>{
 const nodes={'#modal':{innerHTML:''},'#articlePage':{focus(){},addEventListener(){}}};
 context.document={querySelector:s=>nodes[s],body:{style:{}}};
 context.fixture={...article,blocks:[{type:'text',title:'分析｜要点',paragraphs:['本文の結論'],note:'末尾限定の補足',refs:[1]}],sources:[{name:'合成出典',url:'https://example.com/source'}],scope:'確認範囲'};
 vm.runInContext("S.editorial.articles=[fixture];openArticle(fixture.id)",context);
 const html=nodes['#modal'].innerHTML;
 assert.equal((html.match(/末尾限定の補足/g)||[]).length,1);
 assert.ok(html.indexOf('末尾限定の補足')>html.indexOf('class="source-list"'));
 assert.ok(html.indexOf(article.selection_reason)>html.indexOf('class="scope-details"'));
 assert.ok(html.includes('href="#source-1"'));
 const tabs=vm.runInContext('tabs()',context);
 for(const id of ['home','topics','earnings','saved','settings'])assert.ok(tabs.includes(`data-tab="${id}"`));
 assert.equal((tabs.match(/data-tab=/g)||[]).length,5);
});

test('scope blank-line paragraphs remain separate escaped paragraphs, with one fallback',()=>{
 const nodes={'#modal':{innerHTML:''},'#articlePage':{focus(){},addEventListener(){}}};
 context.document={querySelector:s=>nodes[s],body:{style:{}}};
 context.fixture={...article,selection_reason:'',scope:'第一段落\n\n第二段落 <script>bad</script>\r\n\r\n第三段落',sources:[]};
 vm.runInContext("S.editorial.articles=[fixture];openArticle(fixture.id)",context);
 let html=nodes['#modal'].innerHTML;
 assert.ok(html.includes('<p>第一段落</p><p>第二段落 &lt;script&gt;bad&lt;/script&gt;</p><p>第三段落</p>'));
 assert.ok(!html.includes('<script>'));
 context.fixture={...article,selection_reason:'',scope:'',sources:[]};
 vm.runInContext("S.editorial.articles=[fixture];openArticle(fixture.id)",context);
 html=nodes['#modal'].innerHTML;
 const details=html.split('<details class="scope-details">')[1].split('</details>')[0];
 assert.equal((details.match(/<p>/g)||[]).length,1);
 assert.ok(details.includes('RSSの見出し・公開日時・リンクを取得しています。'));
});

test('v2 groups contiguous fact analysis outlook once with nested clean headings',()=>{
 const a={manuscript_version:2,blocks:[
  {type:'text',claim_type:'fact',title:'事実｜1. 何が起きたのか',paragraphs:['fact']},
  {type:'text',claim_type:'fact',title:'事実｜そもそもCPIとは',paragraphs:['background']},
  {type:'text',claim_type:'analysis',title:'分析｜暮らしへの影響',paragraphs:['analysis']},
  {type:'text',claim_type:'prediction',title:'予測｜今後の確認点',paragraphs:['outlook']} ]};
 const html=render('richArticleBlocks',a);
 for(const label of ['事実','分析','今後の見通し'])assert.equal(html.split(`<h2>${label}</h2>`).length-1,1);
 for(const title of ['何が起きたのか','そもそもCPIとは','暮らしへの影響','今後の確認点'])assert.ok(html.includes(`<h3>${title}</h3>`));
 assert.ok(!html.includes('<h3>事実｜'));assert.ok(!html.includes('<h3>1.'));
});
test('noncontiguous claims reopen a group without silently reordering content',()=>{
 const a={manuscript_version:2,blocks:[{type:'text',claim_type:'fact',title:'事実｜A'},{type:'text',claim_type:'analysis',title:'分析｜B'},{type:'text',claim_type:'fact',title:'事実｜C'}]};
 const html=render('richArticleBlocks',a);
 assert.equal(html.split('<h2>事実</h2>').length-1,2);
 assert.ok(html.indexOf('<h3>A</h3>')<html.indexOf('<h3>B</h3>'));
 assert.ok(html.indexOf('<h3>B</h3>')<html.indexOf('<h3>C</h3>'));
});
test('legacy and incomplete claim metadata keep original block heading rendering',()=>{
 const blocks=[{type:'text',title:'事実｜元の見出し',paragraphs:['unchanged']}];
 context.fixture=blocks[0];const expected=vm.runInContext('richBlock(fixture,false)',context);
 assert.equal(render('richArticleBlocks',{blocks}),expected);
 assert.equal(render('richArticleBlocks',{manuscript_version:2,blocks}),expected);
 assert.ok(expected.includes('<h2>事実｜元の見出し</h2>'));
});

test('existing validated v2 fixture uses prediction schema and gets outlook group',()=>{
 const a=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/editorial_v2.json'),'utf8'));
 const html=render('richArticleBlocks',a);
 assert.ok(html.includes('<h2>今後の見通し</h2>'));
 assert.equal((html.match(/<h3>/g)||[]).length,a.blocks.length);
});
