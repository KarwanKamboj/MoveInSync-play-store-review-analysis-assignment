"""
Step 3: Windowed Trend Analysis, 90-Day Comparison, & Normalized 1-5 Prioritization
- Strictly isolates Primary Window (2025-09-01 to 2026-09-30) from historical reviews.
- Compares Most Recent 90 Days (2026-07-03..2026-09-30) vs Preceding 90 Days (2026-04-04..2026-07-02)
  on both star rating distributions and theme complaint rates.
- Computes normalized 1-5 scores for Frequency (F), Severity (S), Trend (T),
  Evidence Strength (V), and Implementation Ease (E_ease), routing safety-critical
  issues to Track 1 (P0_SAFETY_OVERRIDE).
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from src.preprocess_and_classify import THEME_DEFINITIONS


def score_frequency_1_to_5(pct_of_low_star: float) -> int:
    """Normalizes theme share of 1-2* reviews in Sept 2025-Sept 2026 to 1..5."""
    if pct_of_low_star >= 15.0:
        return 5
    if pct_of_low_star >= 10.0:
        return 4
    if pct_of_low_star >= 5.0:
        return 3
    if pct_of_low_star >= 2.0:
        return 2
    return 1


def score_trend_1_to_5(delta_pp: float, rel_change_pct: float, recent_count: int) -> int:
    """
    Normalizes Recent 90d vs Prior 90d complaint rate shift to 1..5:
    5 = Spiking (> +3.0 pp or (>= +1.5 pp and >= +50% relative surge with n>=5))
    4 = Moderately Increasing (+1.0 pp to +3.0 pp)
    3 = Stable (-1.0 pp to +1.0 pp)
    2 = Slightly Declining (-3.0 pp to -1.0 pp)
    1 = Strongly Declining (< -3.0 pp)
    """
    if delta_pp > 3.0 or (delta_pp >= 1.5 and rel_change_pct >= 50.0 and recent_count >= 5):
        return 5
    if delta_pp >= 1.0:
        return 4
    if delta_pp > -1.0:
        return 3
    if delta_pp >= -3.0:
        return 2
    return 1


def score_evidence_strength_1_to_5(count_primary: int, total_thumbs_up: int, avg_words: float) -> int:
    """
    Normalizes Evidence Strength (V) to 1..5 based on volume of specific reports,
    peer agreement (thumbsUpCount), and detail (average word count).
    """
    pts = 0.0
    if count_primary >= 80:
        pts += 2.0
    elif count_primary >= 30:
        pts += 1.5
    elif count_primary >= 15:
        pts += 1.0
    else:
        pts += 0.5

    if total_thumbs_up >= 40:
        pts += 2.0
    elif total_thumbs_up >= 15:
        pts += 1.5
    elif total_thumbs_up >= 5:
        pts += 1.0
    else:
        pts += 0.5

    if avg_words >= 28:
        pts += 1.0
    elif avg_words >= 18:
        pts += 0.5

    return int(np.clip(round(pts), 1, 5))


def run_analysis_and_prioritization(base_dir: Path) -> Dict[str, Any]:
    """Executes all windowed analyses and outputs CSV scorecards and JSON summaries."""
    proc_dir = base_dir / "data" / "processed"
    raw_dir = base_dir / "data" / "raw"

    df = pd.read_csv(proc_dir / "reviews_master_classified.csv")
    df["at_dt"] = pd.to_datetime(df["at_dt"])

    with open(raw_dir / "app_metadata_latest.json", "r", encoding="utf-8") as f:
        app_meta = json.load(f)

    # 1. Partition strictly by temporal window
    df_primary = df[df["window_bucket"] == "primary_2025_09_to_2026_09"].copy()
    df_recent_90d = df_primary[df_primary["subwindow_90d"] == "recent_90d_2026_07_03_to_2026_09_30"].copy()
    df_prior_90d = df_primary[df_primary["subwindow_90d"] == "prior_90d_2026_04_04_to_2026_07_02"].copy()
    df_oct_2026 = df[df["window_bucket"] == "post_window_oct_2026"].copy()
    df_hist = df[df["window_bucket"] == "historical_pre_2025_09"].copy()

    # Low-star (1-2*) and 3* subsets inside Primary Window, Recent 90d, Prior 90d, and Historical
    low_primary = df_primary[df_primary["score"].isin([1, 2])].copy()
    low_recent_90d = df_recent_90d[df_recent_90d["score"].isin([1, 2])].copy()
    low_prior_90d = df_prior_90d[df_prior_90d["score"].isin([1, 2])].copy()
    low_hist = df_hist[df_hist["score"].isin([1, 2])].copy()

    # 2. Star Rating Distribution Comparison across Windows (Cohort A / Complete Primary Window)
    def star_dist_stats(sub: pd.DataFrame, label: str, window_str: str) -> Dict[str, Any]:
        n_total = len(sub)
        counts = sub["score"].value_counts().to_dict()
        c1, c2, c3, c4, c5 = [int(counts.get(s, 0)) for s in (1, 2, 3, 4, 5)]
        low_12 = c1 + c2
        replies = int(sub["has_developer_reply"].sum()) if n_total > 0 else 0
        low_sub = sub[sub["score"].isin([1, 2])]
        low_replies = int(low_sub["has_developer_reply"].sum()) if len(low_sub) > 0 else 0
        return {
            "cohort_label": label,
            "date_window": window_str,
            "n_reviews": n_total,
            "sample_mean_rating": round(float(sub["score"].mean()), 4) if n_total > 0 else None,
            "count_1_star": c1,
            "count_2_star": c2,
            "count_3_star": c3,
            "count_4_star": c4,
            "count_5_star": c5,
            "pct_1_star": round(c1 / n_total * 100, 2) if n_total > 0 else 0.0,
            "pct_2_star": round(c2 / n_total * 100, 2) if n_total > 0 else 0.0,
            "pct_3_star": round(c3 / n_total * 100, 2) if n_total > 0 else 0.0,
            "pct_4_star": round(c4 / n_total * 100, 2) if n_total > 0 else 0.0,
            "pct_5_star": round(c5 / n_total * 100, 2) if n_total > 0 else 0.0,
            "count_low_1_2_star": low_12,
            "pct_low_1_2_star": round(low_12 / n_total * 100, 2) if n_total > 0 else 0.0,
            "dev_reply_count_all": replies,
            "dev_reply_rate_all_pct": round(replies / n_total * 100, 2) if n_total > 0 else 0.0,
            "dev_reply_count_1_2_star": low_replies,
            "dev_reply_rate_1_2_star_pct": round(low_replies / low_12 * 100, 2) if low_12 > 0 else 0.0,
        }

    window_dist_rows = [
        star_dist_stats(df_primary, "Primary Window (All Collected)", "2025-09-01 to 2026-09-30"),
        star_dist_stats(
            df_primary[df_primary["in_cohort_a_unfiltered"]],
            "Primary Window (Cohort A: Unfiltered Chronological en-IN)",
            "2025-09-01 to 2026-09-30",
        ),
        star_dist_stats(df_recent_90d, "Most Recent 90 Days (W_recent_90d)", "2026-07-03 to 2026-09-30"),
        star_dist_stats(df_prior_90d, "Preceding 90 Days (W_prior_90d)", "2026-04-04 to 2026-07-02"),
        star_dist_stats(df_oct_2026, "Supplemental Post-Window Buffer (Oct 2026)", "2026-10-01 to 2026-10-11"),
        star_dist_stats(df_hist, "Quarantined Historical Context (Pre-Sept 2025, Stratified)", "2016-10-04 to 2025-08-31"),
    ]
    window_dist_df = pd.DataFrame(window_dist_rows)
    window_dist_df.to_csv(proc_dir / "window_rating_distributions.csv", index=False)

    # 3. Monthly Time-Series inside Primary Window (2025-09 through 2026-09)
    monthly_rows = []
    for ym, grp in df_primary.groupby("year_month"):
        n_m = len(grp)
        c12 = int(grp["score"].isin([1, 2]).sum())
        c1 = int((grp["score"] == 1).sum())
        c5 = int((grp["score"] == 5).sum())
        monthly_rows.append(
            {
                "year_month": ym,
                "n_reviews": n_m,
                "mean_rating": round(float(grp["score"].mean()), 3),
                "count_1_star": c1,
                "count_1_2_star": c12,
                "count_5_star": c5,
                "pct_1_2_star": round(c12 / n_m * 100, 2),
                "pct_5_star": round(c5 / n_m * 100, 2),
            }
        )
    monthly_df = pd.DataFrame(monthly_rows).sort_values("year_month")
    monthly_df.to_csv(proc_dir / "monthly_trend_2025_09_to_2026_09.csv", index=False)

    # 4. Theme Analysis, 90-Day vs 90-Day Comparison, & Normalized Prioritization
    n_low_primary = len(low_primary)
    n_all_primary = len(df_primary)
    n_low_recent = len(low_recent_90d)
    n_all_recent = len(df_recent_90d)
    n_low_prior = len(low_prior_90d)
    n_all_prior = len(df_prior_90d)
    n_low_hist = len(low_hist)

    theme_rows: List[Dict[str, Any]] = []
    evidence_quotes: Dict[str, List[Dict[str, Any]]] = {}

    for tdef in THEME_DEFINITIONS:
        tid = tdef["theme_id"]

        # Counts in Primary Window (2025-09-01 to 2026-09-30)
        sub_low_p = low_primary[low_primary[tid]]
        cnt_low_p = len(sub_low_p)
        pct_low_p = (cnt_low_p / n_low_primary * 100.0) if n_low_primary > 0 else 0.0
        pct_all_p = (cnt_low_p / n_all_primary * 100.0) if n_all_primary > 0 else 0.0

        # Also count in 3-star reviews in Primary Window
        cnt_3star_p = int(df_primary[df_primary["score"] == 3][tid].sum())

        # Counts in Recent 90 Days vs Prior 90 Days (among 1-2* reviews and among all reviews)
        cnt_low_rec = int(low_recent_90d[tid].sum())
        cnt_low_pri = int(low_prior_90d[tid].sum())

        rate_low_rec = (cnt_low_rec / n_low_recent * 100.0) if n_low_recent > 0 else 0.0
        rate_low_pri = (cnt_low_pri / n_low_prior * 100.0) if n_low_prior > 0 else 0.0
        delta_low_pp = rate_low_rec - rate_low_pri
        rel_change_low_pct = (
            ((rate_low_rec - rate_low_pri) / rate_low_pri * 100.0)
            if rate_low_pri > 0
            else (100.0 if rate_low_rec > 0 else 0.0)
        )

        # Share of ALL reviews in Recent 90d vs Prior 90d
        rate_all_rec = (cnt_low_rec / n_all_recent * 100.0) if n_all_recent > 0 else 0.0
        rate_all_pri = (cnt_low_pri / n_all_prior * 100.0) if n_all_prior > 0 else 0.0
        delta_all_pp = rate_all_rec - rate_all_pri

        # Optional Historical Context (< 2025-09-01, strictly quarantined)
        cnt_low_hist = int(low_hist[tid].sum())
        rate_low_hist = (cnt_low_hist / n_low_hist * 100.0) if n_low_hist > 0 else 0.0

        # ThumbsUp and word length stats in Primary Window (1-2*)
        thumbs_sum = int(sub_low_p["thumbsUpCount"].sum()) if cnt_low_p > 0 else 0
        thumbs_mean = float(sub_low_p["thumbsUpCount"].mean()) if cnt_low_p > 0 else 0.0
        avg_words = float(sub_low_p["word_count"].mean()) if cnt_low_p > 0 else 0.0
        dev_replies = int(sub_low_p["has_developer_reply"].sum()) if cnt_low_p > 0 else 0

        # Normalized 1-5 Scores (computed strictly from Sept 2025 - Sept 2026 & 90d trend)
        F_score = score_frequency_1_to_5(pct_low_p)
        S_score = int(tdef["severity_score"])
        T_score = score_trend_1_to_5(delta_low_pp, rel_change_low_pct, cnt_low_rec)
        V_score = score_evidence_strength_1_to_5(cnt_low_p, thumbs_sum, avg_words)
        E_ease = int(tdef["ease_score"])

        priority_score = round(
            0.25 * F_score + 0.25 * S_score + 0.20 * T_score + 0.15 * V_score + 0.15 * E_ease,
            2,
        )

        theme_rows.append(
            {
                "theme_id": tid,
                "theme_name": tdef["theme_name"],
                "track": tdef["track"],
                "user_journey": tdef["user_journey"],
                "owner": tdef["owner"],
                # Primary Window (Sept 2025 - Sept 2026) counts & shares
                "count_1_2_star_primary": cnt_low_p,
                "denominator_1_2_star_primary": n_low_primary,
                "pct_of_1_2_star_primary": round(pct_low_p, 2),
                "pct_of_all_reviews_primary": round(pct_all_p, 2),
                "count_3_star_primary": cnt_3star_p,
                # 90-Day Comparison (Recent 90d: 2026-07-03..09-30 vs Prior 90d: 2026-04-04..07-02)
                "count_1_2_star_recent_90d": cnt_low_rec,
                "denom_1_2_star_recent_90d": n_low_recent,
                "rate_1_2_star_recent_90d_pct": round(rate_low_rec, 2),
                "count_1_2_star_prior_90d": cnt_low_pri,
                "denom_1_2_star_prior_90d": n_low_prior,
                "rate_1_2_star_prior_90d_pct": round(rate_low_pri, 2),
                "delta_90d_pp": round(delta_low_pp, 2),
                "rel_change_90d_pct": round(rel_change_low_pct, 1),
                "rate_all_recent_90d_pct": round(rate_all_rec, 2),
                "rate_all_prior_90d_pct": round(rate_all_pri, 2),
                "delta_all_90d_pp": round(delta_all_pp, 2),
                # Quarantined Historical Context (< Sept 2025)
                "historical_pre_2025_09_count": cnt_low_hist,
                "historical_pre_2025_09_rate_pct": round(rate_low_hist, 2),
                # Evidence metrics in Primary Window
                "thumbs_up_sum_primary": thumbs_sum,
                "thumbs_up_mean_primary": round(thumbs_mean, 2),
                "avg_word_count_primary": round(avg_words, 1),
                "dev_replies_primary": dev_replies,
                # Normalized 1-5 Prioritization Factors
                "F_frequency_1_5": F_score,
                "S_severity_1_5": S_score,
                "T_trend_1_5": T_score,
                "V_evidence_1_5": V_score,
                "E_ease_1_5_provisional": E_ease,
                "priority_score_1_to_5": priority_score,
                "ease_rationale": tdef["ease_rationale"],
                "symptom_summary": tdef["symptom_summary"],
                "root_cause_hypothesis": tdef["root_cause_hypothesis"],
                "telemetry_check": tdef["telemetry_check"],
            }
        )

        # Select top representative verbatim quotes from Primary Window (Sept 2025 - Sept 2026)
        # Sort by combination of recency and thumbsUpCount
        sub_sorted = sub_low_p.sort_values(["thumbsUpCount", "at_dt"], ascending=[False, False])
        top_recent = sub_low_p.sort_values("at_dt", ascending=False).head(3)
        combined_quotes = pd.concat([sub_sorted.head(3), top_recent]).drop_duplicates(subset=["reviewId"]).head(5)
        evidence_quotes[tid] = [
            {
                "reviewId": str(r["reviewId"]),
                "date": str(r["at"])[:10],
                "score": int(r["score"]),
                "version": str(r["version_raw"]),
                "thumbsUpCount": int(r["thumbsUpCount"]),
                "content": str(r["content_clean"]),
            }
            for _, r in combined_quotes.iterrows()
        ]

    theme_df = pd.DataFrame(theme_rows)
    # Sort Track 1 (P0_SAFETY_OVERRIDE) first, then Track 2 by priority_score_1_to_5 descending
    theme_df["is_p0_safety"] = theme_df["track"] == "P0_SAFETY_OVERRIDE"
    theme_df = theme_df.sort_values(
        ["is_p0_safety", "priority_score_1_to_5", "count_1_2_star_primary"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    theme_df["priority_rank"] = [
        "P0 (Safety Override)" if r["is_p0_safety"] else f"Rank #{idx}"
        for idx, (_, r) in enumerate(theme_df.iterrows(), start=1)
    ]

    theme_df.to_csv(proc_dir / "theme_prioritization_scorecard.csv", index=False)
    with open(proc_dir / "theme_evidence_quotes.json", "w", encoding="utf-8") as f:
        json.dump(evidence_quotes, f, indent=2, ensure_ascii=False)

    # 5. Version-Correlated Anomaly Table within Primary Window (Sept 2025 - Sept 2026)
    ver_rows = []
    for ver_fam, grp in df_primary.groupby("version_family"):
        n_v = len(grp)
        if n_v < 20:
            continue
        low_v = grp[grp["score"].isin([1, 2])]
        n_low_v = len(low_v)
        ver_rows.append(
            {
                "version_family": ver_fam,
                "n_reviews_primary": n_v,
                "min_date": str(grp["at_dt"].min())[:10],
                "max_date": str(grp["at_dt"].max())[:10],
                "sample_mean_rating": round(float(grp["score"].mean()), 3),
                "count_1_2_star": n_low_v,
                "pct_1_2_star": round(n_low_v / n_v * 100.0, 2),
                "crash_launch_count": int(low_v["T02_CRASH_LAUNCH_PERFORMANCE"].sum()),
                "crash_launch_pct_of_ver": round(int(low_v["T02_CRASH_LAUNCH_PERFORMANCE"].sum()) / n_v * 100.0, 2),
                "playstore_block_count": int(low_v["T03_PLAYSTORE_INTEGRITY_BLOCK"].sum()),
                "forced_prompts_count": int(low_v["T04_FORCED_PROMPTS_RATINGS_PERMISSIONS"].sum()),
                "tracking_gps_count": int(low_v["T06_LIVE_TRACKING_GPS_MAP"].sum()),
                "routing_delay_count": int(low_v["T07_ROUTING_CAB_DELAY_ETA"].sum()),
                "scheduling_noshow_count": int(low_v["T08_SCHEDULING_ROSTER_NOSHOW"].sum()),
            }
        )
    ver_df = pd.DataFrame(ver_rows).sort_values("min_date", ascending=False)
    ver_df.to_csv(proc_dir / "version_correlated_anomalies_primary.csv", index=False)

    # 6. Summary JSON for report verification
    unmatched_low_p = int(low_primary["is_generic_uninformative"].sum())
    summary = {
        "app_metadata": app_meta["raw_html_audit_india_locale"],
        "primary_window_total_reviews": n_all_primary,
        "primary_window_low_1_2_star_reviews": n_low_primary,
        "primary_window_matched_specific_theme_count": int(n_low_primary - unmatched_low_p),
        "primary_window_matched_specific_theme_pct": round((n_low_primary - unmatched_low_p) / n_low_primary * 100.0, 2),
        "primary_window_generic_uninformative_count": unmatched_low_p,
        "primary_window_generic_uninformative_pct": round(unmatched_low_p / n_low_primary * 100.0, 2),
        "recent_90d_total_reviews": n_all_recent,
        "recent_90d_low_1_2_star_reviews": n_low_recent,
        "prior_90d_total_reviews": n_all_prior,
        "prior_90d_low_1_2_star_reviews": n_low_prior,
    }
    with open(proc_dir / "analysis_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("=== Analysis & Prioritization Complete ===")
    print(theme_df[["priority_rank", "theme_id", "count_1_2_star_primary", "pct_of_1_2_star_primary", "delta_90d_pp", "F_frequency_1_5", "S_severity_1_5", "T_trend_1_5", "V_evidence_1_5", "E_ease_1_5_provisional", "priority_score_1_to_5"]].to_string(index=False))
    return summary


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    run_analysis_and_prioritization(project_root)
