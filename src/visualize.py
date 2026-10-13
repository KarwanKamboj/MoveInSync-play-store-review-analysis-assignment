"""
Step 4: Publication-Quality Matplotlib Visualizations
Generates 5 high-resolution (300 DPI) charts in reports/figures/ with explicit
sample sizes (n / N), cohort names, and date windows printed directly on every chart.
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.sans-serif"] = "DejaVu Sans"
plt.rcParams["axes.edgecolor"] = "#CCCCCC"
plt.rcParams["axes.linewidth"] = 0.8


def generate_all_charts(base_dir: Path) -> None:
    proc_dir = base_dir / "data" / "processed"
    fig_dir = base_dir / "reports" / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    window_df = pd.read_csv(proc_dir / "window_rating_distributions.csv")
    monthly_df = pd.read_csv(proc_dir / "monthly_trend_2025_09_to_2026_09.csv")
    theme_df = pd.read_csv(proc_dir / "theme_prioritization_scorecard.csv")
    with open(proc_dir / "analysis_summary.json", "r", encoding="utf-8") as f:
        summary = json.load(f)

    # -------------------------------------------------------------------------
    # Chart 1: Rating Distribution & Metric Disambiguation (All-Time vs Windows)
    # -------------------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.8), dpi=300)

    hist_counts = summary["app_metadata"]["ds5_histogram_1_to_5"]
    hist_sum = sum(hist_counts)
    hist_pcts = [c / hist_sum * 100.0 for c in hist_counts]

    prim_row = window_df[window_df["cohort_label"] == "Primary Window (All Collected)"].iloc[0]
    prim_pcts = [prim_row[f"pct_{s}_star"] for s in (1, 2, 3, 4, 5)]

    x = np.arange(5)
    w = 0.36
    b1 = axes[0].bar(
        x - w / 2,
        hist_pcts,
        width=w,
        color="#2563EB",
        label=f"All-Time Play Store Histogram\n(N={hist_sum:,} bucket sum | {summary['app_metadata']['ds5_reported_ratings_total']:,} total | 4.64★)",
    )
    b2 = axes[0].bar(
        x + w / 2,
        prim_pcts,
        width=w,
        color="#DC2626",
        label=f"Primary Window Written Reviews\n(2025-09-01..2026-09-30 | n={int(prim_row['n_reviews']):,} | Mean={prim_row['sample_mean_rating']:.2f}★)",
    )
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(["1 Star", "2 Stars", "3 Stars", "4 Stars", "5 Stars"], fontsize=10, fontweight="bold")
    axes[0].set_ylabel("Percentage of Ratings / Written Reviews (%)", fontsize=10)
    axes[0].set_title("A. Store Rating Histogram vs. Written Review Sample", fontsize=11, fontweight="bold", pad=10)
    axes[0].set_ylim(0, 100)
    axes[0].grid(axis="y", linestyle="--", alpha=0.4)
    axes[0].legend(loc="upper left", fontsize=8.5, frameon=True)

    for bar in b1:
        h = bar.get_height()
        axes[0].annotate(f"{h:.1f}%", (bar.get_x() + bar.get_width() / 2, h + 1.2), ha="center", fontsize=8, color="#1E40AF")
    for bar in b2:
        h = bar.get_height()
        axes[0].annotate(f"{h:.1f}%", (bar.get_x() + bar.get_width() / 2, h + 1.2), ha="center", fontsize=8, color="#991B1B")

    rec_row = window_df[window_df["cohort_label"].str.startswith("Most Recent 90 Days")].iloc[0]
    pri_row = window_df[window_df["cohort_label"].str.startswith("Preceding 90 Days")].iloc[0]
    rec_pcts = [rec_row[f"pct_{s}_star"] for s in (1, 2, 3, 4, 5)]
    pri_pcts = [pri_row[f"pct_{s}_star"] for s in (1, 2, 3, 4, 5)]

    b3 = axes[1].bar(
        x - w / 2,
        pri_pcts,
        width=w,
        color="#64748B",
        label=f"Preceding 90 Days (2026-04-04..2026-07-02)\n(n={int(pri_row['n_reviews']):,} written reviews | Mean={pri_row['sample_mean_rating']:.2f}★)",
    )
    b4 = axes[1].bar(
        x + w / 2,
        rec_pcts,
        width=w,
        color="#EA580C",
        label=f"Most Recent 90 Days (2026-07-03..2026-09-30)\n(n={int(rec_row['n_reviews']):,} written reviews | Mean={rec_row['sample_mean_rating']:.2f}★)",
    )
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(["1 Star", "2 Stars", "3 Stars", "4 Stars", "5 Stars"], fontsize=10, fontweight="bold")
    axes[1].set_ylabel("Percentage of Written Reviews (%)", fontsize=10)
    axes[1].set_title("B. Written Review Distribution: Prior 90d vs. Recent 90d", fontsize=11, fontweight="bold", pad=10)
    axes[1].set_ylim(0, 85)
    axes[1].grid(axis="y", linestyle="--", alpha=0.4)
    axes[1].legend(loc="upper left", fontsize=8.5, frameon=True)

    for bar in b3:
        h = bar.get_height()
        axes[1].annotate(f"{h:.1f}%", (bar.get_x() + bar.get_width() / 2, h + 1.0), ha="center", fontsize=8, color="#334155")
    for bar in b4:
        h = bar.get_height()
        axes[1].annotate(f"{h:.1f}%", (bar.get_x() + bar.get_width() / 2, h + 1.0), ha="center", fontsize=8, color="#9A3412")

    fig.suptitle(
        "MoveInSync (com.moveinsync.ets) — Metric Disambiguation & 90-Day Star Distribution Shift",
        fontsize=13,
        fontweight="bold",
        y=0.98,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(fig_dir / "01_rating_distribution_comparison.png", dpi=300)
    plt.close(fig)

    # -------------------------------------------------------------------------
    # Chart 2: Monthly Trend inside Primary Window (Sept 2025 - Sept 2026)
    # -------------------------------------------------------------------------
    fig, ax1 = plt.subplots(figsize=(12.5, 5.5), dpi=300)
    months = monthly_df["year_month"].tolist()
    x_m = np.arange(len(months))

    ax1.bar(x_m - 0.18, monthly_df["count_5_star"], width=0.35, color="#10B981", alpha=0.85, label="5★ Written Reviews (Count)")
    ax1.bar(x_m + 0.18, monthly_df["count_1_2_star"], width=0.35, color="#EF4444", alpha=0.85, label="1–2★ Low-Rating Reviews (Count)")

    ax1.set_xticks(x_m)
    ax1.set_xticklabels(months, rotation=30, ha="right", fontsize=9.5, fontweight="bold")
    ax1.set_ylabel("Monthly Written Review Count", fontsize=10, fontweight="bold")
    ax1.grid(axis="y", linestyle="--", alpha=0.35)

    ax2 = ax1.twinx()
    ax2.plot(
        x_m,
        monthly_df["pct_1_2_star"],
        color="#991B1B",
        marker="o",
        linewidth=2.4,
        label="1–2★ Share of Monthly Written Reviews (%)",
    )
    ax2.set_ylabel("1–2★ Share of Monthly Reviews (%)", fontsize=10, fontweight="bold", color="#991B1B")
    ax2.set_ylim(0, max(monthly_df["pct_1_2_star"]) * 1.35)

    for idx, val in enumerate(monthly_df["pct_1_2_star"]):
        ax2.annotate(f"{val:.1f}%", (x_m[idx], val + 1.8), ha="center", fontsize=8.5, fontweight="bold", color="#7F1D1D")

    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=9, frameon=True)

    fig.suptitle(
        f"Monthly Written-Review Volume & 1–2★ Complaint Rate (Primary Window: 2025-09-01 to 2026-09-30 | N = {int(prim_row['n_reviews']):,})\n"
        "Cohort: Complete Chronological Dataset (Older pre-Sept 2025 reviews strictly excluded)",
        fontsize=11.5,
        fontweight="bold",
        y=0.97,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.91])
    fig.savefig(fig_dir / "02_monthly_rating_and_complaint_trend.png", dpi=300)
    plt.close(fig)

    # -------------------------------------------------------------------------
    # Chart 3: Complaint Theme Frequency in Primary Window (Sept 2025 - Sept 2026)
    # -------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(13.2, 6.8), dpi=300)
    t_sorted = theme_df.sort_values("count_1_2_star_primary", ascending=True).reset_index(drop=True)
    y_pos = np.arange(len(t_sorted))
    colors = ["#7C3AED" if tr == "P0_SAFETY_OVERRIDE" else "#2563EB" for tr in t_sorted["track"]]

    ax.barh(y_pos, t_sorted["pct_of_1_2_star_primary"], color=colors, height=0.65, alpha=0.9)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(
        [f"{r['theme_name']}\n({r['theme_id'].split('_')[0]})" for _, r in t_sorted.iterrows()],
        fontsize=9,
        fontweight="bold",
    )
    ax.set_xlabel("Share of Low-Star (1–2★) Written Reviews in Primary Window (%)", fontsize=10, fontweight="bold")
    ax.set_xlim(0, max(t_sorted["pct_of_1_2_star_primary"]) * 1.32)
    ax.grid(axis="x", linestyle="--", alpha=0.4)

    for idx, (_, r) in enumerate(t_sorted.iterrows()):
        tag = " [P0 SAFETY OVERRIDE]" if r["track"] == "P0_SAFETY_OVERRIDE" else ""
        ax.annotate(
            f" {r['pct_of_1_2_star_primary']:.1f}%  (n = {int(r['count_1_2_star_primary'])} / {int(r['denominator_1_2_star_primary'])}{tag})",
            (r["pct_of_1_2_star_primary"], y_pos[idx]),
            va="center",
            ha="left",
            fontsize=8.5,
            fontweight="bold",
            color="#4C1D95" if r["track"] == "P0_SAFETY_OVERRIDE" else "#1E3A8A",
        )

    fig.suptitle(
        "What Are Users Complaining About Now? — Top Functional Themes in 1–2★ Reviews\n"
        f"(Primary Window: 2025-09-01 to 2026-09-30 | Low-Star Sample N = {summary['primary_window_low_1_2_star_reviews']} | "
        f"Multi-Label; {summary['primary_window_generic_uninformative_pct']:.1f}% Generic/Short Unmatched)",
        fontsize=11.5,
        fontweight="bold",
        y=0.97,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.91])
    fig.savefig(fig_dir / "03_complaint_themes_primary_window.png", dpi=300)
    plt.close(fig)

    # -------------------------------------------------------------------------
    # Chart 4: Which Problems Are Increasing? (Recent 90d vs Preceding 90d Delta)
    # -------------------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(15.5, 6.6), dpi=300, sharey=True)
    t_delta = theme_df.sort_values("delta_90d_pp", ascending=True).reset_index(drop=True)
    y_d = np.arange(len(t_delta))

    h_bar = 0.36
    axes[0].barh(
        y_d - h_bar / 2,
        t_delta["rate_1_2_star_prior_90d_pct"],
        height=h_bar,
        color="#64748B",
        label=f"Preceding 90d (2026-04-04..07-02 | n_1-2★ = {summary['prior_90d_low_1_2_star_reviews']})",
    )
    axes[0].barh(
        y_d + h_bar / 2,
        t_delta["rate_1_2_star_recent_90d_pct"],
        height=h_bar,
        color="#EA580C",
        label=f"Most Recent 90d (2026-07-03..09-30 | n_1-2★ = {summary['recent_90d_low_1_2_star_reviews']})",
    )
    axes[0].set_yticks(y_d)
    axes[0].set_yticklabels(
        [f"{r['theme_name']} ({r['theme_id'].split('_')[0]})" for _, r in t_delta.iterrows()],
        fontsize=9,
        fontweight="bold",
    )
    axes[0].set_xlabel("Share of 1–2★ Reviews in Window (%)", fontsize=10, fontweight="bold")
    axes[0].set_title("A. Theme Share: Prior 90d vs. Recent 90d", fontsize=11, fontweight="bold", pad=8)
    axes[0].grid(axis="x", linestyle="--", alpha=0.4)
    axes[0].legend(loc="lower right", fontsize=8.5, frameon=True)

    delta_colors = ["#DC2626" if d > 0 else "#16A34A" for d in t_delta["delta_90d_pp"]]
    axes[1].barh(y_d, t_delta["delta_90d_pp"], color=delta_colors, height=0.58, alpha=0.9)
    axes[1].axvline(0, color="#1E293B", linewidth=1.1)
    axes[1].set_xlabel("Change in Share of 1–2★ Reviews (Percentage Points, Δ pp)", fontsize=10, fontweight="bold")
    axes[1].set_title("B. 90-Day Shift (Δ pp & Count Change)", fontsize=11, fontweight="bold", pad=8)
    axes[1].grid(axis="x", linestyle="--", alpha=0.4)
    min_d = min(t_delta["delta_90d_pp"])
    max_d = max(t_delta["delta_90d_pp"])
    axes[1].set_xlim(min_d - 6.8, max_d + 8.0)

    for idx, (_, r) in enumerate(t_delta.iterrows()):
        d_val = r["delta_90d_pp"]
        sign = "+" if d_val > 0 else ""
        label_txt = f" {sign}{d_val:.1f} pp ({int(r['count_1_2_star_prior_90d'])}→{int(r['count_1_2_star_recent_90d'])}) "
        offset = 0.2 if d_val >= 0 else -0.2
        align = "left" if d_val >= 0 else "right"
        axes[1].annotate(
            label_txt,
            (d_val + offset, y_d[idx]),
            va="center",
            ha=align,
            fontsize=8.5,
            fontweight="bold",
            color="#991B1B" if d_val > 0 else "#166534",
        )

    fig.suptitle(
        "Which Problems Are Increasing? — Most Recent 90 Days (Jul–Sept 2026) vs. Preceding 90 Days (Apr–Jul 2026)",
        fontsize=12.5,
        fontweight="bold",
        y=0.98,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(fig_dir / "04_recent_90d_vs_prior_90d_deltas.png", dpi=300)
    plt.close(fig)

    # -------------------------------------------------------------------------
    # Chart 5: Normalized 1-5 Prioritization Matrix (What to Fix First)
    # -------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(12.5, 7.2), dpi=300)

    urgency_scores = (
        0.25 * theme_df["F_frequency_1_5"]
        + 0.25 * theme_df["S_severity_1_5"]
        + 0.20 * theme_df["T_trend_1_5"]
        + 0.15 * theme_df["V_evidence_1_5"]
    ) / 0.85

    ease_scores = theme_df["E_ease_1_5_provisional"].astype(float).copy()
    sizes = np.clip(theme_df["count_1_2_star_primary"] * 4.5, 110, 900)
    p_colors = [
        "#7C3AED" if tr == "P0_SAFETY_OVERRIDE" else "#DC2626" if sc >= 3.6 else "#2563EB"
        for tr, sc in zip(theme_df["track"], theme_df["priority_score_1_to_5"])
    ]

    # Custom non-overlapping offsets per theme_id
    label_offsets = {
        "T02_CRASH_LAUNCH_PERFORMANCE": (14, -4, "left"),
        "T08_SCHEDULING_ROSTER_NOSHOW": (14, -8, "left"),
        "T07_ROUTING_CAB_DELAY_ETA": (14, -6, "left"),
        "T04_FORCED_PROMPTS_RATINGS_PERMISSIONS": (-14, 26, "right"),
        "T03_PLAYSTORE_INTEGRITY_BLOCK": (-18, 36, "right"),
        "T05_AUTH_LOGIN_OTP_SESSION": (14, -2, "left"),
        "T09_UI_UX_USABILITY": (14, -26, "left"),
        "T06_LIVE_TRACKING_GPS_MAP": (-14, 26, "right"),
        "T10_DRIVER_VENDOR_HELPDESK": (14, -20, "left"),
        "T01_SAFETY_SOS_EMERGENCY": (14, -12, "left"),
    }

    ax.scatter(
        ease_scores,
        urgency_scores,
        s=sizes,
        c=p_colors,
        alpha=0.84,
        edgecolors="#1E293B",
        linewidth=1.3,
        zorder=4,
    )

    for idx, (_, r) in enumerate(theme_df.iterrows()):
        tid = r["theme_id"]
        ux = ease_scores.iloc[idx]
        uy = urgency_scores.iloc[idx]
        short_id = tid.split("_")[0]
        dx, dy, ha_align = label_offsets.get(tid, (10, 5, "left"))
        rank_lbl = "P0 SAFETY" if r["track"] == "P0_SAFETY_OVERRIDE" else f"Score={r['priority_score_1_to_5']:.2f}"
        ax.annotate(
            f"{short_id}: {r['theme_name'][:36]}\n({rank_lbl} | n={int(r['count_1_2_star_primary'])} | Δ90d={r['delta_90d_pp']:+.1f}pp)",
            (ux, uy),
            xytext=(dx, dy),
            textcoords="offset points",
            ha=ha_align,
            va="center",
            fontsize=8,
            fontweight="bold",
            arrowprops=dict(arrowstyle="-", color="#64748B", lw=0.8),
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#CBD5E1", alpha=0.92),
            zorder=5,
        )

    ax.axvline(3.0, color="#64748B", linestyle="--", linewidth=1.0)
    ax.axhline(3.5, color="#64748B", linestyle="--", linewidth=1.0)
    ax.set_xlim(1.3, 5.45)
    ax.set_ylim(2.4, 5.1)
    ax.set_xlabel("Provisional Implementation Ease (E_ease: 1 = Very Hard → 5 = Very Easy) [PROVISIONAL]", fontsize=10, fontweight="bold")
    ax.set_ylabel("Normalized Problem Urgency & Impact (F, S, T, V Composite: 1 → 5)", fontsize=10, fontweight="bold")

    fig.suptitle(
        "What Should MoveInSync Fix First? — Normalized 1–5 Prioritization Matrix\n"
        "(Primary Window: Sept 2025 – Sept 2026 | Bubble Size = 1–2★ Review Count | Purple = P0 Safety Override)",
        fontsize=11.5,
        fontweight="bold",
        y=0.97,
    )
    ax.grid(True, linestyle=":", alpha=0.45)
    plt.tight_layout(rect=[0, 0, 1, 0.91])
    fig.savefig(fig_dir / "05_prioritization_matrix.png", dpi=300)
    plt.close(fig)

    print("=== Regenerated all 5 high-resolution Matplotlib charts in reports/figures/ ===")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    generate_all_charts(project_root)
