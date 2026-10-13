
# MoveInSync Employee App (`com.moveinsync.ets`) — Dynamic Play Store Rating Intelligence & Report Generation System

A reproducible, deterministic Python data pipeline and **Dynamic Play Store Rating Intelligence & Report Generation System** analyzing why corporate commuters give low ratings to MoveInSync's official employee transportation app (`com.moveinsync.ets`) on the Google Play Store, which problems are increasing, and what Product, Engineering, and Operations teams should fix first.

---

## Key Highlights & System Capabilities

* **Target Application**: `MoveInSync` (`com.moveinsync.ets`) — Official Employee Transportation App (`https://play.google.com/store/apps/details?id=com.moveinsync.ets&hl=en&gl=in`), explicitly separated from MoveInSync's 6 driver, field-supervisor, and workplace apps (`dev?id=7798917469890870335`).
* **Interactive Dynamic Report Generation (`app.py` + `src/dynamic_engine.py` + `index.html`)**:
  * **Configurable Reporting Controls**:
    * **Primary Analysis Period**: `Last 3 Months` (`3m`), `Last 6 Months` (`6m`), `Last 12 Months (Default)` (`12m`), or **Custom Date Range** (`custom_start` to `custom_end`, with quick preset buttons).
    * **Recent Trend Comparison**: `Previous 1 Month` (`1m`), `Previous 3 Months (Default)` (`3m`), or `Previous 6 Months` (`6m`), calculated with **strictly non-overlapping inclusive calendar boundaries** in `IST (UTC+05:30)`.
    * **Review Focus**: `Negative Reviews (1–2★) & Complaint Themes` (`negative`) or `All Reviews (1–5★)` (`all`).
    * **Optional Live Refresh**: Check **Refresh public Google Play reviews before analysis** to trigger live multi-pass collection (`src/collect.py`) before generating the report.
    * **One-Click HTML & PDF Export**: Every generated report is persisted to `reports/generated/<report_id>/` (`report_data.json`, `report_export.html`, `MoveInSync_Report_<report_id>.pdf`, and 5 dynamic `figures/*.png` charts) and can be downloaded directly via **Export HTML** or **Export PDF / Print** (`/api/pdf/<report_id>`).
* **Minimum Evidence Safeguards & Multi-Label Classification**:
  * **Sample Sizes Everywhere**: Every percentage and trend delta displays its exact sample size (`k/n`).
  * **Comparison Window Thresholds**: If the preceding comparison window has `0` relevant reviews, trends are labeled `"No baseline available"`. If either comparison window has fewer than `10` relevant reviews (or a theme has `< 10` matching reviews in both windows), the trend is labeled `"Insufficient evidence"` (`T = 3` neutral) rather than ranking small-sample noise as a meaningful increase.
  * **Zero-Review Safeguard**: Any theme with `0` matching reviews in the selected primary window is labeled `"No direct review evidence in this period"`, assigned `"Unranked (0 Reviews)"` with `priority_score = None`, and routed to **Preventative Operational Guardrails** (never ranked as a confirmed complaint priority, while preserving its intrinsic severity).
  * **Verified Representative Review Evidence**: Every representative review is verified to match its assigned theme (`classify_single_review_text`), displays its full `reviewId` and assignment reason, and prevents multi-label reviews from acting as the primary proof for unrelated themes.
* **Normalized `1–5` Evidence-Backed Prioritization & Separate Safety Escalation Track**:
  * **Evidence-Backed Priority Score (`Rank #1, #2, ...`)**:
    $$\text{Priority Score} = 0.30 F + 0.25 S + 0.20 T + 0.15 C + 0.10 E_{\text{ease}} \in [1.00, 5.00]$$
    combines **Frequency** ($F$, 30%), **Severity** ($S$, 25%), **Trend Shift** ($T$, 20%), **Evidence & Coverage Confidence** ($C$, 15%), and **Implementation Ease** ($E_{\text{ease}}$, 10%).
  * **Separate Safety Escalation Track**: Credible physical safety, SOS alarm, and night-shift security reports (`T01_SAFETY_SOS_EMERGENCY`) are routed to a dedicated **Separate Safety Escalation Track** card rather than inflating general product rankings when sample counts are low or zero.
* **Programmatic Data Coverage Auditing**:
  * Every run audits the selected date range against the snapshot's unfiltered collection coverage (`19 Jun 2025 – 11 Oct 2026`). If a custom range extends prior to `19 Jun 2025` (where Google Play pagination caps 5-star reviews before `06 Feb 2025`), the system surfaces the exact missing/partial interval, marks the sample mean as `Non-Repr.`, caps confidence $C \le 2$, and never silently substitutes older reviews.

---

## Report Structure (Main Report & Expandable Appendices)

### Main Report Sections
1. **Executive Summary & Three Most Important Evidence-Backed Problems**:
   * Three summary cards (*What Are Users Complaining About?*, *Which Problems Are Increasing?*, *What Should MoveInSync Fix First?*), Top 3 Evidence-Backed Problem cards, and the dedicated **Separate Safety Escalation Track** banner.
2. **Recent-versus-Preceding Trend Summary & Rating Distribution**:
   * Cohort distribution comparison table, 4 dynamic charts (Star Distribution, Monthly Volume & Low-Star Trend, Top Complaint Themes, Recent vs. Preceding Trend Shifts), and the full Complaint Trend Summary table.
3. **Recommended Actions in Priority Order**:
   * Priority Matrix chart and 7-field evidence-backed action cards (*User Problem*, *Supporting Evidence*, *Why Important*, *First Concrete Action*, *Responsible Team*, *Validation Metric*, *Missing Telemetry to Confirm*) with verified representative review quotes.
4. **Owners & Validation Metrics Summary**:
   * Executive lookup table mapping each ranked priority to its responsible team, first concrete action, and target validation metric.
5. **Data Coverage & Limitations**:
   * Concise summary of rating vs. review sentiment, data coverage bounds, theme overlap, and minimum evidence thresholds.

### Expandable Technical Appendices
* **Appendix A**: Detailed Theme Counts & Preventative Guardrails `[EXPAND]`
* **Appendix B**: Priority Scoring Methodology & Weights `[EXPAND]`
* **Appendix C**: Engineering Root-Cause Hypotheses & Internal Telemetry Checks `[EXPAND]`
* **Appendix D**: App-Version Anomaly Analysis in Selected Primary Window `[EXPAND]`

---

## Repository Structure

```text
moveinsync-ratings-analysis/
├── README.md                                           # Project overview, setup, web app usage, CLI & test guide
├── requirements.txt                                    # Pinned Python dependencies (pandas, numpy, matplotlib, google-play-scraper)
├── app.py                                              # HTTP Backend Server (/api/init, /api/generate, /api/export/<id>, /api/pdf/<id>)
├── index.html                                          # Dynamic Play Store Rating Intelligence & Report Generation Web UI
├── run_pipeline.py                                     # CLI entrypoint (--serve, --analyze, --collect, --all)
├── data/
│   ├── raw/                                            # Immutable raw Google Play snapshots
│   │   ├── app_metadata_latest.json                    # Verified store baseline (4.64★, 114,879 ratings, histogram)
│   │   ├── reviews_raw_latest.jsonl                    # Multi-pass raw review records (8,808 raw rows -> 5,008 unique)
│   │   └── manifest_latest.json                        # Collection audit log (pass parameters, counts, date bounds)
│   └── processed/                                      # Baseline static CSVs & JSON outputs
│       ├── reviews_master_classified.csv               # All 5,008 unique deduplicated reviews with theme labels
│       ├── reviews_primary_2025_09_to_2026_09.csv      # Baseline filtered dataset
│       ├── coverage_audit_table.csv                    # Pass-by-pass collection coverage & date-bound audit
│       ├── window_rating_distributions.csv             # Star distributions across Store Baseline & analytical windows
│       ├── monthly_trend_2025_09_to_2026_09.csv        # Month-by-month sample sizes, mean ratings, and 1–2★ shares
│       ├── theme_prioritization_scorecard.csv          # Normalized 1–5 factor scores, deltas, and priority rankings
│       ├── version_correlated_anomalies_primary.csv    # App version breakdown (highlighting v12.19 crash spike)
│       ├── theme_evidence_quotes.json                  # Verbatim review evidence with reviewId, date, star rating & version
│       └── analysis_summary.json                       # Machine-readable summary of baseline metrics
├── src/
│   ├── __init__.py
│   ├── collect.py                                      # Multi-pass collector with exponential backoff & manifest logging
│   ├── preprocess_and_classify.py                      # Deduplication, window partitioning & 10-theme regex taxonomy
│   ├── analyze_and_prioritize.py                       # Baseline delta calculations & prioritization scoring functions
│   ├── visualize.py                                    # Baseline static 300 DPI Matplotlib chart generator
│   └── dynamic_engine.py                               # Dynamic date-windowing, safeguards, chart rendering, HTML & PDF engine
├── tests/
│   └── verify_dynamic_engine.py                        # Comprehensive unit & regression test suite (Tests A–F + PDF verification)
└── reports/
    ├── RECOMMENDATION_REPORT.md                        # Markdown recommendation report
    ├── moveinsync3_fixed.pdf                           # Verified PDF output for the 3-month (12 Jul 2026 – 11 Oct 2026) window
    ├── figures/                                        # Baseline high-resolution (300 DPI) Matplotlib charts
    └── generated/                                      # Persisted dynamic report bundles (RPT-12M, RPT-3M, RPT-6M, custom runs)
```

---

## Quick Start & Local Execution

### 1. Install Dependencies
Requires **Python 3.10+** (tested on Python 3.11+). The dynamic web server uses Python's built-in `http.server.ThreadingHTTPServer`, so no extra web framework is required beyond `requirements.txt`:

```powershell
pip install -r requirements.txt
```

### 2. Launch the Dynamic Web Application (Recommended)
Start the local backend server and open `http://localhost:8000` in your browser:

```powershell
python app.py
# Or equivalently:
python run_pipeline.py --serve --port 8000
```

From the web interface (`http://localhost:8000`):
1. Choose **Primary Analysis Period** (`Last 3 Months`, `Last 6 Months`, `Last 12 Months (Default)`, or `Custom Date Range`).
2. Choose **Recent Trend Comparison** (`Previous 1 Month`, `Previous 3 Months (Default)`, or `Previous 6 Months`).
3. Choose **Review Focus** (`Negative Reviews (1–2★) & Complaint Themes` or `All Reviews (1–5★)`).
4. Click **Generate Report** to recalculate all distributions, complaint counts, percentage-point trend shifts, priority scores, charts, and representative quotes for the selected window.
5. Click **Export HTML** or **Export PDF / Print** to download the standalone HTML or PDF report.

### 3. Run the Automated Unit & Regression Test Suite
Run `tests/verify_dynamic_engine.py` to execute the unit tests (window filtering and classification consistency) and all 6 regression test scenarios (**Tests A–F**: normal 3m/12m periods, zero-review theme period, zero-review comparison window, `< 10` sub-threshold period, distinct custom date ranges, and incomplete historical coverage), plus live HTTP & PDF export verification:

```powershell
python tests/verify_dynamic_engine.py
```

### 4. Re-Run the Baseline CLI Pipeline
To regenerate the static baseline CSVs and charts in `data/processed/` and `reports/figures/`:

```powershell
python run_pipeline.py --analyze   # Offline deterministic run from saved raw snapshot (~5 seconds)
python run_pipeline.py --all       # Live Google Play Store scrape + full analysis
```
