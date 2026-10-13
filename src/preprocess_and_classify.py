"""
Step 2: Preprocessing, Deduplication, Strict Temporal Windowing, & Complaint Classification
- Deduplicates raw reviews strictly by reviewId while preserving cohort provenance.
- Enforces primary analysis window (2025-09-01 to 2026-09-30), Recent 90-Day window
  (2026-07-03 to 2026-09-30), Preceding 90-Day window (2026-04-04 to 2026-07-02),
  and quarantines older reviews (< 2025-09-01) and post-window October 2026 reviews.
- Applies a transparent, auditable multi-label domain taxonomy for MoveInSync complaints.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

PRIMARY_START = pd.Timestamp("2025-09-01 00:00:00")
PRIMARY_END = pd.Timestamp("2026-09-30 23:59:59")
RECENT_90D_START = pd.Timestamp("2026-07-03 00:00:00")
RECENT_90D_END = pd.Timestamp("2026-09-30 23:59:59")
PRIOR_90D_START = pd.Timestamp("2026-04-04 00:00:00")
PRIOR_90D_END = pd.Timestamp("2026-07-02 23:59:59")

# Transparent, auditable domain taxonomy for MoveInSync employee app (com.moveinsync.ets)
THEME_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "theme_id": "T01_SAFETY_SOS_EMERGENCY",
        "theme_name": "Safety, SOS Alarm & Night-Shift Security",
        "track": "P0_SAFETY_OVERRIDE",
        "user_journey": "In-Trip Safety, SOS Emergency & Night-Shift Logout",
        "severity_score": 5,
        "ease_score": 3,
        "ease_rationale": "Moderate (3/5): Client UI changes (non-blocking SOS access, trip-cancel confirmation dialog) are fast; operational helpline/escort SLA enforcement requires ops coordination [PROVISIONAL].",
        "owner": "Safety & Security Product + Mobile Engineering + Fleet Operations",
        "pattern": (
            r"\b(?:sos|panic|emergency|unsafe|safety|rash\s*driv\w*|drunk\w*|speeding|"
            r"harass\w*|guard\w*|escort\w*|helpline|sahayta|accident\w*|"
            r"(?:women'?s?|female|night|lady|ladies)\s+(?:safety|security|escort|guard)|"
            r"security\s+(?:guard\w*|escort\w*|issue\w*|concern\w*)|"
            r"female\s+employees?\s+at\s+logout|going\s+alone\s+at\s+night)\b"
        ),
        "symptom_summary": (
            "SOS button blocked by modal popups, unreachable emergency helplines (Sahayta), "
            "unconfirmed night-shift no-show cancellations, and rash driving reports."
        ),
        "root_cause_hypothesis": (
            "Full-screen modal overlays rendered above the SOS action bar; session token expiry during active trips; "
            "operational gaps in night-shift escort and helpline staffing."
        ),
        "telemetry_check": (
            "Audit SOS tap-to-dispatch success rate, active-trip modal z-index hierarchy, "
            "Sahayta helpline call drop/wait times, and night-shift no-show call logs."
        ),
    },
    {
        "theme_id": "T02_CRASH_LAUNCH_PERFORMANCE",
        "theme_name": "App Crashes, Launch Freezes & Post-Update Failures",
        "track": "TRACK_2_WEIGHTED",
        "user_journey": "App Update, Cold Launch & Core Runtime Stability",
        "severity_score": 5,
        "ease_score": 3,
        "ease_rationale": "Moderate (3/5): Standard Android crash-trace debugging and defensive local storage/cache migration handling within 1-2 sprints [PROVISIONAL].",
        "owner": "Mobile Engineering (Android Platform & Release Engineering)",
        "pattern": (
            r"\b(?:crash\w*|hang\w*|freez\w*|stuck|(?:not|won'?t|doesn'?t|unable\s+to)\s+open\w*|"
            r"trouble\s+in\s+opening|open\s+and\s+close|auto\w*\s+clos\w*|black\s+screen|"
            r"white\s+screen|blank\s+screen|keep\w*\s+stopping|getting\s+stopped|stopped\s+working|"
            r"reinstall\w*|uninstall\w*|not\s+working|doesn'?t\s+work|does\s+not\s+work|"
            r"doesn'?t\s+function|(?:app|screen|page)\s+(?:is\s+)?not\s+loading|keep\w*\s+loading|time\s+to\s+load|load\w*\s+forever|"
            r"application\s+is\s+down|slow\w*|lag\w*|bug\w*|glitch\w*|app\s+error|throwing\s+error|"
            r"something\s+went\s+wrong|install\w*\s+issue|issues?\s+with\s+installation)\b"
        ),
        "symptom_summary": (
            "App freezes on startup (blank/black screen), closes immediately after Play Store updates, "
            "or hangs on loading screens until reinstalled."
        ),
        "root_cause_hypothesis": (
            "Unmigrated local SQLite/Room cache state during in-place Play Store upgrades, combined with "
            "synchronous main-thread network calls on cold start."
        ),
        "telemetry_check": (
            "Compare Crashlytics / Android Vitals cold-start crash and ANR rates for upgrade installs vs. "
            "clean installs across Android OS versions and device OEMs."
        ),
    },
    {
        "theme_id": "T03_PLAYSTORE_INTEGRITY_BLOCK",
        "theme_name": "False 'Not Downloaded from Play Store' Integrity Lockout",
        "track": "TRACK_2_WEIGHTED",
        "user_journey": "App Launch & Device Integrity Verification",
        "severity_score": 5,
        "ease_score": 4,
        "ease_rationale": "Easy (4/5): Localized fix in client installer-package / Play Integrity verification check and caching logic [PROVISIONAL].",
        "owner": "Mobile Engineering (Android Security & Integrity)",
        "pattern": (
            r"(?:not\s+(?:downloaded|installed)\s+(?:from|thru|through|via)\s+(?:the\s+)?play\s*store|"
            r"download\w*\s+from\s+play\s*store|showing\s+not\s+installed)"
        ),
        "symptom_summary": (
            "Legitimate Play Store users are blocked at launch with a false error stating the app was "
            "'not downloaded from the Google Play Store', forcing repeated reinstalls."
        ),
        "root_cause_hypothesis": (
            "Brittle installer-package verification check or transient Play Integrity API token failure "
            "after background auto-updates or enterprise work-profile updates."
        ),
        "telemetry_check": (
            "Log installer package names (com.android.vending, OEM updaters, MDM profiles) and Play Integrity "
            "API error codes whenever the lockout screen triggers."
        ),
    },
    {
        "theme_id": "T04_FORCED_PROMPTS_RATINGS_PERMISSIONS",
        "theme_name": "Mandatory Ride Rating Walls, Intrusive Popups & Forced Permissions",
        "track": "TRACK_2_WEIGHTED",
        "user_journey": "Post-Ride Feedback, App Launch Modals & OS Permission Prompts",
        "severity_score": 3,
        "ease_score": 5,
        "ease_rationale": "Very Easy (5/5): Adding a 'Skip/Dismiss' button to post-ride rating modals and removing non-essential blocking permission/banner gates requires minimal UI/config work [PROVISIONAL].",
        "owner": "Core Product & Mobile UX Team",
        "pattern": (
            r"(?:ask\w*\s+for\s+rat(?:e|ing)|notifying\s+for\s+play\s*store\s+review|"
            r"rethink\s+its\s+rating\s+system|skip\s+(?:the\s+)?(?:rat(?:e|ing)|feedback)|"
            r"no\s+option\s+(?:of|to)\s+skip|(?:forc\w+|mandatory).*?(?:rat(?:e|ing)|feedback)|"
            r"pop\s*-?\s*up\w*|banner\w*|advertisement\w*|\bads\b|microphone|auto\s*-?\s*time\s*zone|"
            r"time\s*zone|permission\w*|turn\s+on\s+notification\w*|seat\s*belt|seat\s*buckle|"
            r"so\s+many\s+notifications|lots\s+of\s+notifications)"
        ),
        "symptom_summary": (
            "Users are blocked from viewing schedules until they rate prior rides (no 'Skip' option), "
            "or interrupted by seatbelt popups hiding boarding OTPs and forced permission prompts."
        ),
        "root_cause_hypothesis": (
            "Non-dismissible post-ride rating modal and blocking OS permission gates at launch, driving "
            "frustrated commuters to post 1-star Play Store ratings."
        ),
        "telemetry_check": (
            "Audit tenant feature flags for mandatory trip feedback, track modal dismissal/block rates, "
            "and review OS permission prompt triggers at app startup."
        ),
    },
    {
        "theme_id": "T05_AUTH_LOGIN_OTP_SESSION",
        "theme_name": "Authentication, Login OTP Delivery & Auto-Logout in Low Network",
        "track": "TRACK_2_WEIGHTED",
        "user_journey": "Account Registration, SSO/OTP Login & Active Trip Session Persistence",
        "severity_score": 4,
        "ease_score": 4,
        "ease_rationale": "Easy-to-Moderate (4/5): Caching active trip details/OTP offline and extending session refresh grace periods are standard client-side resilience improvements [PROVISIONAL].",
        "owner": "Authentication & Mobile Platform Engineering",
        "pattern": (
            r"\b(?:log\s*-?\s*in\w*|logged\s+out|log\s*-?\s*out\w*|logging\s+out|sign\s*-?\s*in\w*|"
            r"otp|verification|authenticate\w*|password|sso|session|offline\s+mode|"
            r"no\s+network|lost\s+signal|internet\s+connect\w*)\b"
        ),
        "symptom_summary": (
            "Delayed or missing SMS/email login OTPs, corporate SSO mapping errors, and automatic session "
            "logouts in low-network parking zones right when the boarding OTP is needed."
        ),
        "root_cause_hypothesis": (
            "Auth interceptor clearing local session tokens on transient network timeouts instead of "
            "retaining cached trip state, plus SMS gateway delivery throttling."
        ),
        "telemetry_check": (
            "Inspect auth token refresh error codes (HTTP 401 vs. network timeout), session duration before "
            "logout, and SMS/email OTP delivery latency logs."
        ),
    },
    {
        "theme_id": "T06_LIVE_TRACKING_GPS_MAP",
        "theme_name": "Live Vehicle Tracking Freeze, GPS Inaccuracy & Map Auto-Zoom",
        "track": "TRACK_2_WEIGHTED",
        "user_journey": "Pre-Boarding Cab Tracking & Map Navigation",
        "severity_score": 4,
        "ease_score": 3,
        "ease_rationale": "Moderate (3/5): Fixing map camera auto-zoom reset is an easy client fix; improving driver GPS telemetry freshness requires driver-app background location tuning [PROVISIONAL].",
        "owner": "Maps, Real-Time Tracking & Driver App Engineering",
        "pattern": (
            r"\b(?:gps|track\w*|map\w*|live\s+location|location\s+update\w*|vehicle\s+location|"
            r"driver\s+location|cab\s+location|shuttles?\s+location|wrong\s+location|incorrect\s+location|"
            r"different\s+location|exact\s+location|location\w*\s+not\s+matching|accurate\s+location|"
            r"see\s+the\s+location|updated\s+in\s+real\s*-?\s*time|zoom\w*|pin\s+location|geo\s*-?\s*fenc\w*)\b"
        ),
        "symptom_summary": (
            "Live cab location freezes or lags by 15–60 minutes, home pickup pins jump to inaccurate "
            "coordinates, and map camera auto-resets zoom every 30 seconds."
        ),
        "root_cause_hypothesis": (
            "Map viewport auto-fit timer overriding manual user zoom gestures, combined with driver-app "
            "background GPS ping throttling or WebSocket staleness."
        ),
        "telemetry_check": (
            "Measure P50/P95 driver GPS ping intervals during active pickup windows, WebSocket delivery lag, "
            "and map camera auto-reset event frequency."
        ),
    },
    {
        "theme_id": "T07_ROUTING_CAB_DELAY_ETA",
        "theme_name": "Routing Detours, Unreliable ETAs & Excessive Commute Times",
        "track": "TRACK_2_WEIGHTED",
        "user_journey": "Route Optimization, Cab Allocation & Commute Execution",
        "severity_score": 4,
        "ease_score": 2,
        "ease_rationale": "Hard (2/5): Tuning multi-stop route solver constraints and ETA prediction models across multi-tenant fleet rules requires algorithmic & ops validation [PROVISIONAL].",
        "owner": "Routing & Dispatch Algorithms Team + Client Transport Operations",
        "pattern": (
            r"\b(?:rout\w+|eta|delay\w*|late|on\s+time|wait\w*\s+time|travel\s+time|long\s+time|"
            r"hours?\s+(?:before|early|daily|late)|pick\s*-?\s*up\s+time|early\s+pick\w*|drop\s+time|"
            r"timings?\s+(?:are\s+)?(?:frequently\s+)?(?:incorrect|wrong)|inaccurate\s+timings?|"
            r"timings?\s+correctly|time\s+management|assign\w*\s+cab\w*|cab\s+not\s+assign\w*|"
            r"cab\s+allocat\w*|cab\s+number|sequence|pooling|club\w*|bharat\s+darshan)\b"
        ),
        "symptom_summary": (
            "Late cab pickups, wildly fluctuating ETAs, last-minute vehicle reassignments, and long "
            "multi-stop pooling detours across distant pickup zones."
        ),
        "root_cause_hypothesis": (
            "Over-aggressive pooling capacity constraints and static travel-time matrices underestimating "
            "peak traffic congestion, plus roster re-sequencing sync lag."
        ),
        "telemetry_check": (
            "Compare predicted ETA vs. actual arrival timestamps by site/shift, audit pooled detour ratios, "
            "and track cab reassignment and unassigned-roster rates."
        ),
    },
    {
        "theme_id": "T08_SCHEDULING_ROSTER_NOSHOW",
        "theme_name": "Schedule Sync Bugs, Unfair 'No-Show' Penalties & Booking Cutoffs",
        "track": "TRACK_2_WEIGHTED",
        "user_journey": "Shift Scheduling, Roster Modification, Check-In & Desk/Shuttle Booking",
        "severity_score": 4,
        "ease_score": 3,
        "ease_rationale": "Moderate (3/5): Fixing empty schedule list rendering, adding AM/PM format clarity, and alerting users before auto-canceling return trips are 1-2 sprint fixes [PROVISIONAL].",
        "owner": "Scheduling, Roster & Workplace Booking Product/Engineering",
        "pattern": (
            r"\b(?:schedul\w*|roster\w*|book\w*|cancel\w*|no\s*-?\s*show|cutoff|cut\s*-?\s*off|"
            r"modify|reschedul\w*|adhoc|ad\s*-?\s*hoc|slot\w*|seat\s+number|desk|parking|shuttle|"
            r"shift\s+time|am\s*/\s*pm)\b"
        ),
        "symptom_summary": (
            "Booked schedules fail to display on the calendar, and morning 'No-Show' flags automatically "
            "cancel the employee's evening return cab without warning."
        ),
        "root_cause_hypothesis": (
            "Date-range pagination bug in the schedule list API client, and coupled morning-to-evening "
            "No-Show cancellation rules firing without user confirmation."
        ),
        "telemetry_check": (
            "Inspect schedule API save/fetch failure logs, driver geofence dwell-time logs on No-Show triggers, "
            "and auto-cancelled evening logout trip counts."
        ),
    },
    {
        "theme_id": "T09_UI_UX_USABILITY",
        "theme_name": "Cluttered UI Navigation, Multi-Step Flows & Broken In-App Feedback",
        "track": "TRACK_2_WEIGHTED",
        "user_journey": "Home Dashboard Navigation, Shuttle/Desk Selection & In-App Feedback",
        "severity_score": 2,
        "ease_score": 4,
        "ease_rationale": "Easy (4/5): Streamlining home screen actions, fixing broken feedback text inputs, and saving default floor/shift preferences are straightforward client UX improvements [PROVISIONAL].",
        "owner": "Mobile Product Design & Frontend Engineering",
        "pattern": (
            r"\b(?:ui\b|user\s+interface|user\s*-?\s*friendly|unfriendly|simplif\w*|confus\w*|"
            r"navigat\w+|drop\s*-?\s*down\w*|too\s+many\s+clicks|2\s+step\s+process|"
            r"retain\s+incorrect\s+preferences|doesn'?t\s+allow\s+feedback|"
            r"feedback\s+(?:option|link|text\s*box|notification))\b"
        ),
        "symptom_summary": (
            "Cluttered multi-step booking flow, difficulty distinguishing the assigned cab on the home screen, "
            "and an unclickable text box in the in-app feedback form."
        ),
        "root_cause_hypothesis": (
            "Multi-module dashboard navigation without saved user defaults, plus an input-focus regression "
            "in the in-app feedback component."
        ),
        "telemetry_check": (
            "Track in-app feedback open-to-submit conversion rate, input-focus error logs, and booking "
            "funnel step drop-off rates."
        ),
    },
    {
        "theme_id": "T10_DRIVER_VENDOR_HELPDESK",
        "theme_name": "Driver Behavior, Vendor Fleet Quality & Unresponsive Helpdesk",
        "track": "TRACK_2_WEIGHTED",
        "user_journey": "On-Ground Pickup, Ride Experience & Transport Helpdesk Escalation",
        "severity_score": 3,
        "ease_score": 2,
        "ease_rationale": "Hard (2/5): Operational driver discipline and client transport vendor SLAs lie largely outside mobile code, though in-app escalation and callback routing can be improved [PROVISIONAL].",
        "owner": "Fleet Operations, Vendor Management & Client Transport Helpdesk",
        "pattern": (
            r"\b(?:driver\w*|vendor\w*|cab\s+provider\w*|transport\s+service\w*|cab\s+service\w*|"
            r"cab\s+management|customer\s+care|customer\s+support|help\s*desk|support\s+team|"
            r"transport\s+team|\bsupport\b|rude|arrogan\w*|unprofessional|behav\w*|call\w*\s+driver|"
            r"pick\s+the\s+call|ac\s+not\s+working|dirty\s+cab|car\s+condition|vehicle\s+condition)\b"
        ),
        "symptom_summary": (
            "Drivers not answering calls, rude behavior, or poor cab/AC upkeep, compounded by unreachable "
            "site transport helpdesk lines during peak shift hours."
        ),
        "root_cause_hypothesis": (
            "Vendor SLA compliance gaps at client sites and lack of automated callback routing when "
            "site helpdesk phone queues are saturated."
        ),
        "telemetry_check": (
            "Measure site helpdesk call-queue abandonment rates by shift hour, vendor SLA violation logs, "
            "and in-app driver call-connection success rates."
        ),
    },
]


def assign_window_bucket(dt: pd.Timestamp) -> str:
    """Assigns each review timestamp to a mutually exclusive top-level window bucket."""
    if pd.isna(dt):
        return "unknown"
    if PRIMARY_START <= dt <= PRIMARY_END:
        return "primary_2025_09_to_2026_09"
    if dt > PRIMARY_END:
        return "post_window_oct_2026"
    return "historical_pre_2025_09"


def assign_90d_subwindow(dt: pd.Timestamp) -> str:
    """Assigns reviews inside the primary window to Recent 90d, Prior 90d, or Earlier Primary."""
    if pd.isna(dt):
        return "outside_primary"
    if RECENT_90D_START <= dt <= RECENT_90D_END:
        return "recent_90d_2026_07_03_to_2026_09_30"
    if PRIOR_90D_START <= dt <= PRIOR_90D_END:
        return "prior_90d_2026_04_04_to_2026_07_02"
    if PRIMARY_START <= dt < PRIOR_90D_START:
        return "earlier_primary_2025_09_01_to_2026_04_03"
    return "outside_primary"


def normalize_version_major_minor(ver: Any) -> str:
    """Extracts major.minor version (e.g. '12.19' from '12.19.0') or 'Unspecified'."""
    if ver is None or pd.isna(ver):
        return "Unspecified"
    s = str(ver).strip()
    if not s or s.lower() in ("none", "nan", "null"):
        return "Unspecified"
    m = re.match(r"^(\d+\.\d+)", s)
    return f"v{m.group(1)}" if m else s


def run_preprocessing_and_classification(base_dir: Path) -> pd.DataFrame:
    """Loads raw JSONL, deduplicates by reviewId, assigns windows, and classifies themes."""
    raw_dir = base_dir / "data" / "raw"
    proc_dir = base_dir / "data" / "processed"
    proc_dir.mkdir(parents=True, exist_ok=True)

    jsonl_path = raw_dir / "reviews_raw_latest.jsonl"
    manifest_path = raw_dir / "manifest_latest.json"

    records = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    raw_df = pd.DataFrame(records)
    print(f"Loaded {len(raw_df)} raw rows from {jsonl_path.name}")

    # Track cohort membership per reviewId before deduplicating
    cohort_map: Dict[str, Dict[str, Any]] = {}
    for _, row in raw_df.iterrows():
        rid = row.get("reviewId")
        if not rid:
            continue
        sname = str(row.get("_slice_name", ""))
        qlang = str(row.get("_query_lang", "en"))
        if rid not in cohort_map:
            cohort_map[rid] = {
                "in_cohort_a_unfiltered": False,
                "in_cohort_b_stratified": False,
                "in_multilingual": False,
                "slices_seen": [],
                "langs_seen": [],
            }
        if sname == "cohort_a_unfiltered_newest":
            cohort_map[rid]["in_cohort_a_unfiltered"] = True
        elif sname.startswith("cohort_b_"):
            cohort_map[rid]["in_cohort_b_stratified"] = True
        elif sname.startswith("multilingual_"):
            cohort_map[rid]["in_multilingual"] = True
        if sname not in cohort_map[rid]["slices_seen"]:
            cohort_map[rid]["slices_seen"].append(sname)
        if qlang not in cohort_map[rid]["langs_seen"]:
            cohort_map[rid]["langs_seen"].append(qlang)

    # Deduplicate strictly by reviewId
    df = raw_df.drop_duplicates(subset=["reviewId"], keep="first").copy()
    df["in_cohort_a_unfiltered"] = df["reviewId"].map(lambda x: cohort_map[x]["in_cohort_a_unfiltered"])
    df["in_cohort_b_stratified"] = df["reviewId"].map(lambda x: cohort_map[x]["in_cohort_b_stratified"])
    df["in_multilingual"] = df["reviewId"].map(lambda x: cohort_map[x]["in_multilingual"])
    df["slices_seen"] = df["reviewId"].map(lambda x: "|".join(cohort_map[x]["slices_seen"]))
    df["langs_seen"] = df["reviewId"].map(lambda x: "|".join(cohort_map[x]["langs_seen"]))

    # Parse timestamps and assign strict temporal windows
    df["at_dt"] = pd.to_datetime(df["at"], errors="coerce")
    df["replied_at_dt"] = pd.to_datetime(df["repliedAt"], errors="coerce")
    df["year_month"] = df["at_dt"].dt.strftime("%Y-%m")
    df["window_bucket"] = df["at_dt"].apply(assign_window_bucket)
    df["subwindow_90d"] = df["at_dt"].apply(assign_90d_subwindow)

    # Clean text and metadata fields
    df["content_clean"] = df["content"].fillna("").astype(str).str.strip()
    df["char_len"] = df["content_clean"].str.len()
    df["word_count"] = df["content_clean"].str.split().str.len()
    df["version_raw"] = df["reviewCreatedVersion"].fillna("Unspecified").replace({"None": "Unspecified", "": "Unspecified"})
    df["version_family"] = df["reviewCreatedVersion"].apply(normalize_version_major_minor)
    df["has_developer_reply"] = (
        df["replyContent"].notna()
        & (df["replyContent"].astype(str).str.strip() != "")
        & (df["replyContent"].astype(str) != "None")
    )
    df["reply_delay_hours"] = (
        (df["replied_at_dt"] - df["at_dt"]).dt.total_seconds() / 3600.0
    ).where(df["has_developer_reply"], other=None)

    # Apply multi-label theme classification
    theme_cols = []
    for tdef in THEME_DEFINITIONS:
        col = tdef["theme_id"]
        theme_cols.append(col)
        df[col] = df["content_clean"].str.contains(tdef["pattern"], case=False, regex=True)

    df["matched_theme_count"] = df[theme_cols].sum(axis=1)
    df["matched_themes_list"] = df.apply(
        lambda r: "|".join([c for c in theme_cols if r[c]]) if r["matched_theme_count"] > 0 else "UNSPECIFIED_OR_GENERIC",
        axis=1,
    )
    df["is_generic_uninformative"] = (df["matched_theme_count"] == 0)

    # Sort chronologically (newest first)
    df = df.sort_values("at_dt", ascending=False).reset_index(drop=True)

    # Save master classified dataset
    master_out = proc_dir / "reviews_master_classified.csv"
    df.to_csv(master_out, index=False, encoding="utf-8-sig")

    # Save dedicated Primary Window dataset (Sept 2025 - Sept 2026 ONLY)
    df_primary = df[df["window_bucket"] == "primary_2025_09_to_2026_09"].copy()
    df_primary.to_csv(proc_dir / "reviews_primary_2025_09_to_2026_09.csv", index=False, encoding="utf-8-sig")

    # Build Coverage Audit Table from manifest
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    cov_df = pd.DataFrame(manifest["slices"])
    cov_df.to_csv(proc_dir / "coverage_audit_table.csv", index=False, encoding="utf-8-sig")

    print(f"Saved deduplicated master dataset ({len(df)} unique reviews) to {master_out.name}")
    print(f"Primary Window (2025-09-01 to 2026-09-30) count: {len(df_primary)}")
    print("Window bucket breakdown:")
    print(df["window_bucket"].value_counts())
    return df


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    run_preprocessing_and_classification(project_root)
