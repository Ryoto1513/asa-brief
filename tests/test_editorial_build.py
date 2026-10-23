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
        def change(payload, raw):
            result = original(payload, raw)
            self.source.write_text('{}')
            return result
        with patch.object(build_site, 'build_outputs', side_effect=change), self.assertRaises(ValueError):
            build_site.build_site(self.root, now=NOW)
        self.assertFalse((self.root / '.site').exists())


if __name__ == '__main__':
    unittest.main()
