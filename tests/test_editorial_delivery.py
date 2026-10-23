"""Synthetic/offline delivery verification. Never contacts GitHub Pages."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / 'tools'))
import editorial_delivery as d

BASE = 'https://example.github.io/asa-brief/'


def fixture():
    # Only summary-facing fields: full manuscript validation is tested separately.
    return {'schema_version': 1, 'editorial_version': 'synthetic-edition-1', 'articles': [
        {'id': 'synthetic-a', 'title': '架空の試験記事', 'lead': 'これは実際のニュースではありません。',
         'published_at': '2026-10-22T09:00:00+09:00', 'home_until': '2026-10-25T00:00:00+09:00'}]}


def encoded(payload):
    return (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def files(payload):
    raw = encoded(payload)
    outputs = d.build_outputs(payload, raw)
    return outputs, {'editorial.json': raw, 'editorial-manifest.json': encoded(outputs['manifest']),
                     'editorial-summary.txt': outputs['summary'].encode('utf-8')}


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.payload = fixture()
        self.outputs, self.public = files(self.payload)
        self.called = []

    def fetch(self, url):
        self.called.append(url)
        self.assertTrue(url.startswith(BASE + 'data/'))
        self.assertIn('?asa_brief_sha=', url)
        return self.public[url.split('/')[-1].split('?')[0]]

    def verify(self):
        return d.verify_public(self.outputs['manifest'], BASE, downloader=self.fetch)

    def test_deterministic_linkage_no_network(self):
        with patch('urllib.request.build_opener', side_effect=AssertionError('unexpected network')):
            again = d.build_outputs(self.payload, encoded(self.payload))
        self.assertEqual(self.outputs, again)
        manifest = again['manifest']
        self.assertEqual(manifest['article_ids'], ['synthetic-a'])
        self.assertEqual(manifest['articles'][0]['sha256'], d.canonical_hash(self.payload['articles'][0]))
        self.assertEqual(manifest['manuscript_sha256'], hashlib.sha256(encoded(self.payload)).hexdigest())
        for key in ('id', 'title', 'lead', 'published_at', 'home_until'):
            self.assertIn(self.payload['articles'][0][key], again['summary'])
        self.assertIn('過去記事を含む', again['summary'])

    def test_canonical_hash_ignores_key_order_not_raw_identity(self):
        reordered = {key: self.payload[key] for key in reversed(self.payload)}
        self.assertEqual(d.canonical_hash(reordered), d.canonical_hash(self.payload))
        self.assertNotEqual(d.build_outputs(reordered, encoded(reordered))['manifest']['manuscript_sha256'],
                            self.outputs['manifest']['manuscript_sha256'])

    def test_summary_never_from_another_manuscript(self):
        altered = copy.deepcopy(self.payload)
        altered['articles'][0]['lead'] = '他の原稿'
        with self.assertRaisesRegex(ValueError, 'payload_bytes_mismatch'):
            d.build_outputs(altered, encoded(self.payload))

    def test_duplicate_ids_and_malformed_summary_input_rejected(self):
        bad = copy.deepcopy(self.payload)
        bad['articles'] *= 2
        with self.assertRaises(ValueError):
            d.build_outputs(bad, encoded(bad))
        for key in ('id', 'title', 'lead', 'published_at', 'home_until'):
            bad = copy.deepcopy(self.payload)
            del bad['articles'][0][key]
            with self.subTest(field=key), self.assertRaises(ValueError):
                d.build_outputs(bad, encoded(bad))

    def test_empty_inventory_valid(self):
        self.payload['articles'] = []
        out = d.build_outputs(self.payload, encoded(self.payload))
        self.assertEqual(out['manifest']['article_ids'], [])
        self.assertIn('編集記事はありません', out['summary'])

    def test_success_checks_three_files_not_thread_receipt(self):
        result = self.verify()
        self.assertEqual(result['state'], 'success')
        self.assertEqual(result['reason'], 'exact_match')
        self.assertEqual(result['conversation_delivery'], 'not_sent')
        self.assertEqual(len(self.called), 3)

    def test_internally_consistent_old_edition_delayed(self):
        old = copy.deepcopy(self.payload)
        old['editorial_version'] = 'synthetic-old'
        _, self.public = files(old)
        result = self.verify()
        self.assertEqual((result['state'], result['reason']), ('delayed', 'different_edition'))

    def test_same_edition_changed_bytes_never_success(self):
        changed = copy.deepcopy(self.payload)
        changed['articles'][0]['lead'] = '別の内容'
        _, self.public = files(changed)
        self.assertEqual((self.verify()['state'], self.verify()['reason']),
                         ('failed', 'edition_content_mismatch'))

    def test_mixed_publication_or_changed_ids_fail(self):
        for part in ('editorial.json', 'editorial-manifest.json', 'editorial-summary.txt'):
            _, self.public = files(self.payload)
            changed = copy.deepcopy(self.payload)
            changed['articles'][0]['id'] = 'another-id'
            _, changed_files = files(changed)
            self.public[part] = changed_files[part]
            with self.subTest(part=part):
                self.assertEqual(self.verify()['state'], 'failed')

    def test_false_manifest_cannot_attest_changed_data(self):
        self.public['editorial.json'] = self.public['editorial.json'].replace('架空'.encode(), '改変'.encode())
        self.assertEqual(self.verify()['state'], 'failed')

    def test_invalid_json_duplicate_keys_nonfinite_and_oversize_fail(self):
        for raw in (b'<html>oops</html>', b'{"x":1,"x":2}', b'{"x":NaN}', b'\xff', b' ' * (d.MAX_BYTES + 1)):
            _, self.public = files(self.payload)
            self.public['editorial.json'] = raw
            with self.subTest(raw=raw[:20]):
                self.assertEqual(self.verify()['state'], 'failed')

    def test_network_and_http_failure_are_never_success(self):
        cases = [(TimeoutError(), 'delayed'), (urllib.error.URLError('offline'), 'delayed'),
                 (urllib.error.HTTPError(BASE, 404, 'not found', {}, None), 'delayed'),
                 (urllib.error.HTTPError(BASE, 503, 'unavailable', {}, None), 'delayed'),
                 (urllib.error.HTTPError(BASE, 403, 'forbidden', {}, None), 'failed'),
                 (urllib.error.HTTPError(BASE, 302, 'redirect', {}, None), 'failed')]
        for error, state in cases:
            with self.subTest(error=type(error).__name__, state=state):
                def fail(url):
                    raise error
                self.assertEqual(d.verify_public(self.outputs['manifest'], BASE, fail)['state'], state)

    def test_unsafe_endpoints_rejected_without_fetch(self):
        unsafe = ['http://example.github.io/repo', 'https://u:p@example.github.io/',
                  'https://127.0.0.1/', 'https://localhost/', 'https://[::1]/',
                  'https://example.github.io.attacker.example/', 'https://example.com/',
                  'https://example.github.io:444/', 'https://example.github.io/?token=secret',
                  'https://example.github.io/#fragment', 'https://example.github.io/../x',
                  'https://example.github.io/%2e%2e/x', 'https://example.github.io\\@attacker.example/']
        for url in unsafe:
            with self.subTest(url=url):
                result = d.verify_public(self.outputs['manifest'], url,
                                         lambda u: self.fail('must not fetch unsafe URL'))
                self.assertEqual((result['state'], result['reason']), ('failed', 'unsafe_public_url'))

    def test_redirect_handler_does_not_follow(self):
        self.assertIsNone(d._NoRedirect().redirect_request(None, None, 302, '', {}, 'http://127.0.0.1/'))

    def test_state_reports_share_identity_and_never_claim_posting(self):
        for state in ('success', 'delayed', 'failed'):
            report = d.delivery_status(self.outputs['manifest'], state, 'fixture')
            self.assertEqual(report['article_ids'], ['synthetic-a'])
            self.assertEqual(report['manuscript_sha256'], self.outputs['manifest']['manuscript_sha256'])
            self.assertEqual(report['conversation_delivery'], 'not_sent')
            self.assertIn('未実施', report['message'])
        with self.assertRaises(ValueError):
            d.delivery_status(self.outputs['manifest'], 'maybe', 'fixture')

    def test_invalid_expected_manifest_rejected(self):
        bad = copy.deepcopy(self.outputs['manifest'])
        bad['article_ids'] = ['wrong-id']
        with self.assertRaises(ValueError):
            d.verify_public(bad, BASE, self.fetch)
        self.assertEqual(self.called, [])

    def test_report_cli_cannot_manually_assert_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            expected = Path(tmp) / 'expected.json'
            expected.write_bytes(encoded(self.outputs['manifest']))
            args = ['report', '--expected', str(expected), '--state', 'failed', '--reason', 'deployment_failed']
            with patch('builtins.print'), patch('urllib.request.build_opener', side_effect=AssertionError('network')):
                self.assertEqual(d.main(args), 0)
            with patch('sys.stderr'), self.assertRaises(SystemExit):
                d.main(['report', '--expected', str(expected), '--state', 'success', '--reason', 'fake'])

    def test_boolean_schema_is_not_integer_schema(self):
        bad = copy.deepcopy(self.payload)
        bad['schema_version'] = True
        with self.assertRaises(ValueError):
            d.build_outputs(bad, encoded(bad))
        bad_manifest = copy.deepcopy(self.outputs['manifest'])
        bad_manifest['schema_version'] = True
        with self.assertRaises(ValueError):
            d.verify_public(bad_manifest, BASE, self.fetch)

    def test_cli_status_exit_code_success_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            expected, status = Path(tmp) / 'expected.json', Path(tmp) / 'status.json'
            expected.write_bytes(encoded(self.outputs['manifest']))
            args = ['verify', '--expected', str(expected), '--base-url', BASE, '--status-output', str(status)]
            with patch.object(d, '_download', self.fetch), patch('builtins.print'):
                self.assertEqual(d.main(args), 0)
                self.public['editorial-summary.txt'] = b'stale summary'
                self.assertEqual(d.main(args), 1)
            self.assertEqual(json.loads(status.read_text())['state'], 'failed')
            expected.write_text('invalid')
            with patch('builtins.print'):
                self.assertEqual(d.main(args), 1)
            self.assertEqual(json.loads(status.read_text())['reason'], 'invalid_expected_manifest')


if __name__ == '__main__':
    unittest.main()
