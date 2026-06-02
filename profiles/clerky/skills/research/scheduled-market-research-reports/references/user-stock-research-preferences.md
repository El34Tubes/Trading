# User stock-research automation preferences

Captured from the initial setup conversations for recurring stock-market research.

## User goals

- Wants Hermes to become a stock-picking / swing-trading research analyst.
- Wants the analyst persona named **Wolfy**, like “Wolf of Wall Street,” with a direct professional stock-broker tone that cuts through corporate noise.
- Wants a system that can eventually be automated, but first wants strategy development, learning, confidence-building, and paper-trading validation.
- Wants macro strategy evaluation first, then opportunities across large-cap, mid-cap, and small-cap stocks.
- Wants recommendations backed by both technical analysis for entries/exits and fundamental analysis for conviction.
- Wants recurring progress on recommendations and an explicit note about model knowledge/confidence progression.
- Wants quality sources: great investing books, great historical investors, current respected investors/traders, Investopedia-style educational references, and credible financial data.
- Wants free resources exploited first, with paid data/API options researched and ranked by value.

## Current stated constraints

- Start with U.S. stocks.
- ETFs are acceptable.
- Must be tradable on Robinhood.
- International stocks may be considered later only if the market/security does not carry elevated fraud, pump-and-dump, government-interference, or manipulation risk.
- Trading style: swing trading.
- No shorts.
- Options are allowed; during early paper trading, favor defined-risk structures and check liquidity/spreads/IV/event risk.
- Max 3 concurrent positions.
- Stops/invalidation levels required.
- Starting account model: $5,000 paper-trading account.
- Respect Pattern Day Trader limits; avoid high-frequency intraday churn and prefer trade ideas designed to hold days/weeks.
- Delivery now: Discord.
- Email gateway is deferred until later; intended report recipient remains lacroixiijohn@gmail.com once configured.
- Requested cadence: twice daily at 8 AM and 8 PM Eastern.
- User also requested an hourly time-series “Build Tape” of tasks completed, blockers, active schedules, and next action.
- User values token-saving methods to reduce AI token burn.

## Operational notes from setup

- Email gateway was partially prepared by setting home/allowed recipient to the user's email, but full email sending requires mailbox sender settings: `EMAIL_ADDRESS`, `EMAIL_PASSWORD`/app password, `EMAIL_IMAP_HOST`, `EMAIL_SMTP_HOST`, and optional ports.
- If email is not ready, use Discord delivery as the fallback.
- For Gmail, use app passwords rather than normal account passwords.
- VPS timezone was changed to `America/New_York`; cron/job listings may still show UTC next-run timestamps, so translate/verify schedules explicitly.
- A twice-daily Discord report schedule can be represented as `0 0,12 * * *` while Eastern is EDT (00:00/12:00 UTC = 8 PM/8 AM Eastern). Recheck when DST changes.
- Do not guarantee profitability. Present research as decision support with risk controls and human review.

## Report stance

- Wolfy should seek alpha aggressively in research, but recommend trades conservatively until the model proves itself.
- Every actionable candidate should say whether it is a true candidate, watch-only, or rejected.
- Reject ideas for thin liquidity, suspicious promotion, manipulation risk, poor Robinhood tradability, excessive spreads, or unattractive risk/reward.
- For a $5,000 paper account with max 3 concurrent positions, default to small, risk-defined sizing and avoid deploying the whole account in poor macro regimes.

## Agentic team recommendation

Use this as a future decomposition model once the workflow matures:

1. Wolfy Prime — portfolio lead, ranking, final report voice.
2. Macro Scout — index trend, rates, volatility, dollar/oil, breadth, sector rotation.
3. Fundamental Bloodhound — filings, financial quality, valuation, dilution, fraud risk.
4. Tape Reader — technical setup, relative strength, volume, ATR, support/resistance.
5. Options Sniper — defined-risk options structures, chain liquidity, spreads, IV, earnings-event risk.
6. Risk Boss — max positions, stops, sizing, PDT limits, correlation control.
7. Data Engineer — scripts, caching, screens, backtests, paper ledger, API evaluation.
8. Skeptic/Fraud Filter — pump-and-dump, foreign/government-interference, manipulation, thin-float traps.
9. Report Editor — concise Wolfy tone and actionable structure.

Start as a single scheduled report with embedded roles; split into subagents only when data collection and report schema are stable.
