"""Optional offline Chromium smoke for additive v2 manuscripts and RSS coexistence.

Uses real application JS/CSS with injected fetch/storage fixtures. It deliberately
never contacts a source or deploys; run after installing Playwright separately.
"""
import argparse
import copy
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright
from browser_briefing_dates import check_briefing_dates

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / 'tools'))
from editorial import require_valid, order_articles, timestamp, canonical_hash, LEGACY_HASHES
from test_editorial import collection, metric, numeric_article, legacy_collection

NOW = datetime.fromisoformat('2026-10-23T11:00:00+09:00')


def fixture_data():
    story = numeric_article()
    story['cat'] = '決算'
    story['title'] = '合成テスト：架空決算の表示確認（本物のニュースではありません）'
    story['company_code'] = '9999'
    story['disclosure_key'] = '9999:2026-10-23'
    story['metrics'].append(metric('profit', 20))
    story['blocks'] += [
        {'type': 'bars', 'title': '事実｜合成テストの比較図', 'role': 'what',
         'claim_type': 'fact', 'unit': '億円', 'rows': [
             ['2026上期 実績 架空売上', 100], ['2026上期 実績 架空利益', 20]],
         'caption': '2026上期 実績 億円。すべて架空の数値。', 'refs': [1],
         'metric_ids': ['sales', 'profit']},
        {'type': 'timeline', 'title': '事実｜合成テストの時系列', 'role': 'background',
         'claim_type': 'fact', 'refs': [1], 'rows': [
             ['2026-10-23T09:00:00+09:00', '架空の発表'],
             ['2026-10-23T09:15:00+09:00', '架空の追記']]},
    ]
    legacy = legacy_collection()['articles']
    manuscript = collection(*order_articles([*legacy, story]))
    require_valid(manuscript, now=NOW)
    rss = {
        'id': 'synthetic-rss-independent', 'title': '合成RSS：別の架空ニュース',
        'lead': '検証専用の架空RSS見出し。', 'cat': '日本経済',
        'source_url': 'https://example.com/synthetic-rss-independent',
        'publisher': '合成RSS', 'source_kind': 'primary', 'quality': 'headline',
        'date': '10/23', 'published_at': '2026-10-23T09:00:00+09:00',
        'priority': '通常', 'sections': [['テスト設定', '合成データです。']],
        'sources': [{'name': '合成RSS出典', 'url': 'https://example.com/synthetic-rss-independent'}],
    }
    duplicate = copy.deepcopy(rss)
    duplicate.update(id='synthetic-rss-covered', title='合成RSS：詳報と同じURLの見出し',
                     source_url=story['source_url'])
    edition = {'schema_version': 1, 'articles': [rss, duplicate], 'status': 'live',
               'generated_at': '2026-10-23T10:00:00+09:00', 'edition_date': '2026-10-23',
               'markets': [], 'notice': 'すべてローカル表示試験。ネットワーク収集は未実施。'}
    return story, {
        'data/latest.json': edition,
        'data/status.json': {'state': 'success', 'feeds': [], 'attempted_at': edition['generated_at']},
        'data/editorial.json': manuscript,
        'data/earnings.json': {'schema_version': 1, 'items': [], 'state': 'uninitialized',
                               'message': '合成表示試験・実在の開示取得なし'},
    }


def check_current_library(browser):
    """Separate real-library view, using one observed clock, never manuscript time."""
    observed = datetime.now(timezone.utc)
    raw = (R / 'config/editorial.json').read_bytes()
    library = json.loads(raw)
    require_valid(library, now=observed)
    assert observed <= datetime.now(timezone.utc)
    print('BROWSER_REAL_LIBRARY_EVALUATION ' + observed.isoformat(), flush=True)
    articles = library['articles']
    assert articles == order_articles(articles)
    for identity, expected_hash in LEGACY_HASHES.items():
        assert canonical_hash(next(a for a in articles if a['id'] == identity)) == expected_hash
    story = next(a for a in articles if a['id'] == 'japan-cpi-202609-first-brief')
    day = observed.astimezone(timestamp(story['published_at']).tzinfo).date().isoformat()
    members = library.get('briefings', {}).get(day)
    active = [a for a in articles if timestamp(a['published_at']) <= observed < timestamp(a['home_until'])
              and (members is None or a['id'] in members)]
    data = {
        'data/editorial.json': library,
        'data/latest.json': {'schema_version': 1, 'articles': [], 'status': 'live',
                            'edition_date': observed.astimezone(timestamp(story['published_at']).tzinfo).date().isoformat(),
                            'generated_at': observed.isoformat(), 'markets': []},
        'data/earnings.json': {'schema_version': 1, 'items': []},
        'data/status.json': {'state': 'success', 'feeds': []},
    }
    errors, requests = [], []
    context = browser.new_context(viewport={'width': 390, 'height': 844},
                                  is_mobile=True, has_touch=True, service_workers='block')
    context.route('**/*', lambda route: (requests.append(route.request.url), route.abort()))
    page = context.new_page()
    page.clock.install(time=observed)
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.set_content('<meta name="viewport" content="width=device-width, initial-scale=1">'
                     '<style>' + (R / 'assets/style.css').read_text(encoding='utf-8') + '</style>'
                     '<main class="shell" id="app"></main><div id="modal"></div>')
    page.add_script_tag(content='window.TEST_DATA=' + json.dumps(data, ensure_ascii=False) + ';'
        'window.TEST_STORE={};'
        "Object.defineProperty(window,'localStorage',{value:{getItem:k=>window.TEST_STORE[k]??null,"
        'setItem:(k,v)=>{window.TEST_STORE[k]=String(v)},removeItem:k=>{delete window.TEST_STORE[k]}}});'
        'window.fetch=async(url)=>{'
        r"let key=String(url).replace(/^\.\//,'').split('?')[0];"
        'return new Response(JSON.stringify(window.TEST_DATA[key]||{}),'
        "{status:200,headers:{'Content-Type':'application/json'}})};")
    page.add_script_tag(content=(R / 'assets/app.js').read_text(encoding='utf-8'))
    page.wait_for_function('!S.loading')
    expected_ids = [a['id'] for a in active[:12]]
    assert page.locator('.article-card').evaluate_all('(cards)=>cards.map(c=>c.dataset.open)') == expected_ids
    if story['id'] in expected_ids:
        card = page.locator('.article-card[data-open="' + story['id'] + '"]')
        assert card.locator('.summary').inner_text() == story['lead']
        assert card.locator('.why').count() == 0
        assert story['selection_reason'] not in card.inner_text()
        card.click()
    else:
        # Retained articles remain available after expiry; do not advance the clock.
        page.evaluate('(id)=>openArticle(id)', story['id'])
    assert page.locator('#articlePage h1').inner_text() == story['title']
    assert page.locator('#articlePage .editorial-group > h2').all_inner_texts() == ['事実', '分析', '今後の見通し']
    expected_titles = [re.sub(r'^(事実|分析|予測)\s*[｜|:：]\s*', '', b['title']) for b in story['blocks']]
    assert page.locator('#articlePage .rich-block h3').all_inner_texts() == expected_titles
    assert page.locator('#articlePage table').count() == 1
    assert page.locator('#articlePage .bar-row').count() == 2
    for block in story['blocks']:
        if block['type'] in ('table', 'bars'):
            assert block['caption'] in page.locator('#articlePage').inner_text()
    assert page.locator('#articlePage .rich-block .smallnote').count() == 0
    details = page.locator('#articlePage .scope-details')
    details.locator('summary').click()
    assert story['selection_reason'] in details.inner_text()
    for paragraph in re.split(r'\r?\n\s*\r?\n', story['scope']):
        assert paragraph in details.locator('p').all_text_contents()
    for width in (320, 375, 390, 430):
        page.set_viewport_size({'width': width, 'height': 844})
        assert page.locator('#articlePage').evaluate('(e)=>e.scrollWidth<=e.clientWidth'), width
    assert not errors, errors
    assert not requests, requests
    assert (R / 'config/editorial.json').read_bytes() == raw
    result = {'as_of': observed.isoformat(), 'article_ids': [a['id'] for a in articles],
              'active_article_ids': [a['id'] for a in active], 'cpi_revision': story['revision'],
              'cpi_sha256': canonical_hash(story), 'javascript_errors': errors, 'network_requests': requests}
    context.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=R.parent)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    story, data = fixture_data()
    errors, requests = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=shutil.which('chromium'),
                                    args=['--no-sandbox'])
        context = browser.new_context(viewport={'width': 390, 'height': 844},
                                      is_mobile=True, has_touch=True, service_workers='block')
        # Fail closed even if future application code attempts a real request.
        context.route('**/*', lambda route: (requests.append(route.request.url), route.abort()))
        page = context.new_page()
        page.clock.install(time=NOW)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_content('<meta name="viewport" content="width=device-width, initial-scale=1">'
                         '<style>' + (R / 'assets/style.css').read_text(encoding='utf-8') + '</style>'
                         '<main class="shell" id="app"></main><div id="modal"></div>')
        page.add_script_tag(content='window.TEST_DATA=' + json.dumps(data, ensure_ascii=False) + ';'
            'window.TEST_STORE={};window.TEST_FETCHES=[];'
            "Object.defineProperty(window,'localStorage',{value:{"
            'getItem:k=>window.TEST_STORE[k]??null,'
            'setItem:(k,v)=>{window.TEST_STORE[k]=String(v)},'
            'removeItem:k=>{delete window.TEST_STORE[k]}}});'
            'window.fetch=async(url)=>{'
            r"let key=String(url).replace(/^\.\//,'').split('?')[0];window.TEST_FETCHES.push(key);"
            'return new Response(JSON.stringify(window.TEST_DATA[key]||{}),'
            "{status:window.TEST_DATA[key]?200:404,headers:{'Content-Type':'application/json'}})};")
        page.add_script_tag(content=(R / 'assets/app.js').read_text(encoding='utf-8'))
        page.wait_for_selector('.article-card')
        page.wait_for_timeout(100)

        expected_cards = len(data['data/editorial.json']['articles']) + 1
        assert page.locator('.article-card').count() == expected_cards
        assert page.locator('[data-open="synthetic-rss-covered"]').count() == 0
        assert page.locator('.article-card').first.get_attribute('data-open') == story['id']
        assert page.locator('.article-card').first.locator('.mini.muted').first.inner_text().startswith(story['date'])
        assert page.locator('[data-open="synthetic-rss-independent"]').count() == 1
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(args.output_dir / 'asa_brief_phase2_home.png'))

        def open_synthetic():
            page.locator('.article-card[data-open="' + story['id'] + '"]').click()
            assert page.locator('#articlePage h1').inner_text() == story['title']

        open_synthetic()
        assert page.locator('#articlePage table').count() == 1
        assert page.locator('#articlePage .bar-row').count() == 2
        # The outer section also carries the timeline class; count only event rows.
        timeline = page.locator('#articlePage section.rich-block.timeline > div.timeline > div')
        assert timeline.count() == 2
        expected_timeline = next(b['rows'] for b in story['blocks'] if b['type'] == 'timeline')
        assert timeline.locator('b').all_inner_texts() == [row[0] for row in expected_timeline]
        assert timeline.locator('p').all_inner_texts() == [row[1] for row in expected_timeline]
        assert page.locator('#articlePage .flow-step').count() == 3
        assert page.locator('#articlePage .takeaways').count() == 1
        headings = page.locator('#articlePage .editorial-group > h2').all_inner_texts()
        for label in ('事実', '分析', '今後の見通し'):
            assert label in headings, headings
        subheadings = page.locator('#articlePage .rich-block h3').all_inner_texts()
        assert len(subheadings) == len(story['blocks'])
        assert not any(title.startswith(('事実｜', '分析｜', '予測｜')) for title in subheadings)
        assert page.locator('#source-1').get_attribute('href') == story['source_url']
        page.locator('.glossary summary').first.click()
        assert page.locator('.glossary details[open]').count() == 1
        normal = page.locator('.rich-block p').first.evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)')
        assert normal == 16
        page.locator('.text-toggle').click()
        large = page.locator('.rich-block p').first.evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)')
        assert large == 19
        page.locator('.rich-block.table').scroll_into_view_if_needed()
        page.screenshot(path=str(args.output_dir / 'asa_brief_phase2_numbers.png'))
        page.locator('#articlePage [data-bookmark]').click()
        page.locator('[data-close]').first.click()
        page.locator('.bottom [data-tab="saved"]').click()
        assert page.locator('.article-card').count() == 1
        assert page.locator('.article-card').get_attribute('data-open') == story['id']
        page.locator('.bottom [data-tab="topics"]').click()
        page.locator('[data-cat="日本経済"]').click()
        assert page.locator('[data-open="synthetic-rss-independent"]').count() == 1
        page.locator('[data-cat="決算"]').click()
        assert page.locator('[data-open="' + story['id'] + '"]').count() == 1
        page.locator('.bottom [data-tab="earnings"]').click()
        assert page.locator('[data-open="' + story['id'] + '"]').count() == 1

        for width in (320, 375, 390, 430):
            page.set_viewport_size({'width': width, 'height': 844})
            for theme in ('light', 'dark'):
                page.locator('.bottom [data-tab="settings"]').click()
                page.locator('[data-theme="' + theme + '"]').click()
                page.locator('[data-font="large"]').click()
                assert page.locator('.font-sample p').evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)') == 19
                for tab in ('home', 'topics', 'earnings', 'saved', 'settings'):
                    page.locator('.bottom [data-tab="' + tab + '"]').click()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), (width, theme, tab)
                page.locator('.bottom [data-tab="earnings"]').click()
                open_synthetic()
                assert page.locator('#articlePage').evaluate('(e)=>e.scrollWidth<=e.clientWidth'), (width, theme)
                page.locator('[data-close]').first.click()
        assert not errors, errors
        assert not requests, requests
        date_filter = check_briefing_dates(browser, data)
        current_library = check_current_library(browser)
        result = {
            'current_library': current_library, 'date_filter': date_filter,
            'status': 'PASS', 'browser': 'Chromium', 'network_requests': requests,
            'widths': [320, 375, 390, 430], 'themes': ['light', 'dark'],
            'font_px': {'normal': normal, 'large': large}, 'javascript_errors': errors,
            'tests': ['validated synthetic v2 with unchanged legacy articles', 'RSS coexistence and duplicate suppression',
                      'import ordering helper puts important new article in TOP3',
                      'visible fact/analysis/prediction', 'table/bars/flow/timeline', 'glossary and source links',
                      'today/topics/earnings/saved/settings', 'bookmark and font controls',
                      'large-text page overflow at four widths in both themes'],
            'limitations': ['Injected fetch/storage, not native HTTP/localStorage/service worker',
                            'No real iPhone or Safari', 'No live RSS, source verification or Pages deployment'],
        }
        (args.output_dir / 'asa_brief_phase2_browser_report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
        browser.close()


if __name__ == '__main__':
    main()
