"""UI regression checks with routed local assets and controlled data, not live feeds."""
import json,shutil
from test_editorial import legacy_collection
from datetime import datetime,timezone
from pathlib import Path
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1]
OUT=R/'browser-artifacts/v12'
NOW=datetime(2026,10,22,13,0,tzinfo=timezone.utc)
EDITORIAL=legacy_collection()  # fixed three-article regression, not the evolving production library
EDITION={'schema_version':1,'articles':[],'status':'live','generated_at':'2026-10-22T21:45:00+09:00','edition_date':'2026-10-22','markets':[],'notice':'API不使用。テスト用取得状態。'}
HEALTH={'state':'success','feeds':[],'attempted_at':EDITION['generated_at']}

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,executable_path=shutil.which('chromium'),args=['--no-sandbox'])
  context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,service_workers='block')
  errors=[]
  fixture_data={'data/latest.json':EDITION,'data/status.json':HEALTH,'data/editorial.json':EDITORIAL,'data/earnings.json':{'schema_version':1,'items':[],'state':'uninitialized','message':'公開先での初回確認前'}}
  def boot(storage=None):
   pg=context.new_page();pg.clock.install(time=NOW)
   pg.on('pageerror',lambda e:errors.append(str(e)))
   pg.set_content('<meta name="viewport" content="width=device-width, initial-scale=1"><style>'+(R/'assets/style.css').read_text()+'</style><main class="shell" id="app"></main><div id="modal"></div>')
   # Managed Chromium restricts navigations. In-memory fetch/storage fixtures
   # exercise actual UI logic; this does NOT test native origin storage or HTTP.
   pg.add_script_tag(content="window.TEST_DATA="+json.dumps(fixture_data,ensure_ascii=False)+";window.TEST_STORE="+json.dumps(storage or {})+";Object.defineProperty(window,'localStorage',{value:{getItem:k=>window.TEST_STORE[k]??null,setItem:(k,v)=>{window.TEST_STORE[k]=String(v)},removeItem:k=>{delete window.TEST_STORE[k]}}});window.fetch=async(url)=>{let key=String(url).replace(/^\\.\\//,'').split('?')[0];return new Response(JSON.stringify(window.TEST_DATA[key]||{dates:[]}),{status:200,headers:{'Content-Type':'application/json'}})};")
   pg.add_script_tag(content=(R/'assets/app.js').read_text())
   pg.wait_for_selector('.article-card');pg.wait_for_timeout(150)
   return pg
  page=boot()
  assert page.locator('.article-card').count()==2
  first=page.locator('.article-card').first.bounding_box()
  assert first['y']<180,first
  assert page.locator('.audit-footer').first.bounding_box()['y']>844
  assert 'API不使用' not in page.locator('.top').inner_text()
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  page.screenshot(path=str(OUT/'asa_brief_v12_home.png'),full_page=False)
  page.locator('.article-card').first.click()
  assert page.locator('.takeaways').count()==1
  assert page.locator('#articlePage table').count()==3
  assert page.locator('#articlePage .bar-row').count()==2
  assert page.locator('#articlePage .flow-step').count()==4
  assert page.locator('.source-trail').bounding_box()['y']>page.locator('.rich-block').last.bounding_box()['y']
  before=page.locator('.rich-block p').first.evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)')
  assert before==16,before
  page.screenshot(path=str(OUT/'asa_brief_v12_article.png'),full_page=False)
  # Scroll to numeric chart for screenshot (only local rendering, source values were checked separately).
  page.locator('.rich-block.table').first.scroll_into_view_if_needed();page.wait_for_timeout(100)
  page.screenshot(path=str(OUT/'asa_brief_v12_tables.png'),full_page=False)
  # On-article font toggle, no lost story or scroll.
  page.locator('.text-toggle').click();after=page.locator('.rich-block p').first.evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)')
  assert after==19,(before,after)
  assert page.evaluate("localStorage.getItem('asa-large')==='true'")
  assert page.locator('#articlePage').count()==1
  assert page.locator('#articlePage').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
  page.locator('#articlePage [data-bookmark]').click()
  page.locator('[data-close]').first.click();page.locator('.bottom [data-tab="saved"]').click();assert page.locator('.article-card').count()==1
  page.locator('.bottom [data-tab="settings"]').first.click()
  assert page.locator('.font-sample p').evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)')==19
  page.locator('[data-font="normal"]').click();assert page.locator('.font-sample p').evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)')==16
  page.locator('[data-font="large"]').click();state=page.evaluate('window.TEST_STORE');page.close();page=boot(state)
  assert page.evaluate('parseFloat(getComputedStyle(document.documentElement).fontSize)')==19
  page.locator('.bottom [data-tab="settings"]').first.click();page.locator('[data-theme="dark"]').click();assert page.locator('body.dark').count()==1
  page.locator('.bottom [data-tab="topics"]').first.click();page.locator('[data-cat="セキュリティ"]').click();assert page.locator('.article-card').count()==1
  page.locator('.article-card').click();assert 'PHP' in page.locator('#articlePage h1').inner_text()
  page.locator('.glossary summary').first.click();assert page.locator('.glossary details[open]').count()==1
  page.locator('[data-close]').first.click();page.locator('.bottom [data-tab="earnings"]').click();assert page.locator('.article-card').count()==1
  # Device widths, both themes, large text. Tables may scroll internally, never whole page.
  for width in (320,375,390,430):
   page.set_viewport_size({'width':width,'height':844})
   for tab in ('home','topics','earnings','settings','saved'):
    page.locator(f'.bottom [data-tab="{tab}"]').click()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,tab)
   page.locator('.bottom [data-tab="earnings"]').click();page.locator('.article-card').click()
   assert page.locator('#articlePage').evaluate('(e)=>e.scrollWidth<=e.clientWidth'),width
   page.locator('[data-close]').first.click()
  # No fabricated future and old content in fresh home edition.
  page.evaluate("S.editorial.articles[0].published_at='2099-01-01T00:00:00+09:00';render()")
  page.locator('.bottom [data-tab="home"]').click();assert page.locator('.article-card').count()==1
  page.evaluate("S.editorial.articles.forEach(a=>a.home_until='2000-01-01T00:00:00+09:00');render()")
  assert page.locator('.article-card').count()==1  # Publication date, not curation expiry, defines Today.
  assert not errors,errors
  result={'status':'PASS','browser':'Chromium','widths':[320,375,390,430],'article_body_px':{'normal':before,'large':after},'first_card_top_px':first['y'],'js_errors':errors,'tests':['article-first layout','notices at footer','tables/chart/flow','font switch in article','font setting in settings','preference save and fresh-page restore using storage fixture','bookmarks','topic filter','glossary expansion','earnings tab','large text overflow checks','future exclusion','publication day independent of curation expiry'],'limitations':['Injected fetch and storage fixtures; native localStorage/HTTP/service-worker not exercised','No real iPhone/Safari device test','No live RSS or TDnet connection test','No production deployment']}
  (OUT/'asa_brief_v12_browser_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
  print(json.dumps(result,ensure_ascii=False));browser.close()
if __name__=='__main__':main()
