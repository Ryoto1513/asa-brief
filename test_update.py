import copy
from datetime import datetime, timedelta
from email.utils import format_datetime
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
R=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('update_news',R/'tools/update_news.py')
u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
NOW=datetime(2026,10,22,7,35,tzinfo=u.JST)
CONFIG=json.loads((R/'config/sources.json').read_text())
PRIMARY=CONFIG['feeds'][0]
PRESS=CONFIG['feeds'][7]

def rss(title='テスト用 金融政策の発表',url='https://www.boj.or.jp/test.htm',published=None,source=''):
    return f'<rss version="2.0"><channel><item><title>{title}</title><link>{url}</link><pubDate>{published or format_datetime(NOW-timedelta(hours=1))}</pubDate>{source}</item></channel></rss>'.encode()

class CollectorTests(unittest.TestCase):
    def test_rss2(self):
        items,_=u.parse_feed(rss(),PRIMARY,NOW,CONFIG)
        self.assertEqual(len(items),1);self.assertEqual(items[0]['tag'],'公式発表')
    def test_rdf(self):
        blob=b'''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"><item><title>test RDF title</title><link>https://www.boj.or.jp/rdf</link><dc:date>2026-10-21T10:00:00+09:00</dc:date></item></rdf:RDF>'''
        self.assertEqual(len(u.parse_feed(blob,PRIMARY,NOW,CONFIG)[0]),1)
    def test_atom(self):
        blob=b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Test Atom</title><link rel="self" href="https://bad.example"/><link rel="alternate" href="https://www.boj.or.jp/atom"/><updated>2026-10-21T12:00:00+09:00</updated></entry></feed>'''
        self.assertEqual(u.parse_feed(blob,PRIMARY,NOW,CONFIG)[0][0]['source_url'],'https://www.boj.or.jp/atom')
    def test_shift_jis(self):
        xml='<?xml version="1.0" encoding="Shift_JIS"?>'+rss().decode()
        self.assertEqual(len(u.parse_feed(xml.encode('shift_jis'),PRIMARY,NOW,CONFIG)[0]),1)
    def test_future_excluded(self):
        items,_=u.parse_feed(rss(published=format_datetime(NOW+timedelta(minutes=1))),PRIMARY,NOW,CONFIG)
        self.assertFalse(items)
    def test_stale_excluded(self):
        items,_=u.parse_feed(rss(published=format_datetime(NOW-timedelta(days=9))),PRIMARY,NOW,CONFIG)
        self.assertFalse(items)
    def test_date_only(self):
        items,_=u.parse_feed(rss(published='2026-10-21'),PRIMARY,NOW,CONFIG)
        self.assertEqual(items[0]['date_precision'],'date')
    def test_reject_unsafe_url(self):
        for link in ('javascript:alert(1)','https://www.boj.or.jp.evil.example/x','https://a:b@www.boj.or.jp/x','https://www.boj.or.jp:8443/x'):
            self.assertFalse(u.parse_feed(rss(url=link),PRIMARY,NOW,CONFIG)[0])
    def test_unapproved_press(self):
        source='<source url="https://bad.example">unknown</source>'
        self.assertFalse(u.parse_feed(rss(url='https://news.google.com/rss/articles/test',source=source),PRESS,NOW,CONFIG)[0])
    def test_approved_press(self):
        source='<source url="https://www.reuters.com">Reuters</source>'
        records,_=u.parse_feed(rss(title='テスト用ニュース - Reuters',url='https://news.google.com/rss/articles/test',source=source),PRESS,NOW,CONFIG)
        self.assertEqual(records[0]['publisher'],'Reuters');self.assertEqual(records[0]['title'],'テスト用ニュース')
    def test_html_feed_rejected(self):
        with self.assertRaises(ValueError):u.parse_feed(b'<html><body>403</body></html>',PRIMARY,NOW,CONFIG)
    def test_entities_rejected(self):
        with self.assertRaises(ValueError):u.parse_feed(b'<!DOCTYPE a [<!ENTITY x "aa">]><rss/>',PRIMARY,NOW,CONFIG)
    def test_strip_script(self):
        self.assertEqual(u.clean('<script>alert(1)</script><b>safe</b>'),'safe')
    def test_domain_allowlist(self):
        self.assertTrue(u.host_ok('https://jp.reuters.com/a',['reuters.com']))
        self.assertFalse(u.host_ok('https://reuters.com.evil.example/a',['reuters.com']))
    def test_discover_primary(self):
        feed=copy.deepcopy(CONFIG['feeds'][1]);feed.pop('url',None);feed['discovery_page']='https://www.mof.go.jp/about_mof/rss/index.html'
        html=b'<a href="/english/feed.xml">English</a><a href="/news.rdf">RSS</a>'
        self.assertEqual(u.resolve_feed(feed,lambda url,hosts:html),'https://www.mof.go.jp/news.rdf')
    def test_dedup_and_coverage(self):
        a=u.parse_feed(rss(),PRIMARY,NOW,CONFIG)[0][0]
        b=copy.deepcopy(a);b.update(id='different',cat='世界経済',source_url='https://www.boj.or.jp/other',_titlekey='distinct')
        self.assertEqual(len(u.select_articles([a,copy.deepcopy(a),b],CONFIG)),2)
    def test_general_notes_labeled(self):
        a=u.parse_feed(rss(),PRIMARY,NOW,CONFIG)[0]
        k=json.loads((R/'config/knowledge.json').read_text())
        result=u.enrich_with_fixed_notes(a,k)
        self.assertEqual(result[0]['quality'],'fixed_learning')
        self.assertTrue(any('一般論' in s[0] for s in result[0]['sections']))
    def test_total_failure_preserves_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'latest.json').write_text('{"old":"preserve"}')
            with self.assertRaises(RuntimeError):u.run(now=NOW,data_dir=p,downloader=lambda *args:(_ for _ in ()).throw(OSError('offline')))
            self.assertEqual((p/'latest.json').read_text(),'{"old":"preserve"}')
            self.assertEqual(json.loads((p/'status.json').read_text())['state'],'failed')
    def test_success_empty_feed_not_failure(self):
        c=copy.deepcopy(CONFIG);c['feeds']=[PRIMARY]
        with tempfile.TemporaryDirectory() as tmp:
            result=u.run(now=NOW,data_dir=tmp,config=c,downloader=lambda *args:b'<rss><channel/></rss>')
            self.assertEqual(result['articles'],[])
            self.assertEqual(json.loads((Path(tmp)/'status.json').read_text())['state'],'success')
    def test_no_paid_api_even_with_environment_key(self):
        c=copy.deepcopy(CONFIG);c['feeds']=[PRIMARY];called=[]
        def downloader(url,hosts):called.append(url);return rss()
        with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'OPENAI_API_KEY':'test-not-a-real-key','ANTHROPIC_API_KEY':'test'}):
            result=u.run(now=NOW,data_dir=tmp,config=c,downloader=downloader)
            self.assertEqual(result['editorial_mode'],'curated_with_editorial_library')
            self.assertEqual(called,['https://www.boj.or.jp/rss/whatsnew.xml'])
    def test_no_fake_prices(self):
        self.assertEqual(json.loads((R/'data/latest.json').read_text())['markets'],[])
    def test_archive_retention(self):
        c=copy.deepcopy(CONFIG);c['feeds']=[PRIMARY]
        with tempfile.TemporaryDirectory() as tmp:
            for d in range(16):u.run(now=NOW+timedelta(days=d),data_dir=tmp,config=c,downloader=lambda *a:b'<rss><channel/></rss>')
            self.assertEqual(len(list((Path(tmp)/'archive').glob('????-??-??.json'))),14)
    def test_no_llm_endpoints_in_runtime(self):
        for p in [R/'tools/update_news.py',R/'.github/workflows/daily-news.yml',R/'assets/app.js']:
            text=p.read_text()
            for forbidden in ['api.openai.com','api.anthropic.com','OPENAI_API_KEY','ANTHROPIC_API_KEY']:
                self.assertNotIn(forbidden,text)

if __name__=='__main__':unittest.main()
