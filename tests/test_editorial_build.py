"""End-to-end offline build: synthetic inputs never modify the real source."""
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
import editorial_delivery
from test_editorial import NOW, article, collection


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ('index.html', 'manifest.webmanifest', 'sw.js'):
            shutil.copy2(R / name, self.root / name)
        shutil.copytree(R / 'assets', self.root / 'assets')
        (self.root / 'config').mkdir()
        (self.root / 'data/archive').mkdir(parents=True)
        self.source = self.root / 'config/editorial.json'
        self.latest = b'{"schema_version":1,"articles":[{"id":"rss-synthetic","title":"RSS fixture only"}]}\n'
        (self.root / 'data/latest.json').write_bytes(self.latest)
        (self.root / 'data/archive/2026-10-22.json').write_bytes(self.latest)
        self.write(collection(article()))

    def tearDown(self):
        self.temp.cleanup()

    def write(self, payload):
        self.source.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def test_exact_copy_same_manuscript_outputs_no_network(self):
        with patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
            result = build_site.build_site(self.root, now=NOW)
        out = self.root / '.site'
        self.assertEqual((out / 'data/editorial.json').read_bytes(), self.source.read_bytes())
        self.assertEqual((out / 'data/latest.json').read_bytes(), self.latest)
        self.assertEqual((out / 'data/archive/2026-10-22.json').read_bytes(), self.latest)
        self.assertFalse((out / 'config').exists())
        self.assertFalse((out / 'tests').exists())
        self.assertFalse((out / 'tools').exists())
        self.assertEqual(result['manifest']['manuscript_sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())
        public = {name: (out / 'data' / name).read_bytes() for name in
                  ('editorial.json', 'editorial-manifest.json', 'editorial-summary.txt')}
        report = editorial_delivery.verify_public(result['manifest'], 'https://example.github.io/asa-brief/',
            downloader=lambda url: public[url.split('/')[-1].split('?')[0]])
        self.assertEqual(report['state'], 'success')
        self.assertEqual(report['conversation_delivery'], 'not_sent')

    def test_invalid_article_refuses_build_and_keeps_previous_output(self):
        build_site.build_site(self.root, now=NOW)
        before = (self.root / '.site/data/editorial.json').read_bytes()
        bad = article(); bad['blocks'][0]['refs'] = [999]
        self.write(collection(bad))
        with self.assertRaises(ValueError):
            build_site.build_site(self.root, now=NOW)
        self.assertEqual((self.root / '.site/data/editorial.json').read_bytes(), before)
        self.assertEqual((self.root / 'data/latest.json').read_bytes(), self.latest)

    def test_build_is_deterministic_and_original_articles_retained(self):
        self.source.write_bytes((R / 'config/editorial.json').read_bytes())
        first = build_site.build_site(self.root, now=NOW)
        second = build_site.build_site(self.root, now=NOW)
        self.assertEqual(first, second)
        self.assertEqual((self.root / '.site/data/editorial.json').read_bytes(), (R / 'config/editorial.json').read_bytes())

    def test_unsorted_source_rejected_without_touching_previous_build(self):
        build_site.build_site(self.root, now=NOW)
        before = (self.root / '.site/data/editorial.json').read_bytes()
        first, second = article(), article()
        first['id'] = 'z-synthetic'
        second['id'] = 'a-synthetic'
        second['title'] += ' 別の合成記事'
        second['source_url'] = 'https://example.com/different-fixture'
        second['sources'][0]['url'] = second['source_url']
        self.write(collection(first, second))
        with self.assertRaisesRegex(ValueError, 'article order'):
            build_site.build_site(self.root, now=NOW)
        self.assertEqual((self.root / '.site/data/editorial.json').read_bytes(), before)

    def test_snapshot_uses_exact_evaluation_and_preserves_archives(self):
        result = build_site.build_site(self.root, now=NOW)
        self.assertEqual(result['manifest']['as_of'], NOW.astimezone(__import__('datetime').timezone.utc).isoformat())
        self.assertEqual(result['manifest']['delivery_date'], '2026-10-23')
        self.assertEqual(result['manifest']['active_article_ids'], [article()['id']])
        self.assertEqual((self.root / '.site/data/archive/2026-10-22.json').read_bytes(), self.latest)

    def test_no_ui_or_article_body_transformation(self):
        build_site.build_site(self.root, now=NOW)
        for name in ('index.html', 'sw.js', 'assets/app.js', 'assets/style.css'):
            with self.subTest(name=name):
                self.assertEqual((self.root / '.site' / name).read_bytes(), (self.root / name).read_bytes())
        self.assertEqual((self.root / '.site/data/editorial.json').read_bytes(), self.source.read_bytes())

    def test_import_build_summary_and_ui_order_share_exact_ids_and_hashes(self):
        import editorial
        original = json.loads((R / 'config/editorial.json').read_text())
        self.write(original)
        a = article()
        editorial.import_article(a, self.source, 'create', hashlib.sha256(self.source.read_bytes()).hexdigest(),
                                 original['editorial_version'], 'synthetic-integration-r2', now=NOW)
        first = build_site.build_site(self.root, now=NOW)
        second = build_site.build_site(self.root, now=NOW)
        self.assertEqual(first, second)
        public = json.loads((self.root / '.site/data/editorial.json').read_text())
        self.assertEqual(public['articles'][0]['id'], a['id'])
        active_ids = [item['id'] for item in public['articles']
                      if editorial.timestamp(item['published_at']) <= NOW < editorial.timestamp(item['home_until'])]
        self.assertEqual(first['manifest']['active_article_ids'], active_ids)
        for old in original['articles']:
            self.assertEqual(next(x for x in public['articles'] if x['id'] == old['id']), old)
        for link in first['manifest']['articles']:
            actual = next(x for x in public['articles'] if x['id'] == link['id'])
            self.assertEqual(link['sha256'], editorial.canonical_hash(actual))
        self.assertEqual((self.root / '.site/data/archive/2026-10-22.json').read_bytes(), self.latest)

    def test_future_or_unreviewed_new_article_is_not_published(self):
        for change in ('future', 'pending'):
            a = article()
            if change == 'future': a['published_at'] = '2099-01-01T00:00:00+09:00'
            else: a['review']['sourcecheck']['status'] = 'pending'
            self.write(collection(a))
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_site.build_site(self.root, now=NOW)
            self.assertFalse((self.root / '.site').exists())

    def test_valid_expired_archive_remains_buildable(self):
        from datetime import timedelta
        build_site.build_site(self.root, now=NOW + timedelta(days=30))
        self.assertTrue((self.root / '.site/data/editorial.json').exists())

    def test_concurrent_source_change_refuses_generated_artifacts(self):
        original = build_site.build_outputs
        def change(payload, raw, **kwargs):
            result = original(payload, raw, **kwargs)
            self.source.write_text('{}')
            return result
        with patch.object(build_site, 'build_outputs', side_effect=change), self.assertRaises(ValueError):
            build_site.build_site(self.root, now=NOW)
        self.assertFalse((self.root / '.site').exists())


if __name__ == '__main__':
    unittest.main()
