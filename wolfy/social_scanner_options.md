# Wolfy free financial Twitter/X scanner options

Date: 2026-06-01
Task: t_e93dcc88

## Executive recommendation

Use Stocktwits public JSON endpoints as Wolfy's free social-momentum prototype, then optionally add official X API/xurl later if the user accepts pay-per-use costs and completes credentials outside the agent session.

Reason: xurl is not installed in this environment, X is now pay-per-use for meaningful reads, public X browser search is login/bot-wall prone, and Nitter-style mirrors are operationally unstable. Stocktwits is purpose-built around cashtags, returned live JSON during testing with no credentials, and maps directly to Wolfy's Robinhood-tradable U.S. stock/ETF workflow.

Prototype delivered:

- `/root/.hermes/wolfy/stocktwits_social_scanner.py`
- `/root/.hermes/wolfy/test_stocktwits_social_scanner.py`

The scanner stores into SQLite tables `social_scanner_runs` and `social_scanner_messages` when not run with `--dry-run`.

## Environment check

Command checked without reading any secret files:

```bash
command -v xurl
xurl --help
xurl auth status
```

Result: `xurl` is not installed (`command not found`). No `~/.xurl` file was read.

If X is later approved, install xurl and have the user do the auth flow manually; agents must only verify with `xurl auth status` and must not read or print `~/.xurl`.

## Option comparison

| Option | Free/legal posture | Practicality for Wolfy | Main limitations | Recommendation |
| --- | --- | --- | --- | --- |
| Official X API via xurl | Legal official path; current docs describe pay-per-use credits, not a practical free read tier. Recent search is documented for all developers, but reads are priced per resource. | Best X fidelity if paid/credentialed. Structured search, filtered stream, rate-limit headers. | xurl absent; user must create app/auth manually; read costs add up; API plan/permission errors are common. | Keep as paid upgrade path, not default free scanner. |
| Public X browser search | Free for a human in a browser. | Poor for automation. | Login walls, bot blocking, brittle DOM, likely Terms/risk issues if scraped. The YouTube transcript task already hit bot/sign-in blocking in this environment. | Do not build scheduled automation around this. |
| Nitter/RSS mirrors | Sometimes free and RSS-like. | Low reliability. Instance status endpoint showed healthy mirrors, but RSS was false for at least the top checked host; mirrors are unofficial and can disappear. | Unofficial, unstable, may break when X changes access. | Only manual fallback for one-off investigation, not production. |
| Stocktwits API | Free public JSON endpoint worked live for symbol streams and trending symbols. Finance-native cashtags. | Strong fit for social-momentum signals and meme/retail chatter. | Not X; less institutional/CEO flow; API terms/rate limits should be respected; sentiment is user-provided and noisy. | Build now. Use as default free substitute. |
| Reddit | Official API exists, but unauthenticated JSON returned 403 from this environment. | Useful if authenticated for r/stocks/r/wallstreetbets chatter. | API credentials/rate policies; noisy, slower ticker relevance. | Later optional source if user wants credentials. |
| Google News/Yahoo Finance RSS/SEC RSS | Free-ish feeds accessible; Yahoo Finance RSS and SEC RSS worked; Google News RSS terms restrict non-personal/non-commercial uses. | Good for news/catalyst, not social chatter. | Feed licensing/terms; not a Twitter replacement. | Use in separate catalyst/news pipeline, not social scanner core. |

## X API notes from current docs

Observed from docs.x.com on 2026-06-01:

- X API is described as pay-per-use with credits and no subscription commitment.
- Pricing page lists read operations such as `Posts: Read` at `$0.005 per resource`; owned reads are `$0.001 per resource` for the app owner's own data.
- Search docs list `GET /2/tweets/search/recent` as searching the last 7 days and available to all developers, while full archive search is pay-per-use/Enterprise.
- Rate-limit docs list recent search at `450/15min` per app and `300/15min` per user, with 10 default / 100 max results and 512 query length.

Interpretation: official X is usable, but it is not the best "free" foundation for Wolfy's recurring market scanner unless the user explicitly accepts X API credit spend.

## Prototype usage

Dry run live scan:

```bash
cd /root/.hermes/wolfy
python3 stocktwits_social_scanner.py --symbols SPY AAPL NVDA --include-trending --trending-limit 3 --message-limit 5 --dry-run --json
```

Persist to Wolfy's SQLite DB:

```bash
cd /root/.hermes/wolfy
python3 stocktwits_social_scanner.py --symbols SPY QQQ AAPL NVDA TSLA --include-trending --trending-limit 10 --message-limit 30 --json
```

Suggested first cron cadence: every 30-60 minutes during market hours. Keep message limits modest until we observe any rate limiting.

## Verification performed

- `python3 -m pytest -q test_stocktwits_social_scanner.py` -> 5 passed.
- Live dry run against Stocktwits for SPY/AAPL/NVDA plus 3 trending symbols returned 72 normalized message rows across 28 tickers, with no errors.
- Live write test against a temporary SQLite DB inserted 18 message rows and one run row; no production DB write was performed during this task.

## Next integration ideas

1. Add this scanner to Wolfy's hourly context only as a low-confidence social signal: "retail chatter / candidate discovery," never as standalone trade conviction.
2. Cross-check any Stocktwits lead against existing suspicious-activity filters before creating alpha leads.
3. Add a source quality penalty for tiny-float meme names and single-author bursts.
4. If the user approves X spending, install xurl and add an official X adapter behind the same `social_scanner_messages` schema.
