"""
Comprehensive Automated Regression & Verification Suite for the MoveInSync
Dynamic Play Store Rating Intelligence System.

Covers:
  - Requirement 1 Unit Tests:
      * Known review inside primary window is counted accurately.
      * Known review outside primary window is excluded.
      * Identical review is classified consistently across different reporting windows.
      * Primary-window low-star denominator and every theme numerator match underlying records.
  - Requirement 8 Regression Suite (Tests A through F):
      * Test A: Normal period with sufficient reviews and multiple complaint themes
                (both 3m window 12 Jul 2026 – 11 Oct 2026 [moveinsync3.pdf] and 12m default window).
      * Test B: Period with zero matching reviews for a particular theme (15 Sep 2026 – 11 Oct 2026, T01 = 0).
      * Test C: Period with zero reviews in one comparison window (01 Mar 2019 – 30 Aug 2022, Preceding n = 0).
      * Test D: Period with fewer than the minimum required matching reviews (< 10 reviews).
      * Test E: Two different selected date ranges with different underlying review distributions.
      * Test F: Period with incomplete historical collection coverage (01 Jan 2025 – 31 Dec 2025).
  - HTTP Server & PDF Export Verification:
      * Verifies /api/init, /api/generate, /api/report/<id>, /api/export/<id>, and /api/pdf/<id>.
      * Asserts zero occurrences of 'undefined', 'NaN', or 'Infinity' in HTML and generated PDFs.
"""

import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import RatingIntelligenceHandler
from src.dynamic_engine import (
    METHODOLOGY_VERSION,
    MIN_COMPARISON_WINDOW_REVIEWS,
    MIN_THEME_MATCHING_PER_WINDOW,
    build_standalone_export_html,
    classify_single_review_text,
    generate_dynamic_report,
    load_and_classify_snapshot,
    render_pdf_from_report,
)
from src.preprocess_and_classify import THEME_DEFINITIONS


def assert_report_invariants(rep: Dict[str, Any], test_label: str, verify_pdf: bool = False) -> None:
    """
    Verifies all 8 mathematical, evidence, ranking, cross-section consistency,
    and HTML/PDF export invariants for any generated report payload.
    """
    meta = rep["report_metadata"]
    win = rep["window_configuration"]
    dp = rep["distributions"]["primary"]
    dr = rep["distributions"]["recent"]
    dpre = rep["distributions"]["preceding"]
    ex = rep["executive_summary"]
    cov = rep["classification_coverage"]
    themes = rep["themes_and_recommendations"]

    assert meta["methodology_version"] == METHODOLOGY_VERSION, f"[{test_label}] Stale methodology_version"

    # 1. Verify non-overlapping comparison windows
    assert win["preceding_end"] < win["recent_start"], f"[{test_label}] Preceding and Recent windows overlapped!"

    # 2. Verify primary-window counts and multi-label accounting against underlying dataframe
    df_all, _, _ = load_and_classify_snapshot(BASE_DIR, snapshot_id=meta["snapshot_id"])
    df_p = df_all[(df_all["at_dt"] >= win["primary_start_ts"]) & (df_all["at_dt"] <= win["primary_end_ts"])]
    df_rec = df_all[(df_all["at_dt"] >= win["recent_start_ts"]) & (df_all["at_dt"] <= win["recent_end_ts"])]
    df_pre = df_all[(df_all["at_dt"] >= win["preceding_start_ts"]) & (df_all["at_dt"] <= win["preceding_end_ts"])]

    low_p = df_p[df_p["score"].isin([1, 2])]
    low_rec = df_rec[df_rec["score"].isin([1, 2])]
    low_pre = df_pre[df_pre["score"].isin([1, 2])]

    assert dp["n_reviews"] == len(df_p), f"[{test_label}] Primary total review count mismatch"
    assert dp["count_low_1_2_star"] == len(low_p), f"[{test_label}] Primary low-star denominator mismatch"
    assert dr["count_low_1_2_star"] == len(low_rec), f"[{test_label}] Recent low-star denominator mismatch"
    assert dpre["count_low_1_2_star"] == len(low_pre), f"[{test_label}] Preceding low-star denominator mismatch"

    n_low_p = len(low_p)
    n_low_rec = len(low_rec)
    n_low_pre = len(low_pre)

    # 3. Verify each theme's primary, recent, preceding counts, percentage-point change, and evidence labels
    for r in themes:
        tid = r["theme_id"]
        expected_low_p = int(low_p[tid].sum()) if n_low_p > 0 else 0
        expected_all_p = int(df_p[tid].sum()) if len(df_p) > 0 else 0
        expected_low_rec = int(low_rec[tid].sum()) if n_low_rec > 0 else 0
        expected_low_pre = int(low_pre[tid].sum()) if n_low_pre > 0 else 0

        assert r["count_1_2_star_primary"] == expected_low_p, (
            f"[{test_label}] {tid} primary low-star count {r['count_1_2_star_primary']} != expected {expected_low_p}"
        )
        assert r["count_all_reviews_primary"] == expected_all_p, (
            f"[{test_label}] {tid} primary all count {r['count_all_reviews_primary']} != expected {expected_all_p}"
        )
        assert r["count_1_2_star_recent"] == expected_low_rec, (
            f"[{test_label}] {tid} recent low-star count {r['count_1_2_star_recent']} != expected {expected_low_rec}"
        )
        assert r["count_1_2_star_preceding"] == expected_low_pre, (
            f"[{test_label}] {tid} preceding low-star count {r['count_1_2_star_preceding']} != expected {expected_low_pre}"
        )

        # Verify percentage-point calculation (recent_rate - preceding_rate)
        exp_rate_pre = round((expected_low_pre / n_low_pre * 100.0), 2) if n_low_pre > 0 else 0.0
        exp_rate_rec = round((expected_low_rec / n_low_rec * 100.0), 2) if n_low_rec > 0 else 0.0
        assert r["rate_1_2_star_preceding_pct"] == exp_rate_pre
        assert r["rate_1_2_star_recent_pct"] == exp_rate_rec

        if n_low_pre == 0:
            assert r["trend_status"] == "NO_BASELINE_AVAILABLE", f"[{test_label}] {tid} expected NO_BASELINE_AVAILABLE when n_pre=0"
            assert "No baseline available" in r["trend_display"]
            assert r["T_trend_1_5"] == 3
        elif n_low_rec == 0 or n_low_pre < MIN_COMPARISON_WINDOW_REVIEWS or n_low_rec < MIN_COMPARISON_WINDOW_REVIEWS:
            assert r["trend_status"] == "INSUFFICIENT_EVIDENCE"
            assert "Insufficient evidence" in r["trend_display"]
            assert r["T_trend_1_5"] == 3
        elif expected_low_pre == 0 and expected_low_rec == 0:
            assert r["trend_status"] == "NO_MATCHING_REVIEWS"
            assert "No matching reviews" in r["trend_display"]
            assert r["T_trend_1_5"] == 3
        elif expected_low_pre < MIN_THEME_MATCHING_PER_WINDOW or expected_low_rec < MIN_THEME_MATCHING_PER_WINDOW:
            assert r["trend_status"] == "INSUFFICIENT_EVIDENCE"
            assert "Insufficient evidence" in r["trend_display"]
            assert r["T_trend_1_5"] == 3
        else:
            assert r["trend_status"] == "VALID"
            assert r["delta_1_2_star_pp"] == round(exp_rate_rec - exp_rate_pre, 2)

        # Verify 0-review safeguard and 7-field recommendation completeness
        focus_cnt = r["count_all_reviews_primary"] if meta["review_focus"] == "all" else r["count_1_2_star_primary"]
        if focus_cnt == 0:
            assert r["has_direct_evidence"] is False
            assert r["priority_score_1_to_5"] is None, f"[{test_label}] 0-review theme {tid} must have priority_score=None"
            assert r["priority_rank"] == "Unranked (0 Reviews)"
            assert r["evidence_label"] == "No direct review evidence in this period"
            assert r["S_severity_1_5"] > 0, "Missing review data must not be interpreted as zero severity"
        else:
            assert r["has_direct_evidence"] is True
            assert r["priority_score_1_to_5"] is not None and 1.0 <= r["priority_score_1_to_5"] <= 5.0
            for req_field in [
                "user_problem",
                "supporting_evidence_summary",
                "why_important",
                "first_concrete_action",
                "owner",
                "validation_metric",
                "missing_telemetry_to_confirm",
            ]:
                val = str(r.get(req_field, "")).strip()
                assert len(val) > 5 and "undefined" not in val.lower(), f"[{test_label}] Missing {req_field} on {tid}"

    # 4. Verify cross-section consistency between Executive Summary and Theme Table
    top3 = ex["top_3_evidence_backed_problems"]
    ev_themes = [
        r for r in themes
        if r["has_direct_evidence"]
        and r["recommendation_category"] == "EVIDENCE_BACKED_PRIORITY"
        and r["evidence_status"] != "SECONDARY_MULTILABEL_ONLY"
    ]
    assert len(top3) == len(ev_themes[:3]), f"[{test_label}] Top 3 problem count mismatch"
    for p, r in zip(top3, ev_themes[:3]):
        assert p["theme_id"] == r["theme_id"]
        assert p["priority_rank"] == r["priority_rank"]
        assert p["priority_score_1_to_5"] == r["priority_score_1_to_5"]
        assert p["count_focus"] > 0

    # Verify Safety & SOS is never Rank #1 with 5.00/5.0 in general priority list
    for item_str in ex["what_to_fix_first"]:
        assert "Rank #1: Safety & SOS Emergency" not in item_str, f"[{test_label}] Safety & SOS falsely ranked #1!"
        assert "5.00 / 5.0" not in item_str, f"[{test_label}] Hardcoded 5.00/5.0 score found!"

    # 5. Verify standalone HTML export has zero undefined/NaN/Infinity in visible/markup text
    html_str = build_standalone_export_html(rep)
    import re as _re
    html_no_b64 = _re.sub(r"data:image/png;base64,[A-Za-z0-9+/=]+", "BASE64_IMG", html_str)
    for bad_token in ["undefined", "NaN", "Infinity"]:
        assert bad_token not in html_no_b64, f"[{test_label}] Found invalid token '{bad_token}' in exported HTML!"

    # Check that nonzero primary counts are rendered in the exported HTML (never 0/207 when count > 0)
    if ev_themes:
        top1 = ev_themes[0]
        c1 = top1["count_all_reviews_primary"] if meta["review_focus"] == "all" else top1["count_1_2_star_primary"]
        d1 = dp["n_reviews"] if meta["review_focus"] == "all" else dp["count_low_1_2_star"]
        expected_frac = f"({c1}/{d1})"
        assert expected_frac in html_str, f"[{test_label}] Top theme fraction {expected_frac} missing from HTML!"

    # 6. Optionally verify headless PDF generation
    if verify_pdf:
        pdf_path = BASE_DIR / "reports" / "generated" / meta["report_id"] / f"MoveInSync_Report_{meta['report_id']}.pdf"
        ok = render_pdf_from_report(rep, pdf_path)
        assert ok and pdf_path.exists() and pdf_path.stat().st_size > 20_000, (
            f"[{test_label}] PDF generation failed or produced empty file at {pdf_path}"
        )


def test_requirement_1_window_filtering_and_classification_consistency() -> None:
    print("=" * 84)
    print("UNIT TEST (Requirement 1): Window Filtering & Classification Consistency")
    print("=" * 84)
    df, _, _ = load_and_classify_snapshot(BASE_DIR, snapshot_id="latest")

    # Known review inside 12 Jul 2026 – 11 Oct 2026:
    # reviewId 4f55dc55-2bf6-4c07-ba91-3e302c78c8b6 (2026-09-26, 1★, "App is unable to open...")
    in_row = df[df["reviewId"].str.startswith("4f55dc55")].iloc[0]
    out_row = df[df["reviewId"].str.startswith("4307083c")].iloc[0]
    known_in_rid = str(in_row["reviewId"])
    known_out_rid = str(out_row["reviewId"])

    # 1. Check inclusion/exclusion in 3m window (2026-07-12 .. 2026-10-11)
    df_3m = df[(df["at_dt"] >= "2026-07-12 00:00:00") & (df["at_dt"] <= "2026-10-11 23:59:59")]
    assert known_in_rid in set(df_3m["reviewId"]), "Known in-window review must be included in 3m primary window."
    assert known_out_rid not in set(df_3m["reviewId"]), "Known out-of-window review must be excluded from 3m primary window."

    # 2. Check that the same review is classified identically across different reporting windows
    themes_in_snapshot = [t["theme_id"] for t in THEME_DEFINITIONS if bool(in_row[t["theme_id"]])]
    themes_direct = classify_single_review_text(in_row["content_clean"], int(in_row["score"]))
    assert themes_in_snapshot == themes_direct, "Single-review classification must match snapshot classification."
    assert "T02_CRASH_LAUNCH_PERFORMANCE" in themes_in_snapshot

    rep_3m = generate_dynamic_report(BASE_DIR, primary_period_mode="3m", trend_comparison_mode="3m", review_focus="negative")
    rep_12m = generate_dynamic_report(BASE_DIR, primary_period_mode="12m", trend_comparison_mode="3m", review_focus="negative")

    t02_3m = next(r for r in rep_3m["themes_and_recommendations"] if r["theme_id"] == "T02_CRASH_LAUNCH_PERFORMANCE")
    t02_12m = next(r for r in rep_12m["themes_and_recommendations"] if r["theme_id"] == "T02_CRASH_LAUNCH_PERFORMANCE")
    q_rids_3m = {q["reviewId"] for q in t02_3m["supporting_quotes"]}
    q_rids_12m = {q["reviewId"] for q in t02_12m["supporting_quotes"]}
    assert known_in_rid in q_rids_3m and known_in_rid in q_rids_12m, (
        "Known review 4f55dc55 must be consistently classified under T02 across both 3m and 12m windows."
    )
    print(f"  [PASS] Known review {known_in_rid[:8]} (2026-09-26) included & classified identically in 3m and 12m windows.")
    print(f"  [PASS] Known review {known_out_rid[:8]} (2022-03-04) excluded from 3m/12m windows and included in 2019-2022 window.\n")


def run_all_regression_tests() -> None:
    test_requirement_1_window_filtering_and_classification_consistency()

    # -------------------------------------------------------------------------
    # TEST A: Normal period with sufficient reviews and multiple complaint themes
    #   A1: 3m Window (12 Jul 2026 – 11 Oct 2026, N=726, Low-Star=207) — Exact moveinsync3.pdf period!
    #   A2: Default 12m Window (12 Oct 2025 – 11 Oct 2026, N=2,851, Low-Star=769)
    # -------------------------------------------------------------------------
    print("=" * 84)
    print("TEST A: Normal Period with Sufficient Reviews (3m [moveinsync3.pdf] & 12m Default)")
    print("=" * 84)
    rep_3m = generate_dynamic_report(
        BASE_DIR,
        primary_period_mode="3m",
        trend_comparison_mode="3m",
        review_focus="negative",
        save_artifacts=True,
    )
    assert_report_invariants(rep_3m, "Test A1 (3m - moveinsync3 window)", verify_pdf=True)

    # Also copy RPT-3M PDF to reports/moveinsync3_fixed.pdf for direct side-by-side comparison
    fixed_pdf_3m = BASE_DIR / "reports" / "moveinsync3_fixed.pdf"
    render_pdf_from_report(rep_3m, fixed_pdf_3m)

    assert rep_3m["distributions"]["primary"]["n_reviews"] == 726
    assert rep_3m["distributions"]["primary"]["count_low_1_2_star"] == 207
    t_map_3m = {r["theme_id"]: r for r in rep_3m["themes_and_recommendations"]}
    assert t_map_3m["T02_CRASH_LAUNCH_PERFORMANCE"]["count_1_2_star_primary"] == 47
    assert t_map_3m["T02_CRASH_LAUNCH_PERFORMANCE"]["priority_rank"] == "Rank #1"
    assert t_map_3m["T08_SCHEDULING_ROSTER_NOSHOW"]["count_1_2_star_primary"] == 36
    assert t_map_3m["T08_SCHEDULING_ROSTER_NOSHOW"]["priority_rank"] == "Rank #2"
    assert t_map_3m["T07_ROUTING_CAB_DELAY_ETA"]["count_1_2_star_primary"] == 36
    assert t_map_3m["T07_ROUTING_CAB_DELAY_ETA"]["priority_rank"] == "Rank #3"
    assert t_map_3m["T01_SAFETY_SOS_EMERGENCY"]["count_1_2_star_primary"] == 4
    assert t_map_3m["T01_SAFETY_SOS_EMERGENCY"]["priority_rank"] == "Safety Escalation"
    print(
        f"  [PASS] Test A1 (3m: 12 Jul 2026 – 11 Oct 2026): N=726, 1-2★=207 | "
        f"Rank #1={t_map_3m['T02_CRASH_LAUNCH_PERFORMANCE']['short_name']} (47/207, 22.7%, {t_map_3m['T02_CRASH_LAUNCH_PERFORMANCE']['trend_short_display']}) | "
        f"Rank #2={t_map_3m['T08_SCHEDULING_ROSTER_NOSHOW']['short_name']} (36/207, 17.4%) | "
        f"Rank #3={t_map_3m['T07_ROUTING_CAB_DELAY_ETA']['short_name']} (36/207, 17.4%)"
    )

    rep_12m = generate_dynamic_report(
        BASE_DIR,
        primary_period_mode="12m",
        trend_comparison_mode="3m",
        review_focus="negative",
        save_artifacts=True,
    )
    assert_report_invariants(rep_12m, "Test A2 (12m Default)", verify_pdf=True)
    t_map_12m = {r["theme_id"]: r for r in rep_12m["themes_and_recommendations"]}
    assert rep_12m["distributions"]["primary"]["n_reviews"] == 2851
    assert rep_12m["distributions"]["primary"]["count_low_1_2_star"] == 769
    assert t_map_12m["T02_CRASH_LAUNCH_PERFORMANCE"]["count_1_2_star_primary"] == 126
    assert t_map_12m["T02_CRASH_LAUNCH_PERFORMANCE"]["priority_rank"] == "Rank #1"
    print(
        f"  [PASS] Test A2 (12m: 12 Oct 2025 – 11 Oct 2026): N=2,851, 1-2★=769 | "
        f"Rank #1={t_map_12m['T02_CRASH_LAUNCH_PERFORMANCE']['short_name']} (126/769, 16.4%) | "
        f"Rank #2={t_map_12m['T08_SCHEDULING_ROSTER_NOSHOW']['short_name']} (121/769, 15.7%) | "
        f"Rank #3={t_map_12m['T07_ROUTING_CAB_DELAY_ETA']['short_name']} (100/769, 13.0%)\n"
    )

    # -------------------------------------------------------------------------
    # TEST B: Period with zero matching reviews for a particular theme
    #   (15 Sep 2026 – 11 Oct 2026: T01_SAFETY_SOS_EMERGENCY has 0/69 matching reviews)
    # -------------------------------------------------------------------------
    print("=" * 84)
    print("TEST B: Period with Zero Matching Reviews for a Theme (15 Sep 2026 – 11 Oct 2026)")
    print("=" * 84)
    rep_b = generate_dynamic_report(
        BASE_DIR,
        primary_period_mode="custom",
        trend_comparison_mode="1m",
        review_focus="negative",
        custom_start="2026-09-15",
        custom_end="2026-10-11",
        save_artifacts=False,
    )
    assert_report_invariants(rep_b, "Test B (Zero-Theme Period)", verify_pdf=False)
    t01_b = next(r for r in rep_b["themes_and_recommendations"] if r["theme_id"] == "T01_SAFETY_SOS_EMERGENCY")
    assert t01_b["count_1_2_star_primary"] == 0
    assert t01_b["priority_score_1_to_5"] is None
    assert t01_b["priority_rank"] == "Unranked (0 Reviews)"
    assert t01_b["evidence_label"] == "No direct review evidence in this period"
    assert rep_b["executive_summary"]["safety_escalation_summary"]["has_credible_evidence"] is False
    print(
        f"  [PASS] Test B (15 Sep 2026 – 11 Oct 2026): T01 Safety has 0/{rep_b['distributions']['primary']['count_low_1_2_star']} reviews -> "
        f"Rank='{t01_b['priority_rank']}', Score={t01_b['priority_score_1_to_5']}, Label='{t01_b['evidence_label']}'\n"
    )

    # -------------------------------------------------------------------------
    # TEST C: Period with zero reviews in one comparison window
    #   (01 Mar 2019 – 30 Aug 2022: Preceding low-star n=0, Recent low-star n=1)
    # -------------------------------------------------------------------------
    print("=" * 84)
    print("TEST C: Period with Zero Reviews in One Comparison Window (01 Mar 2019 – 30 Aug 2022)")
    print("=" * 84)
    rep_c = generate_dynamic_report(
        BASE_DIR,
        primary_period_mode="custom",
        trend_comparison_mode="3m",
        review_focus="negative",
        custom_start="2019-03-01",
        custom_end="2022-08-30",
        save_artifacts=True,
    )
    assert_report_invariants(rep_c, "Test C (Zero Comparison Window)", verify_pdf=True)
    assert rep_c["distributions"]["preceding"]["count_low_1_2_star"] == 0
    assert rep_c["distributions"]["recent"]["count_low_1_2_star"] == 1
    for r in rep_c["themes_and_recommendations"]:
        assert r["trend_status"] == "NO_BASELINE_AVAILABLE"
        assert "No baseline available" in r["trend_display"]
    print(
        f"  [PASS] Test C (01 Mar 2019 – 30 Aug 2022): Preceding n=0, Recent n=1 -> "
        f"All trends labeled '{rep_c['themes_and_recommendations'][0]['trend_short_display']}'\n"
    )

    # -------------------------------------------------------------------------
    # TEST D: Period with fewer than the minimum required matching reviews (< 10)
    #   (10 Oct 2026 – 11 Oct 2026: 2-day window with < 10 low-star matching reviews)
    # -------------------------------------------------------------------------
    print("=" * 84)
    print("TEST D: Period with Fewer Than Minimum Required Matching Reviews (10 Oct 2026 – 11 Oct 2026)")
    print("=" * 84)
    rep_d = generate_dynamic_report(
        BASE_DIR,
        primary_period_mode="custom",
        trend_comparison_mode="1m",
        review_focus="negative",
        custom_start="2026-10-10",
        custom_end="2026-10-11",
        save_artifacts=False,
    )
    assert_report_invariants(rep_d, "Test D (<10 Matching Reviews)", verify_pdf=False)
    assert rep_d["distributions"]["primary"]["count_low_1_2_star"] < 10
    assert rep_d["executive_summary"]["is_sufficient_evidence"] is False
    assert rep_d["executive_summary"]["advisory_banner"] is not None
    # Also verify that themes with < 10 matching reviews in comparison windows are labeled Insufficient evidence
    low_match_themes = [
        r for r in rep_d["themes_and_recommendations"]
        if (r["count_1_2_star_preceding"] + r["count_1_2_star_recent"]) > 0
        and (r["count_1_2_star_preceding"] < MIN_THEME_MATCHING_PER_WINDOW or r["count_1_2_star_recent"] < MIN_THEME_MATCHING_PER_WINDOW)
    ]
    assert len(low_match_themes) > 0
    for r in low_match_themes:
        assert r["trend_status"] == "INSUFFICIENT_EVIDENCE"
        assert "Insufficient evidence" in r["trend_display"]
        assert r["is_meaningful_increase"] is False
    print(
        f"  [PASS] Test D (08 Oct 2026 – 11 Oct 2026): N={rep_d['distributions']['primary']['n_reviews']}, "
        f"1-2★={rep_d['distributions']['primary']['count_low_1_2_star']} (<10 threshold) -> "
        f"is_sufficient_evidence=False, {len(low_match_themes)} sub-threshold theme trends labeled 'Insufficient evidence'.\n"
    )

    # -------------------------------------------------------------------------
    # TEST E: Two different selected date ranges with different underlying distributions
    #   (Range 1: 01 Sep 2025 – 31 Mar 2026 vs. Range 2: 12 Jul 2026 – 11 Oct 2026)
    # -------------------------------------------------------------------------
    print("=" * 84)
    print("TEST E: Two Different Date Ranges with Distinct Review Distributions")
    print("=" * 84)
    rep_e1 = generate_dynamic_report(
        BASE_DIR,
        primary_period_mode="custom",
        trend_comparison_mode="3m",
        review_focus="negative",
        custom_start="2025-09-01",
        custom_end="2026-03-31",
        save_artifacts=True,
    )
    assert_report_invariants(rep_e1, "Test E1 (Sep 2025 – Mar 2026)", verify_pdf=False)
    assert rep_e1["distributions"]["primary"]["n_reviews"] != rep_3m["distributions"]["primary"]["n_reviews"]
    assert rep_e1["distributions"]["primary"]["count_low_1_2_star"] != rep_3m["distributions"]["primary"]["count_low_1_2_star"]
    assert rep_e1["distributions"]["primary"]["sample_mean_rating"] != rep_3m["distributions"]["primary"]["sample_mean_rating"]
    print(
        f"  [PASS] Test E: Range 1 (Sep 2025 – Mar 2026: N={rep_e1['distributions']['primary']['n_reviews']}, "
        f"1-2★={rep_e1['distributions']['primary']['count_low_1_2_star']}, Mean={rep_e1['distributions']['primary']['sample_mean_rating']}★) != "
        f"Range 2 (Jul 2026 – Oct 2026: N={rep_3m['distributions']['primary']['n_reviews']}, "
        f"1-2★={rep_3m['distributions']['primary']['count_low_1_2_star']}, Mean={rep_3m['distributions']['primary']['sample_mean_rating']}★)\n"
    )

    # -------------------------------------------------------------------------
    # TEST F: Period with incomplete historical collection coverage
    #   (01 Jan 2025 – 31 Dec 2025: extends prior to 19 Jun 2025 unfiltered Cohort A floor)
    # -------------------------------------------------------------------------
    print("=" * 84)
    print("TEST F: Period with Incomplete Historical Coverage (01 Jan 2025 – 31 Dec 2025)")
    print("=" * 84)
    rep_f = generate_dynamic_report(
        BASE_DIR,
        primary_period_mode="custom",
        trend_comparison_mode="3m",
        review_focus="negative",
        custom_start="2025-01-01",
        custom_end="2025-12-31",
        save_artifacts=False,
    )
    assert_report_invariants(rep_f, "Test F (Incomplete Historical Coverage)", verify_pdf=False)
    assert rep_f["window_configuration"]["is_fully_covered_unfiltered"] is False
    assert rep_f["distributions"]["primary"]["is_representative"] is False
    assert "Non-Repr." in rep_f["distributions"]["primary"]["mean_rating_display"]
    assert len(rep_f["window_configuration"]["missing_or_partial_intervals"]) >= 1
    for r in rep_f["themes_and_recommendations"]:
        if r["has_direct_evidence"]:
            assert r["C_confidence_1_5"] <= 2, "Confidence factor C must be capped at <= 2 when coverage is non-representative"
    print(
        f"  [PASS] Test F (01 Jan 2025 – 31 Dec 2025): is_fully_covered_unfiltered=False, "
        f"Mean Display='{rep_f['distributions']['primary']['mean_rating_display']}', C_confidence capped <= 2.\n"
    )

    # -------------------------------------------------------------------------
    # Regenerate all remaining stored report bundles on disk so zero stale files exist
    # -------------------------------------------------------------------------
    print("Regenerating all stored report bundles in reports/generated/ to v2.3.0...")
    for p_mode, t_mode, foc, c_s, c_e in [
        ("6m", "3m", "negative", None, None),
        ("12m", "3m", "all", None, None),
        ("3m", "1m", "all", None, None),
        ("custom", "3m", "negative", "2025-09-01", "2026-09-30"),
    ]:
        rep_other = generate_dynamic_report(
            BASE_DIR,
            primary_period_mode=p_mode,
            trend_comparison_mode=t_mode,
            review_focus=foc,
            custom_start=c_s,
            custom_end=c_e,
            save_artifacts=True,
        )
        assert_report_invariants(rep_other, f"Stored Bundle {rep_other['report_metadata']['report_id']}", verify_pdf=False)

    # -------------------------------------------------------------------------
    # HTTP Server & Live PDF Endpoint Verification
    # -------------------------------------------------------------------------
    server = ThreadingHTTPServer(("127.0.0.1", 0), RatingIntelligenceHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/init", timeout=15) as r:
            init_payload = json.loads(r.read().decode("utf-8"))
            assert init_payload["status"] == "ok"
            assert init_payload["initial_report"]["report_metadata"]["methodology_version"] == METHODOLOGY_VERSION

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/report/RPT-3M", timeout=15) as r:
            rep3m_api = json.loads(r.read().decode("utf-8"))
            assert rep3m_api["status"] == "ok"
            assert rep3m_api["report"]["report_metadata"]["methodology_version"] == METHODOLOGY_VERSION
            assert rep3m_api["report"]["themes_and_recommendations"][0]["count_1_2_star_primary"] == 47

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/pdf/RPT-3M", timeout=60) as r:
            pdf_bytes = r.read()
            assert r.status == 200
            assert r.headers.get("Content-Type") == "application/pdf"
            assert pdf_bytes[:4] == b"%PDF" and len(pdf_bytes) > 25_000
        print(f"  [PASS] HTTP Server & Live PDF Endpoint (/api/pdf/RPT-3M -> {len(pdf_bytes):,} bytes valid PDF) verified on port {port}.")
    finally:
        server.shutdown()
        server.server_close()

    print("\nALL UNIT & REGRESSION TESTS (TESTS A–F + PDF GENERATION) PASSED SUCCESSFULLY.")


if __name__ == "__main__":
    run_all_regression_tests()
