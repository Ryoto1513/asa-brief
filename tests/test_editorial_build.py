"""Public allowlist build tests after the authorized Chat-mirror migration.

Legacy article validation/import/hash tests remain in test_editorial*.py; the old
build assertions that published RSS and all independent articles are intentionally
replaced: those files must no longer be deployed.
"""
from datetime import datetime, timezone
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / 'tools'))
import build_site
import chat_brief

class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ('index.html','manifest.webmanifest','sw.js'):
            shutil.copy2(R/name,self.root/name)
        for name in ('assets','config','data'):
            shutil.copytree(R/name,self.root/name)
        self.now = datetime.now(timezone.utc)
    def tearDown(self): self.temp.cleanup()
    def build(self): return build_site.build_site(self.root,now=self.now)
    def test_allowlist_exact_body_and_preserved_earnings(self):
        with patch('socket.create_connection',side_effect=AssertionError('network forbidden')):
            result=self.build()
        out=self.root/'.site'
        source=json.loads((self.root/'config/editorial.json').read_text())
        public=json.loads((out/'data/editorial.json').read_text())
        self.assertEqual(public['articles'],[a for a in source['articles'] if a['cat']=='決算'])
        self.assertEqual((out/'data/earnings.json').read_bytes(),(self.root/'data/earnings.json').read_bytes())
        for p in result['manifest']['absent_paths']: self.assertFalse((out/p).exists(),p)
        for p in ('config','tests','tools','asa_brief_noapi_v1_1'): self.assertFalse((out/p).exists())
        for entry in result['manifest']['files']:
            self.assertEqual(chat_brief.sha256((out/entry['path']).read_bytes()),entry['sha256'])
        for e in result['manifest']['editions']:
            day=e['edition_date']; raw=(self.root/f'config/chat-briefs/{day}.md').read_bytes()
            self.assertEqual((out/f'data/chat-briefs/{day}.md').read_bytes(),raw)
            payload=json.loads((out/f'data/chat-briefs/{day}.json').read_text())
            self.assertEqual(payload['body_markdown'].encode(),raw)
            self.assertEqual(payload['body_sha256'],chat_brief.sha256(raw))
            self.assertEqual(payload['blocks'],chat_brief.parse_markdown(raw.decode()))
    def test_deterministic(self): self.assertEqual(self.build(),self.build())
    def test_invalid_legacy_source_still_fails_without_overwrite(self):
        self.build(); before=(self.root/'.site/data/chat-brief-manifest.json').read_bytes()
        p=self.root/'config/editorial.json'; source=json.loads(p.read_text()); source['articles'][0]['blocks'][0]['refs']=[999];p.write_text(json.dumps(source))
        with self.assertRaises(ValueError): self.build()
        self.assertEqual((self.root/'.site/data/chat-brief-manifest.json').read_bytes(),before)
    def test_missing_canonical_never_falls_back_to_rss(self):
        shutil.rmtree(self.root/'config/chat-briefs')
        with self.assertRaisesRegex(ValueError,'missing'): self.build()
        self.assertFalse((self.root/'.site').exists())
    def test_body_mismatch_preserves_previous_site(self):
        self.build(); before=(self.root/'.site/data/chat-brief-manifest.json').read_bytes()
        p=next((self.root/'config/chat-briefs').glob('*.md'));p.write_bytes(p.read_bytes()+b'altered')
        with self.assertRaisesRegex(ValueError,'integrity'):self.build()
        self.assertEqual((self.root/'.site/data/chat-brief-manifest.json').read_bytes(),before)
    def test_concurrent_canonical_change_fails(self):
        original=build_site.load_editions
        def changed(*args,**kwargs):
            result=original(*args,**kwargs);p=next((self.root/'config/chat-briefs').glob('*.md'));p.write_bytes(p.read_bytes()+b'changed');return result
        with patch.object(build_site,'load_editions',side_effect=changed), self.assertRaisesRegex(ValueError,'changed'):self.build()
        self.assertFalse((self.root/'.site').exists())
    def test_no_private_or_unexpected_public_manuscript_files(self):
        (self.root/'config/chat-briefs/privateaudit.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'unexpected'):self.build()
    def test_expired_edition_keeps_its_date_never_relabels_as_today(self):
        from datetime import timedelta
        result=build_site.build_site(self.root,now=self.now+timedelta(days=7))
        self.assertEqual(result['manifest']['editions'][0]['edition_date'],'2026-10-24')

class ManuscriptTests(unittest.TestCase):
    def test_real_body_hash_and_order(self):
        editions,_=chat_brief.load_editions(R);e=editions[0]
        self.assertEqual(e['body_sha256'],'8d309138251dd9161a09a657982c204b80c35b663bd27b4ce6b96603e9a36740')
        self.assertEqual(len(e['body_markdown'].encode()),41711)
        self.assertEqual(len([b for b in e['blocks'] if b['type']=='table']),2)
        self.assertEqual(e['blocks'][0]['type'],'heading')
    def test_injection_private_links_and_unknown_markup_rejected(self):
        cases=['<script>alert(1)</script>','![image](https://example.com/a)','```python\nx\n```','> quote','[x](javascript:alert)','[x](https://chatgpt.com/c/secret)','[x](https://localhost/a)','[x](https://user:pass@example.com/a)','[x](https://example.com/a?token=secret)','\ue200cite\ue202x\ue201','**unclosed','| h |\n| invalid |','_unsupported_','1. first\n3. third']
        for body in cases:
            with self.subTest(body=body),self.assertRaises(ValueError):chat_brief.parse_markdown(body)
    def test_exact_inline_order_and_table(self):
        b=chat_brief.parse_markdown('# 1．見出し\n\n前**重要**後 [出典](https://example.com/a)\n次の行\n\n| 左 | 右 |\n|---|---:|\n| 1 | 2 |')
        self.assertEqual([x['type'] for x in b],['heading','paragraph','table'])
        self.assertEqual(b[0]['inlines'][0]['text'],'1．見出し')
        self.assertEqual(b[1]['inlines'][-1]['text'],'\n次の行')
        self.assertEqual(b[2]['rows'][0][1][0]['text'],'2')
        self.assertEqual(b[2]['align'],['left','right'])
    def test_future_source_and_edition_rejected(self):
        with self.assertRaisesRegex(ValueError,'future|timestamps'):
            chat_brief.load_editions(R,datetime(2026,10,23,tzinfo=timezone.utc))
        with self.assertRaisesRegex(ValueError,'timestamps'):
            chat_brief.load_editions(R,datetime(2026,10,24,14,0,tzinfo=timezone.utc))

if __name__=='__main__': unittest.main()
