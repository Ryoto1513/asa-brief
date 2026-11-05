"""Dependency-free guards for publication order, cost and retained schedules."""
from pathlib import Path
import unittest
R = Path(__file__).resolve().parents[1]

class PublicationSafetyTests(unittest.TestCase):
    def read(self, name):
        return (R/'.github/workflows'/name).read_text()

    def test_fixture_and_javascript_gate_precede_upload_in_both_publishers(self):
        for name in ('daily-news.yml', 'editorial-delivery.yml'):
            with self.subTest(workflow=name):
                text=self.read(name)
                build=text.index('run: python tools/build_site.py')
                javascript=text.index('node tests/test_briefing_dates.js')
                browser=text.index('run: python tests/browser_chat_brief.py\n')
                upload=text.index('uses: actions/upload-pages-artifact@v4')
                deploy=text.index('uses: actions/deploy-pages@v4')
                self.assertLess(build, javascript)
                self.assertLess(javascript, browser)
                self.assertLess(browser, upload)
                self.assertLess(upload, deploy)
                self.assertIn('group: asa-brief-publish', text)
                self.assertIn('cancel-in-progress: false', text)
                self.assertIn('test "$(git rev-parse HEAD)" = "$remote"', text)

    def test_checks_have_no_billable_artifact_or_persistent_cache(self):
        text=self.read('editorial-checks.yml')
        self.assertIn("github.event.repository.private == false", text)
        self.assertEqual(text.count('runs-on: ubuntu-latest'), 2)
        for forbidden in ('upload-artifact@', 'upload-pages-artifact@', 'actions/cache@', 'pages: write', 'id-token: write'):
            self.assertNotIn(forbidden,text)
        self.assertIn('$GITHUB_STEP_SUMMARY',text)

    def test_schedules_and_canonical_collection_unchanged(self):
        text=self.read('daily-news.yml')
        self.assertEqual([line.strip() for line in text.splitlines() if '- cron:' in line], ["- cron: '35 22 * * *'", "- cron: '40 23 * * *'"])
        self.assertIn('run: python tools/update_news.py',text)
        self.assertIn('git add data/',text)
        self.assertNotIn('schedule:',self.read('editorial-delivery.yml'))
        self.assertNotIn('uses: actions/upload-artifact@',self.read('editorial-delivery.yml'))

if __name__=='__main__':
    unittest.main()
