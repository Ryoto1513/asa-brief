import copy,importlib.util,json,sys,tempfile,unittest
from datetime import datetime,timedelta
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'tools'))
import update_news as u
import editorial_rules as e
import earnings_watch as w
C=json.loads((R/'config/sources.json').read_text());NOW=datetime(2026,10,22,18,0,tzinfo=u.JST)

def item(title,url='https://example.com/news',cat='日本経済',id='a'):
    return {'id':id,'title':title,'cat':cat,'source_url':url,'source_kind':'press_search','publisher_domain':'reuters.com','_score':25,'date':'10/22'}

class EditorialTests(unittest.TestCase):
    def test_recruitment_excluded(self):
        self.assertIsNone(e.classify(item('採用,職員を募集しています。（資産運用会社等の監督）')))
    def test_ir_results_kept(self):self.assertGreater(e.classify(item('半導体企業の決算、営業利益が増益'))[1],40)
    def test_meeting_noise_excluded(self):self.assertIsNone(e.classify(item('情報通信政策部会 委員会（第7回）配布資料・議事録')))
    def test_php_selected(self):self.assertEqual(e.classify(item('PHPに重大な脆弱性、修正版を公開'))[0],'セキュリティ')
    def test_minor_plugin_excluded(self):self.assertIsNone(e.classify(item('無名プラグインにクロスサイトスクリプティングの脆弱性')))
    def test_paris_selected(self):self.assertEqual(e.classify(item('パリで暴動、夜間外出禁止令'))[0],'国際情勢')
    def test_disaster_selected(self):self.assertEqual(e.classify(item('大規模災害で避難指示'))[0],'社会・重要')
    def test_no_nikkei_membership_inference(self):self.assertEqual(e.classify(item('日経平均の企業が好決算'))[0],'日本経済')
    def test_cve_duplicate_collapsed(self):
        a=item('PHP CVE-2026-109618 重大な脆弱性');b=item('PHP CVE-2026-109618 修正版公開',url='https://other.com/a',id='b')
        self.assertEqual(len(e.select([a,b],C)),1)
    def test_rss_extension_discovery(self):
        f={'discovery_page':'https://www.mof.go.jp/rss/','hosts':['mof.go.jp']}
        self.assertEqual(u.resolve_feed(f,lambda *a:b'<a href="/news.rss">RSS</a>'),'https://www.mof.go.jp/news.rss')
    def test_own_domain_http_normalization(self):
        blob=b'<rss><channel><item><title>Policy rate</title><link>http://www.boj.or.jp/a</link><pubDate>2026-10-22</pubDate></item></channel></rss>'
        rows,_=u.parse_feed(blob,C['feeds'][0],NOW,C);self.assertEqual(rows[0]['source_url'],'https://www.boj.or.jp/a')
    def test_editorial_claims_have_source_trails(self):
        articles=json.loads((R/'config/editorial.json').read_text())['articles']
        self.assertEqual(len(articles),3)
        for a in articles:
            self.assertTrue(a['scope']);self.assertTrue(a['glossary']);self.assertTrue(a['home_until']>a['published_at'])
            for b in a['blocks']:
                for ref in b.get('refs',[]):self.assertTrue(1<=ref<=len(a['sources']))
                if b['type']=='table':self.assertTrue(all(len(r)==len(b['headers']) for r in b['rows']))
    def test_disco_calculations(self):
        self.assertEqual(round(116639/257058*100,1),45.4)
        self.assertEqual((174700-116639)/100,580.61)
        self.assertEqual((389500-257058)/100,1324.42)
        self.assertEqual(round((116639/257058-78871/194537)*100,1),4.8)

class EarningsTests(unittest.TestCase):
    def test_component_count_guard(self):
        with self.assertRaises(ValueError):w.parse_components(b'<html>Maintenance</html>')
    def test_component_parser(self):
        h='<table>'+''.join(f'<tr><td>{i}</td><td>Alias</td><td>Company {i}</td></tr>' for i in range(1000,1225))+'</table>'
        self.assertEqual(len(w.parse_components(h.encode())),225)
    def test_tdnet_constituent_filter(self):
        h='<table><tr><td>16:00</td><td>61460</td><td>ディスコ</td><td><a href="1401.pdf">2027年3月期 決算短信</a></td></tr><tr><td>16:00</td><td>99990</td><td>Other</td><td><a href="other.pdf">決算短信</a></td></tr></table>'
        rows,_=w.parse_disclosures(h.encode(),'2026-10-22',{'6146':'ディスコ'})
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['code'],'6146');self.assertEqual(rows[0]['url'],'https://www.release.tdnet.info/inbs/1401.pdf')
    def test_tdnet_disallows_foreign_pdf(self):
        h='<tr><td>16:00</td><td>61460</td><td>Company</td><td><a href="https://evil.example/a.pdf">決算短信</a></td></tr>'
        self.assertEqual(w.parse_disclosures(h.encode(),'2026-10-22',{'6146':'Disco'})[0],[])
    def test_failure_preserves_previous(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);old={'items':[dict(id='a',published_at='2026-10-21T12:00+09:00')]};(p/'earnings.json').write_text(json.dumps(old))
            result=w.update_watch(NOW,lambda *a:(_ for _ in ()).throw(OSError()),p)
            self.assertEqual(result['state'],'failed');self.assertEqual(result['items'],old['items'])
    def test_successful_watch_with_fixtures(self):
        comp='<table>'+''.join(f'<tr><td>{i}</td><td>Company {i}</td></tr>' for i in range(1000,1225))+'</table>'
        doc='<table><tr><td>16:00</td><td>10000</td><td>会社</td><td><a href="news.pdf">決算短信</a></td></tr></table>'
        with tempfile.TemporaryDirectory() as t:
            result=w.update_watch(NOW,lambda url,h:comp.encode() if 'component' in url else doc.encode(),t)
            self.assertEqual(result['state'],'success');self.assertEqual(result['universe_count'],225);self.assertEqual(result['pages_ok'],3)
    def test_unexpected_html_not_success(self):
        comp='<table>'+''.join(f'<tr><td>{i}</td><td>Company</td></tr>' for i in range(1000,1225))+'</table>'
        with tempfile.TemporaryDirectory() as t:
            result=w.update_watch(NOW,lambda url,h:comp.encode() if 'component' in url else b'<html>403</html>',t)
            self.assertEqual(result['state'],'failed')

if __name__=='__main__':unittest.main()
