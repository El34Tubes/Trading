#!/usr/bin/env python3
import hashlib
from psycopg.types.json import Jsonb
from wolfy_db import connect_postgres

TITLE = "C run-469 research: Q2 earnings and capital return support context, but approved breakout gates fail"
SOURCE_URL = "https://www.sec.gov/Archives/edgar/data/831001/000110465926083383/c-20260714xex99d1.htm"
TENQ_URL = "https://www.sec.gov/Archives/edgar/data/831001/000083100126000045/c-20260630.htm"
BODY = """FACT (deterministic scanner provenance): Postgres scanner_results id 52534/run 469 recorded Citigroup (C) from September 4, 2026 closing data with close 137.90, score 7.7018, 5/20/60-day returns of +3.7622%/+2.1481%/+3.3888%, approximately 8.091M-share average volume, bull_50_200 trend, squeeze flag 1, squeeze ratio 0.7933, ATR/close 2.0206%, zero extension penalty and no gap reversal. One-day/20-day and five-day/20-day volume ratios were only 0.3217x and 0.8856x. The close was 2.1153% below the recorded 20-day high and 6.3961% above the recorded 20-day low. This is close-time discovery evidence, not a validated strategy signal or setup.

FACT (benchmark and canonical-data defects): Scanner run 469 contains ten rows and no SPY or QQQ row. For all ten rows, notes.rs_spy_20 and notes.rs_qqq_20 exactly equal that ticker's own 20-day return. C's reported “RS+2.1 vs SPY/QQQ” is therefore an absent-benchmark zero fallback, not measured excess return; benchmark-relative reasons and their score contribution are invalid. Postgres has no canonical C prices or features row for September 4, 2026, so the scanner-local trend, squeeze and liquidity fields lack canonical EOD confirmation.

FACT (filed operating and capital-return context): Citigroup's July 14, 2026 8-K Exhibit 99.1 reported Q2 net income of $5.8B/$3.15 diluted EPS on $24.766B revenue, versus $4.0B/$1.96 on $21.668B a year earlier. Revenue rose 14%, while operating expense rose 5% to $14.215B, producing positive operating leverage. Net credit losses rose 8% to $2.404B, but total provision for credit losses declined 12% to $2.522B because the net allowance build and other provisions were lower. The release reported 13.0% RoTCE, a 12.8% CET1 ratio, $114.74 book value per share and $100.89 tangible book value per share. Management said Services posted record quarterly revenue; Markets benefited from FX/spread products and 45% Equities growth; Banking revenue rose 34%; and Wealth revenue increased for a ninth consecutive quarter. These are issuer-reported results, not a causal attribution for the later scanner move.

FACT (capital catalyst and balance-sheet cushion): Citi reported returning about $5.0B to common shareholders in Q2, including $4.0B of repurchases, under its 2026 $30B buyback program. The August 6 Form 10-Q says June 30 CET1 was about 120 basis points above its regulatory requirement and records a declared quarterly dividend increase from $0.60 to $0.67 per share. The same filing reports completion of the additional American Airlines co-branded card portfolio acquisition, the Poland consumer-bank sale and another Banamex equity sale. Earnings growth, announced capital returns and simplification milestones are durable public support factors, but the SEC submissions feed shows no new operating 8-K between the July 14 earnings filing and the September 4 scanner date; the August 6 10-Q chiefly formalized quarter-end information. Thus no discrete proximate filing catalyst was verified for September 4.

FACT (filed risks): The 10-Q says the multiyear transformation, including remediation of the 2020 Federal Reserve and OCC consent orders, has not been linear. The filing describes those orders as requiring improvements to enterprise risk management, compliance, data-quality governance and internal controls, and notes 2024 civil-money-penalty orders over remediation shortcomings. Q2 net credit losses increased, and management attributed the net allowance build to portfolio growth and macro-variable changes, partly offset by portfolio-quality improvement. Citi also identifies exposure to interest-rate and monetary-policy changes, market volatility, funding costs, consumer/corporate credit, leveraged finance and non-bank financial institutions, geopolitical risks, emerging markets, regulation, sanctions and legal proceedings. U.S. Consumer Cards investment, the American Airlines portfolio integration, transformation execution and capital requirements therefore remain material monitoring variables.

FACT (liquidity/manipulation context): Run 469 marked liquidity_pass true, measured approximately 8.091M average daily shares and a 0.2497 liquidity-spread proxy; at the recorded close, average-volume dollar turnover was about $1.116B. The lead's suspicious-activity screen was clear, and SEC-filed earnings/capital-return disclosures provide conventional public context. These facts make a classic thin-float promotion an implausible primary explanation, but they do not prove absence of manipulation, informed trading, data error, benchmark error, macro/sector flows or adverse execution. The 0.3217x one-day volume ratio does not confirm fresh accumulation.

FACT (approved-strategy relevance): Approved strategy_rule 4070 requires SPY above its 50-day average, a close-confirmed breakout, valid 20-day excess return versus SPY of at least 2%, volume of at least 1.2x, prior-low risk no greater than 5%, and complete deterministic risk fields. C fails the recorded close-confirmed breakout and one-day-volume gates; its distance above the available 20-day low is 6.3961%, above the rule's 5% ceiling if that field is used as the prior-low proxy. It also lacks valid benchmark excess return, an independent SPY-regime row and canonical EOD confirmation. Postgres contains no C signal dated September 4, 2026 and no C setup. Older C signal rows are historical/research-only and do not qualify this observation under rule 4070.

JUDGMENT (research interpretation, not a trade recommendation): Q2 earnings growth, broad business revenue momentum, capital returns and divestiture progress supply a coherent durable fundamental backdrop. Rising net credit losses, consumer-card investment/integration, consent-order remediation, macro/rate sensitivity and capital regulation remain counterweights. More importantly for Wolfy, the scanner's benchmark-relative strength is invalid and every decisive approved breakout gate is failed or missing. Retain as researched-watchlist/research-only/no-trade. Future review should use complete post-close canonical C and SPY data, subsequent SEC filings, credit and card-cohort trends, transformation milestones, capital ratios and buyback execution; do not infer edge, trigger, stop, size or rank from this note."""
FP = hashlib.sha256(b"jonah:scanner-alpha:C:run469:task4046:v1").hexdigest()

conn = connect_postgres()
try:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM agent_artifacts WHERE artifact_type=%s AND source_fingerprint=%s AND title=%s", ('scanner_alpha_research', FP, TITLE))
        existing = cur.fetchone()
        cur.execute(
            """
            INSERT INTO agent_artifacts
              (agent_name, artifact_type, title, body, source_url, source_final_url,
               source_fingerprint, topic_tags, ticker_symbols, confidence, freshness)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (artifact_type, source_fingerprint, title)
            DO UPDATE SET body=EXCLUDED.body, source_url=EXCLUDED.source_url,
                          source_final_url=EXCLUDED.source_final_url,
                          topic_tags=EXCLUDED.topic_tags, ticker_symbols=EXCLUDED.ticker_symbols,
                          confidence=EXCLUDED.confidence, freshness=EXCLUDED.freshness,
                          updated_at=now()
            RETURNING id
            """,
            ('Jonah', 'scanner_alpha_research', TITLE, BODY, SOURCE_URL, TENQ_URL, FP,
             ['alpha_search','scanner_alpha_research','public_filing','watchlist','banking','capital_return','credit_risk','data_quality'],
             ['C'], 0.93, 'current'),
        )
        artifact_id = cur.fetchone()[0]
        # Fundamental/catalyst notes remain auditable artifacts but are deliberately
        # excluded from knowledge_chunks under the technical-retrieval policy.
        cur.execute("DELETE FROM knowledge_chunks WHERE source_table=%s AND source_id=%s", ('agent_artifacts', str(artifact_id)))
        filing_context = (
            'SEC Q2 2026 earnings/10-Q reviewed: net income $5.8B, revenue $24.766B, '
            'CET1 12.8%, Q2 common capital return about $5.0B; transformation/consent-order '
            'and credit risks remain. No proximate operating 8-K after July 14 through scanner date.'
        )
        next_q = (
            'Research-only: validate future C observations using canonical post-close C/SPY features, '
            'a real benchmark-relative return, approved rule-4070 signal, and subsequent SEC credit, '
            'capital-return and transformation disclosures.'
        )
        cur.execute(
            """UPDATE alpha_leads
               SET status='researched_watchlist', filing_context=%s,
                   next_research_question=%s, updated_at=now()
               WHERE id=3982""",
            (filing_context, next_q),
        )
    conn.commit()
    print(f'ARTIFACT_ID={artifact_id}')
    print(f'RECORDS_CREATED={0 if existing else 1}')
    print('ALPHA_LEAD_UPDATED=3982')
finally:
    conn.close()
