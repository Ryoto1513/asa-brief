"""Optional mobile-sized Chromium test. Requires Playwright + a Chromium binary.
Uses synthetic fixtures in a temporary directory. It does not fetch real news.
"""
from datetime import datetime, timedelta
from email.utils import format_datetime
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import threading
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('collector',ROOT/'tools/update_news.py')
u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

def main():
    with tempfile.TemporaryDirectory() as tmp:
        app=Path(tmp)/'asa-brief';shutil.copytree(ROOT,app)
        config=json.loads((ROOT/'config/sources.json').read_text());config['feeds']=[config['feeds'][0]]
        now=datetime.now(u.JST)
        blob=f'<rss><channel><item><title>操作テスト用：金融政策の見出し</title><link>https://www.boj.or.jp/test-fixture-only</link><pubDate>{format_datetime(now-timedelta(hours=1))}</pubDate></item></channel></rss>'.encode()
        u.run(now=now,data_dir=app/'data',config=config,downloader=lambda *args:blob)
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=tmp))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,executable_path=shutil.which('chromium'),args=['--no-sandbox'])
                ctx=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
                page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                url=f'http://127.0.0.1:{server.server_port}/asa-brief/'
                # The sandbox's managed Chromium blocks loopback navigation. Exercise the
                # real UI with injected JSON responses instead of altering that policy.
                edition=json.loads((app/'data/latest.json').read_text())
                health=json.loads((app/'data/status.json').read_text())
                page.set_content('<style>'+(ROOT/'assets/style.css').read_text()+'</style><main class="shell" id="app"></main><div id="modal"></div>')
                page.add_script_tag(content="window.TEST_DATA="+json.dumps(edition)+";window.TEST_HEALTH="+json.dumps(health)+";window.TEST_OFFLINE=false;window.fetch=async (url)=>{let data=String(url).includes('status.json')?window.TEST_HEALTH:String(url).includes('archive/index.json')?{dates:[window.TEST_DATA.edition_date]}:window.TEST_DATA;return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json','X-Asa-Offline':window.TEST_OFFLINE?'1':'0'}})};")
                page.add_script_tag(content=(ROOT/'assets/app.js').read_text())
                page.wait_for_selector('.article-card')
                assert page.locator('.article-card').count()==1
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                page.locator('.article-card').first.click();assert page.locator('#articlePage').count()==1
                assert '一般論' in page.locator('#articlePage').inner_text()
                assert 'コピー' in page.locator('[data-copy-question]').inner_text()
                page.locator('#articlePage [data-bookmark]').click()
                page.locator('[data-close]').first.click();page.locator('[data-tab="saved"]').click()
                assert page.locator('.article-card').count()==1
                page.locator('[data-tab="topics"]').click();page.locator('[data-cat="金融政策"]').click()
                assert page.locator('.article-card').count()==1
                page.locator('#searchInput').fill('no-such-text');assert page.locator('.article-card').count()==0
                page.locator('[data-tab="settings"]').click();page.locator('[data-theme="dark"]').click()
                assert page.locator('body.dark').count()==1
                page.locator('[data-font="large"]').click();assert page.locator('body.large').count()==1
                assert '取得状況' in page.inner_text('body')
                page.locator('[data-tab="home"]').first.click();page.locator('[data-refresh]').first.click()
                page.wait_for_timeout(250)
                page.wait_for_selector('.article-card')
                page.evaluate('window.TEST_OFFLINE=true');page.locator('[data-refresh]').first.click()
                page.wait_for_function("document.body.innerText.includes('オフライン・保存済み')")
                assert page.locator('.article-card').count()==1
                page.evaluate('window.TEST_OFFLINE=false')
                page.locator('[data-refresh]').first.click();page.wait_for_timeout(250)
                page.locator('[data-archive]').click();page.locator('#archiveSelect').select_option(now.date().isoformat())
                page.wait_for_timeout(250);assert '過去の配信号' in page.inner_text('body')
                for width in (320,375,430):
                    page.set_viewport_size({'width':width,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),f'overflow at {width}'
                assert not errors,errors
                browser.close()
                print('PASS: mobile 320/375/390/430px; article; bookmark; category; search; theme; font; source health; archive; simulated offline notice. Injected JSON / Chromium only. Real HTTP, service worker caching and iOS Safari not exercised.')
        finally:server.shutdown()

if __name__=='__main__':main()
