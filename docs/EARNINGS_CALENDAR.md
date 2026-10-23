# 決算予定と発表済み詳報

- `data/earnings.json.schedule` is **planned**, not a release or article. Existing TDnet `items` and editorial manuscripts are unchanged.
- `tools/earnings_watch.py:update_watch` calls `tools/earnings_schedule.py:update_schedule` from the existing daily `tools/update_news.py` path. No new workflow, cron, settings, paid API, credentials, packages, or generated earnings numbers.
- Source: JPX public financial-announcement page, its currently linked **monthly** `kessanMM_DDDD.xlsx` files only (at most four). The separately formatted next-business-day workbook is intentionally not parsed. JPX says monthly coverage is for companies with quarter/year ends in the listed months; schedules can change and omissions are possible.
- Match each code against Nikkei's current official component page, requiring exactly 225 members. Company, exact announcement date, fiscal year end and quarter are taken from JPX, not inferred. Non-specific/undecided dates are omitted. There is no company article until released results have been separately sourced and edited.
- Source `as_of` comes from the workbook's explicit Japanese `YYYY年M月D日 現在` line. `checked_at` records the retrieval attempt, not the source publication time. Each row retains both its workbook link and source as-of date.
- `schedule.state` is independent of the TDnet monitor state. On failure, keep the last known schedule and indicate failed/stale. Zero visible rows means no confirmed dates to display, **not** that no companies are scheduled. Calendar displays today through 13 days ahead (14 calendar days); passing a planned date never creates a release.
- Downloader retains existing HTTPS host/redirect allowlist, 12-second timeout and 2 MB response limit. XLSX expansion is limited to 100 entries and 12 MB total; only expected workbook/shared strings/first worksheet paths and explicit known headers are read. 1904-date workbooks and changed schemas fail closed.

## Verified initial snapshot

Fetched 2026-10-23 16:15:25 JST. Official components: 225. Parsed planned rows: 220 (includes past dates in retained snapshot; UI displays the next 14 days).

- JPX `kessan08_1002.xlsx`: as of 2026-10-01.
- JPX `kessan09_1023.xlsx`: as of 2026-10-22.
- Root: https://www.jpx.co.jp/listing/event-schedules/financial-announcement/
- Membership: https://indexes.nikkei.co.jp/nkave/index/component

Refresh: existing daily update invokes the monitor; manually `python tools/earnings_watch.py` refreshes both schedule and release detection. Failure of either status does not represent success of the other. This is not real-time, exhaustive coverage or automatic financial analysis.

## Verification

`python -m unittest discover -s tests -v` and `node --test tests/test_earnings_calendar.js`.
Unit coverage: verified-member filtering, unspecified dates, source as-of extraction, schema rejection, last-known retention, official-link allowlist, ZIP entry bound, today/future vs past dates, plan/release separation, and no false 'none scheduled' statement. Existing legacy manuscript hash tests remain unchanged.
