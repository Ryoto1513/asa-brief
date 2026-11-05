# Chat news mirror publication

The public morning brief is a faithful mirror of the approved Chat news body, not a new RSS or editorial composition. Only the verified public `.md` and metadata files belong in `config/chat-briefs/`. Never add a conversation export, conversation ID/URL, prompt, private audit, user statement, or credential. Private acquisition evidence stays outside this repository.

## Canonical input

The date is the original edition's JST calendar date. `source_updated_at` records the version actually read; it is distinct from the body's information cutoff. Preserve wording, punctuation, headings, paragraphs, lists, tables, notes, source labels and URL order. Citation resolution must use the same full message; snippets are not a canonical body. Unsupported Markdown, unresolved citations, private links, hash mismatch or an unavailable manuscript stop the import. Do not regenerate an edition or fill its gaps with RSS/yesterday's news.

`python tools/build_site.py` validates the canonical files and stages only public assets, Chat mirror history and retained earnings data. Non-earnings legacy independent articles remain recoverable in repository history but are excluded from public output. The RSS collection schedule and earnings update pipeline are unchanged. A missing today's edition is shown as waiting, not relabeled older content.

## Release

1. Work on a new branch from freshly checked main. Run all Python tests and `tests/browser_chat_brief.py` with the already configured Playwright runtime; do not install new paid services or expand permissions.
2. Review the full diff, public-file allowlist and canonical body hashes. Ensure no private audit is included. Refresh main before the merge; do not overwrite RSS updates or force-push.
3. Main changes to canonical files or relevant public code trigger `editorial-delivery.yml`. It also supports explicit manual dispatch. Both publishers use the existing `asa-brief-publish` lock. The Chat publisher rejects obsolete queued event SHAs and both publishers reject a stale checkout immediately before deployment and public verification.
4. Do not assume a push made with `GITHUB_TOKEN` triggers a new workflow. Check the actual run for the exact commit. A test pass or uploaded artifact is not publication success.
5. `tools/chat_brief_verify.py --expected .site/data/chat-brief-manifest.json --base-url https://ryoto1513.github.io/asa-brief/ --status-output chat-brief-delivery-status.json` checks the public manifest bytes, all declared file hashes, canonical Markdown/JSON agreement, edition index and removal of declared obsolete endpoints. This is a single attempt; failed/unknown publication or content mismatch stops further publication, with no automatic rerun or rollback.
6. Confirm terminal workflow success and independently inspect the public body, headings/tables/sources and earnings UI in the browser. Report exact commit/run links and limitations; cloud Chromium is not actual iPhone Safari testing.

The application publication automation is configured separately for an 08:10 JST start; the separate 08:00 Chat delivery and existing RSS cron are not changed by these repository workflows. Browser refresh only reads already public data. This repository never claims that it sent a Chat message.

## Publication safeguards

Both existing publication workflows build first, then run the JavaScript regressions and Chromium fixture test against the exact staged `.site` files before uploading or deploying. This gate does not change the RSS schedule, feed selection, earnings pipeline, canonical manuscript or original Chat delivery schedule. Browser checks use the existing pinned Playwright package on a standard public-repository Ubuntu runner.

The non-deploying `editorial-checks.yml` workflow stores its result in workflow logs and the job summary only. It does not upload artifacts or use a persistent cache. Browser screenshot files remain temporary runner files. Standard public-repository runner use and logs do not add Actions storage charges. The Pages deployment artifact is separate: publishing still requires the existing Pages artifact, so do not infer an account-wide zero-storage-cost guarantee from a successful no-artifact check.

A chronology error now reports the edition, field and exact positive gap. In particular, an information cutoff later than the source's actual revision time is still rejected. Never round or rewrite either timestamp to make a failing manuscript pass. Review the canonical source first, and keep the last valid published build unchanged if the source cannot be verified.

When today's canonical edition is missing, the app continues to say so. A separately labelled button opens the most recent available historical edition only after the reader selects it; an older edition is never relabelled as today's news.
