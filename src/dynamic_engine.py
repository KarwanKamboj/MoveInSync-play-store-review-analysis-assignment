"""
Dynamic Play Store Rating Intelligence & Report Generation Engine for MoveInSync (com.moveinsync.ets).

Single shared analysis layer that executes date filtering, review classification,
aggregation, trend evaluation, priority scoring, recommendation synthesis, chart generation,
and HTML/PDF export from one validated result object:

  1. Primary-Window & Comparison-Window Count Integrity (P0):
     - Applies the exact same THEME_DEFINITIONS across Primary, Recent, and Preceding windows.
     - Counts distinct deduplicated reviews (reviewId), never duplicate keyword hits.
     - Explicitly documents multi-label classification and validates all denominators and numerators.

  2. Cross-Section Consistency (P0):
     - Computes all metrics once in generate_dynamic_report() and drives Executive Summary,
       Top 3 Problems, Trend Summary, Priority Rankings, Action Plan, Owners/Metrics, and Appendix
       from the same validated data structures.

  3. Trend Calculation & Minimum-Evidence Safeguards:
     - Configurable provisional threshold (MIN_COMPARISON_WINDOW_REVIEWS = 10).
     - Distinguishes percentage-point change (recent_rate - preceding_rate, in pp) from relative % change.
     - Returns explicit statuses ("No baseline available", "Insufficient evidence", "No matching reviews")
       when denominators are zero or sample sizes fall below threshold.

  4. Documented 5-Factor Priority Scoring & Separate Safety Escalation:
     - Priority Score = 0.25*F + 0.25*S + 0.20*T + 0.15*C + 0.15*E on a 1.00–5.00 scale.
     - Never awards an evidence-backed score to a 0-review theme (priority_score_1_to_5 = None).
     - Does not treat missing review data as zero severity.
     - Caps trend score T at neutral (3) when sample size is below threshold.
     - Routes credible safety reports (count > 0) to a separate Safety Escalation track.
"""

import base64
import datetime as dt
import io
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.analyze_and_prioritize import (
    score_evidence_strength_1_to_5,
    score_frequency_1_to_5,
    score_trend_1_to_5,
)
from src.collect import run_collection
from src.preprocess_and_classify import (
    THEME_DEFINITIONS,
    normalize_version_major_minor,
)

METHODOLOGY_VERSION = "v2.4.0-clean-executive-ui"
TIMEZONE_LABEL = "IST (UTC+05:30, Storefront gl=in)"

# Configurable minimum-evidence thresholds (provisional reporting safeguards)
MIN_COMPARISON_WINDOW_REVIEWS = 10
MIN_THEME_MATCHING_PER_WINDOW = 10
MIN_CONFIRMED_THEME_REVIEWS = 3
MIN_REPRESENTATIVE_PRIMARY_REVIEWS = 30
MIN_SUFFICIENT_PRIMARY_LOW_REVIEWS = 10

PRIORITY_WEIGHTS: Dict[str, float] = {
    "frequency_F": 0.25,
    "severity_S": 0.25,
    "trend_T": 0.20,
    "confidence_C": 0.15,
    "feasibility_E": 0.15,
}

# Grounded 7-part recommendation specifications per theme (avoiding fabricated internal code claims)
THEME_ACTION_SPECS: Dict[str, Dict[str, str]] = {
    "T01_SAFETY_SOS_EMERGENCY": {
        "user_problem": (
            "Commuters report difficulty accessing the in-app Emergency SOS / panic control during active trips "
            "or express night-shift security concerns when trips are cancelled or drivers deviate."
        ),
        "why_important": (
            "Passenger physical safety and emergency escalation during night-shift and early-morning commutes "
            "carry zero-tolerance operational risk and cannot wait for volume-based prioritization."
        ),
        "first_concrete_action": (
            "Audit the active-trip UI layer to ensure the Emergency SOS control remains visible and clickable above all "
            "modals/popups, and verify that site transport desks receive immediate phone/SMS alerts before any night-shift "
            "trip is cancelled or marked No-Show."
        ),
        "validation_metric": (
            "100% of test and production SOS triggers reach the transport security desk within < 2 seconds regardless "
            "of modal/network state; 0 night-shift unverified No-Show safety escalations."
        ),
        "missing_telemetry_to_confirm": (
            "In-app SOS tap event logs, modal overlay impression timestamps during active rides, and night-shift "
            "transport-desk escalation audit logs."
        ),
    },
    "T02_CRASH_LAUNCH_PERFORMANCE": {
        "user_problem": (
            "The app freezes on startup (blank/black screen), hangs during navigation, or crashes immediately after "
            "Play Store updates when employees try to view their trip or boarding pass."
        ),
        "why_important": (
            "Launch failures during the 15-minute pickup window lock commuters out of seeing their cab number, "
            "driver contact, and boarding OTP, directly causing missed pickups and helpdesk call spikes."
        ),
        "first_concrete_action": (
            "Triage cold-start crashes and ANRs by app version and Android OS/device model in Crashlytics / Play Console "
            "Android Vitals, and cache confirmed next-ride details (Cab ID, Driver phone, Boarding OTP) locally so the "
            "home screen renders offline."
        ),
        "validation_metric": (
            "Achieve >= 99.5% crash-free sessions in Google Play Console Android Vitals and reduce Crash/Launch "
            "low-star complaint share by >= 50% over the next 90 days."
        ),
        "missing_telemetry_to_confirm": (
            "Firebase Crashlytics stack traces, Play Console ANR vitals segmented by release version (e.g., v12.19) "
            "and device model, and cold-start API latency P95/P99."
        ),
    },
    "T03_PLAYSTORE_INTEGRITY_BLOCK": {
        "user_problem": (
            "Employees who installed or updated MoveInSync directly from the official Google Play Store are blocked "
            "at launch by an error stating the app was 'not downloaded from the Play Store'."
        ),
        "why_important": (
            "False-positive install-source blocks completely lock legitimate corporate commuters out of the app "
            "even after repeated uninstall/reinstall attempts."
        ),
        "first_concrete_action": (
            "Inspect client-side installer-package verification logic across Android enterprise/Work Profile and "
            "Play Store auto-update paths, and allow verified APK signatures to proceed with a telemetry warning "
            "instead of a hard launch lockout."
        ),
        "validation_metric": (
            "0 false-positive 'not downloaded from Play Store' lockout complaints in Play Store reviews within "
            "60 days of release."
        ),
        "missing_telemetry_to_confirm": (
            "Client integrity-check rejection logs showing the reported installer package string, Android OS version, "
            "and device OEM for blocked sessions."
        ),
    },
    "T04_FORCED_PROMPTS_RATINGS_PERMISSIONS": {
        "user_problem": (
            "Mandatory post-ride rating popups without a skip option, mid-boarding seatbelt/buckle prompts, "
            "and forced permission blockers interrupt commuters while trying to view trip details or boarding OTPs."
        ),
        "why_important": (
            "Blocking modals at the cab door delay boarding OTP verification, frustrate hurried commuters, and "
            "induce retaliatory 1-star Play Store reviews."
        ),
        "first_concrete_action": (
            "Add an explicit 'Skip / Remind Later' dismissal option to post-ride feedback modals and defer seatbelt "
            "confirmation prompts until after the boarding OTP has been verified."
        ),
        "validation_metric": (
            "Reduce Forced Prompt & Popup complaint rate below 1.5% of low-star reviews within 60 days while "
            "tracking in-app ride rating submission completion."
        ),
        "missing_telemetry_to_confirm": (
            "Modal impression-to-dismissal funnel events, timestamp delta between modal display and OTP verification, "
            "and permission-denial drop-off logs."
        ),
    },
    "T05_AUTH_LOGIN_OTP_SESSION": {
        "user_problem": (
            "Commuters are unexpectedly logged out when entering low-network zones (basements/parking) and face "
            "delayed or failed SMS/Email login OTPs when trying to sign back in."
        ),
        "why_important": (
            "An unexpected logout at pickup time without OTP delivery prevents employees from accessing their "
            "boarding pass or driver contact when standing in low-signal pickup zones."
        ),
        "first_concrete_action": (
            "Preserve local authenticated sessions across transient network timeouts (avoiding token wipe on offline "
            "errors) and retain read-only offline access to the active trip pass during commute windows."
        ),
        "validation_metric": (
            "Cut unexpected auto-logout and OTP failure complaints by >= 50% over 90 days and achieve >= 98.5% "
            "OTP delivery within 15 seconds across SMS and corporate Email."
        ),
        "missing_telemetry_to_confirm": (
            "Auth token refresh error codes (401 vs. network timeout), session duration distribution prior to logout, "
            "and SMS/Email gateway delivery latency logs."
        ),
    },
    "T06_LIVE_TRACKING_GPS_MAP": {
        "user_problem": (
            "The live cab tracking map freezes, shows stale or inaccurate vehicle GPS coordinates, or automatically "
            "resets its zoom level every 30 seconds while commuters try to track approaching cabs."
        ),
        "why_important": (
            "Unreliable live tracking causes commuters to miss pickups or wait outdoors unnecessarily without knowing "
            "whether the cab has arrived."
        ),
        "first_concrete_action": (
            "Disable automatic map camera zoom resets after a user manually pans/zooms, add a manual 'Re-center' button, "
            "and display a 'Last updated X sec ago' GPS staleness indicator on the tracking card."
        ),
        "validation_metric": (
            "Reduce Live Tracking & Map GPS complaints by >= 45% within 90 days and maintain P95 driver location "
            "update lag below 15 seconds during active pickup windows."
        ),
        "missing_telemetry_to_confirm": (
            "Driver-app GPS ping interval distribution, WebSocket/polling latency to commuter clients, and map camera "
            "reset event frequency."
        ),
    },
    "T07_ROUTING_CAB_DELAY_ETA": {
        "user_problem": (
            "Commuters experience late cab pickups, inaccurate ETAs that jump repeatedly, last-minute vehicle "
            "reassignments, and long multi-stop pooling detours."
        ),
        "why_important": (
            "Unpredictable pickup delays and excessive route detours directly impact employee shift punctuality "
            "and represent one of the fastest-growing sources of recent dissatisfaction."
        ),
        "first_concrete_action": (
            "Audit routes and sites with the highest ETA slippage, send proactive push notifications when pickup ETA "
            "shifts by > 10 minutes, and tighten maximum detour ratio guardrails in the pooling solver."
        ),
        "validation_metric": (
            "Reduce Routing & Cab Delay complaint share below 11.0% of low-star reviews and improve P90 pickup ETA "
            "accuracy to within +/- 6 minutes."
        ),
        "missing_telemetry_to_confirm": (
            "Planned vs. actual trip duration logs by site/shift, ETA prediction error distribution, and cab "
            "reassignment/unassigned-roster rates."
        ),
    },
    "T08_SCHEDULING_ROSTER_NOSHOW": {
        "user_problem": (
            "Roster bookings fail to save or sync, calendar views do not load full-month schedules, and commuters "
            "report unfair 'No-Show' penalties or automatic cancellation of their evening return cab."
        ),
        "why_important": (
            "Silently cancelling an employee's evening logout ride after a morning No-Show or failing to persist "
            "roster edits leaves commuters stranded at the office without transport."
        ),
        "first_concrete_action": (
            "Decouple evening return-cab cancellation from morning No-Show events by sending an interactive confirmation "
            "prompt ('Do you still need your evening cab?'), and verify roster save/load pagination across month boundaries."
        ),
        "validation_metric": (
            "Reduce Schedule Sync & No-Show complaints by >= 45% within 90 days and cut helpdesk disputes over "
            "auto-cancelled return rides by 40%."
        ),
        "missing_telemetry_to_confirm": (
            "Roster API save/fetch failure logs, No-Show rule trigger logs (driver geofence dwell time at pickup), "
            "and auto-cancelled logout trip counts."
        ),
    },
    "T09_UI_UX_USABILITY": {
        "user_problem": (
            "Users report a cluttered multi-step booking flow, difficulty distinguishing their assigned cab from "
            "other vehicles on the dashboard, and an unclickable in-app feedback text box."
        ),
        "why_important": (
            "Confusing booking confirmation states cause accidental unbooked rides, and a broken in-app feedback input "
            "pushes frustrated users to post 1-star reviews on the public Play Store."
        ),
        "first_concrete_action": (
            "Fix the text-input focus bug in the in-app feedback form and highlight the user's assigned vehicle "
            "and booking confirmation badge prominently on the home screen."
        ),
        "validation_metric": (
            "Reduce UI Navigation & Feedback complaints below 4.0% of low-star reviews within 60 days and increase "
            "in-app feedback form submission success rate."
        ),
        "missing_telemetry_to_confirm": (
            "In-app feedback screen open-to-submit conversion rate and booking flow step drop-off analytics."
        ),
    },
    "T10_DRIVER_VENDOR_HELPDESK": {
        "user_problem": (
            "Commuters cite rude or reckless driver behavior, poor cab maintenance/AC issues, drivers not answering "
            "calls, and inability to reach transport helpdesk lines during peak shift hours."
        ),
        "why_important": (
            "When an on-road delay or driver issue occurs and helpdesk phone lines are unreachable, commuters have "
            "no operational recourse except public Play Store escalation."
        ),
        "first_concrete_action": (
            "Add a 1-tap 'Request Helpdesk Callback' option in the active trip screen that passes Trip ID and Cab ID "
            "to site transport ops, and restore a < 24-hour Play Store developer reply SLA on 1–2★ reviews."
        ),
        "validation_metric": (
            "Increase Play Store 1–2★ developer reply rate to >= 80% within 30 days and reduce Driver & Helpdesk "
            "complaint share by >= 30% over 90 days."
        ),
        "missing_telemetry_to_confirm": (
            "Site helpdesk call-queue abandonment rates by shift hour, vendor SLA violation logs, and driver "
            "call-connection success metrics."
        ),
    },
}

SHORT_THEME_NAMES: Dict[str, str] = {
    "T01_SAFETY_SOS_EMERGENCY": "Safety & SOS Emergency",
    "T02_CRASH_LAUNCH_PERFORMANCE": "App Crashes & Freeze",
    "T03_PLAYSTORE_INTEGRITY_BLOCK": "Play Store Integrity Block",
    "T04_FORCED_PROMPTS_RATINGS_PERMISSIONS": "Forced Rating & Popups",
    "T05_AUTH_LOGIN_OTP_SESSION": "Login, OTP & Auto-Logout",
    "T06_LIVE_TRACKING_GPS_MAP": "Live Tracking & Map GPS",
    "T07_ROUTING_CAB_DELAY_ETA": "Routing & Cab Delays",
    "T08_SCHEDULING_ROSTER_NOSHOW": "Schedule Sync & No-Show",
    "T09_UI_UX_USABILITY": "UI Navigation & Feedback",
    "T10_DRIVER_VENDOR_HELPDESK": "Driver & Helpdesk Support",
}

SHORT_OWNER_NAMES: Dict[str, str] = {
    "T01_SAFETY_SOS_EMERGENCY": "Safety & Mobile Eng",
    "T02_CRASH_LAUNCH_PERFORMANCE": "Android Platform Team",
    "T03_PLAYSTORE_INTEGRITY_BLOCK": "Mobile SecOps & Release",
    "T04_FORCED_PROMPTS_RATINGS_PERMISSIONS": "Mobile Product & Growth",
    "T05_AUTH_LOGIN_OTP_SESSION": "Identity & Auth Team",
    "T06_LIVE_TRACKING_GPS_MAP": "Geo-Tracking & Maps",
    "T07_ROUTING_CAB_DELAY_ETA": "Routing & Dispatch Eng",
    "T08_SCHEDULING_ROSTER_NOSHOW": "Scheduling & Booking",
    "T09_UI_UX_USABILITY": "Mobile Design & UX",
    "T10_DRIVER_VENDOR_HELPDESK": "Fleet Ops & CX Support",
}

# High-specificity domain anchors vs. broad single-word terms for review-to-theme verification
HIGH_SPECIFICITY_TERMS: Dict[str, re.Pattern] = {
    "T01_SAFETY_SOS_EMERGENCY": re.compile(
        r"\b(?:sos|panic|emergency|unsafe|rash\s*driv\w*|drunk\w*|harass\w*|sahayta|women'?s?\s+safety|"
        r"women\s+security|female\s+employees?\s+at\s+logout|going\s+alone\s+at\s+night)\b",
        re.IGNORECASE,
    ),
    "T02_CRASH_LAUNCH_PERFORMANCE": re.compile(
        r"\b(?:crash\w*|hang\w*|freez\w*|(?:not|won'?t|doesn'?t|unable\s+to)\s+open\w*|black\s+screen|"
        r"white\s+screen|blank\s+screen|keep\w*\s+stopping|stopped\s+working|reinstall\w*|uninstall\w*)\b",
        re.IGNORECASE,
    ),
    "T03_PLAYSTORE_INTEGRITY_BLOCK": re.compile(
        r"(?:not\s+(?:downloaded|installed)\s+(?:from|thru|through|via)\s+(?:the\s+)?play\s*store|"
        r"download\w*\s+from\s+play\s*store|showing\s+not\s+installed)",
        re.IGNORECASE,
    ),
    "T04_FORCED_PROMPTS_RATINGS_PERMISSIONS": re.compile(
        r"(?:ask\w*\s+for\s+rat(?:e|ing)|skip\s+(?:the\s+)?(?:rat(?:e|ing)|feedback)|"
        r"no\s+option\s+(?:of|to)\s+skip|(?:forc\w+|mandatory).*?(?:rat(?:e|ing)|feedback)|"
        r"pop\s*-?\s*up\w*|seat\s*belt|seat\s*buckle|microphone|auto\s*-?\s*time\s*zone)",
        re.IGNORECASE,
    ),
    "T05_AUTH_LOGIN_OTP_SESSION": re.compile(
        r"\b(?:logged\s+out|log\s*-?\s*out\w*|logging\s+out|otp|authenticate\w*|sso|no\s+network|lost\s+signal)\b",
        re.IGNORECASE,
    ),
    "T06_LIVE_TRACKING_GPS_MAP": re.compile(
        r"\b(?:gps|live\s+location|location\s+update\w*|vehicle\s+location|driver\s+location|cab\s+location|"
        r"wrong\s+location|incorrect\s+location|zoom\w*|pin\s+location|geo\s*-?\s*fenc\w*)\b",
        re.IGNORECASE,
    ),
    "T07_ROUTING_CAB_DELAY_ETA": re.compile(
        r"\b(?:rout\w+|eta|delay\w*|wait\w*\s+time|travel\s+time|pick\s*-?\s*up\s+time|early\s+pick\w*|"
        r"drop\s+time|cab\s+not\s+assign\w*|cab\s+allocat\w*|pooling|bharat\s+darshan)\b",
        re.IGNORECASE,
    ),
    "T08_SCHEDULING_ROSTER_NOSHOW": re.compile(
        r"\b(?:schedul\w*|roster\w*|no\s*-?\s*show|cutoff|cut\s*-?\s*off|reschedul\w*|adhoc|ad\s*-?\s*hoc|"
        r"shuttle|shift\s+time)\b",
        re.IGNORECASE,
    ),
    "T09_UI_UX_USABILITY": re.compile(
        r"\b(?:user\s+interface|user\s*-?\s*friendly|unfriendly|navigat\w+|drop\s*-?\s*down\w*|"
        r"too\s+many\s+clicks|2\s+step\s+process|doesn'?t\s+allow\s+feedback|feedback\s+(?:option|link|text\s*box))\b",
        re.IGNORECASE,
    ),
    "T10_DRIVER_VENDOR_HELPDESK": re.compile(
        r"\b(?:driver\w*|vendor\w*|cab\s+provider\w*|customer\s+care|customer\s+support|help\s*desk|"
        r"rude|arrogan\w*|unprofessional|ac\s+not\s+working|dirty\s+cab|vehicle\s+condition)\b",
        re.IGNORECASE,
    ),
}

# Positive-only 4-5* reviews without any complaint/contrast marker should not be counted as complaint matches
NEGATIVE_CONTRAST_PATTERN = re.compile(
    r"\b(?:but|however|issue\w*|problem\w*|not|no|never|worst|bad|poor|slow|fail\w*|wrong|error\w*|"
    r"bug\w*|crash\w*|stuck|hang\w*|freez\w*|delay\w*|late|unable|doesn'?t|don'?t|won'?t|can'?t|"
    r"cannot|unfair|rude|unsafe|annoy\w*|frustrat\w*|terrible|pathetic|useless|horrible|force\w*)\b",
    re.IGNORECASE,
)


def list_available_snapshots(base_dir: Path) -> List[Dict[str, Any]]:
    """Lists all available raw review snapshots in data/raw/ with metadata."""
    raw_dir = base_dir / "data" / "raw"
    snapshots: List[Dict[str, Any]] = []
    if not raw_dir.exists():
        return snapshots

    for manifest_file in sorted(raw_dir.glob("manifest_*.json"), reverse=True):
        if manifest_file.name == "manifest_latest.json":
            continue
        snap_id = manifest_file.stem.replace("manifest_", "")
        jsonl_file = raw_dir / f"reviews_raw_{snap_id}.jsonl"
        meta_file = raw_dir / f"app_metadata_{snap_id}.json"
        if jsonl_file.exists():
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    mdata = json.load(f)
                snapshots.append(
                    {
                        "snapshot_id": snap_id,
                        "retrieved_at_utc": mdata.get("collection_completed_utc", ""),
                        "unique_reviews": mdata.get("total_unique_reviews_deduplicated", 0),
                        "raw_rows": mdata.get("total_raw_rows_written", 0),
                        "jsonl_file": jsonl_file.name,
                        "metadata_file": meta_file.name if meta_file.exists() else "app_metadata_latest.json",
                    }
                )
            except Exception:
                pass

    latest_manifest = raw_dir / "manifest_latest.json"
    if latest_manifest.exists():
        try:
            with open(latest_manifest, "r", encoding="utf-8") as f:
                mdata = json.load(f)
            snapshots.insert(
                0,
                {
                    "snapshot_id": "latest",
                    "retrieved_at_utc": mdata.get("collection_completed_utc", ""),
                    "unique_reviews": mdata.get("total_unique_reviews_deduplicated", 0),
                    "raw_rows": mdata.get("total_raw_rows_written", 0),
                    "jsonl_file": "reviews_raw_latest.jsonl",
                    "metadata_file": "app_metadata_latest.json",
                },
            )
        except Exception:
            pass
    return snapshots


def inspect_review_theme_assignments(
    content: str,
    score: int,
    word_count: int,
    matched_theme_ids: List[str],
) -> Dict[str, Any]:
    """
    Audits a review's theme matches, computes per-theme specificity scores,
    identifies the primary theme, generates an explicit assignment_reason per theme,
    and flags ambiguous/brief matches for manual review.
    """
    if not matched_theme_ids:
        return {
            "primary_theme_id": None,
            "per_theme": {},
        }

    per_theme: Dict[str, Dict[str, Any]] = {}
    for tdef in THEME_DEFINITIONS:
        tid = tdef["theme_id"]
        if tid not in matched_theme_ids:
            continue
        raw_matches = re.findall(tdef["pattern"], content, flags=re.IGNORECASE)
        seen_m: List[str] = []
        for m in raw_matches:
            m_str = m.strip() if isinstance(m, str) else " ".join(x for x in m if x).strip()
            if m_str and m_str.lower() not in [s.lower() for s in seen_m]:
                seen_m.append(m_str)

        high_spec_regex = HIGH_SPECIFICITY_TERMS.get(tid)
        high_hits = high_spec_regex.findall(content) if high_spec_regex else []
        n_high = len(high_hits)

        spec_score = len(seen_m) * 2 + n_high * 3 + sum(1 for s in seen_m if len(s.split()) >= 2)
        per_theme[tid] = {
            "matched_keywords": seen_m[:4],
            "high_spec_hits": n_high,
            "specificity_score": spec_score,
        }

    sorted_tids = sorted(
        per_theme.keys(),
        key=lambda t: (per_theme[t]["specificity_score"], per_theme[t]["high_spec_hits"]),
        reverse=True,
    )
    primary_tid = sorted_tids[0] if sorted_tids else None
    primary_short = SHORT_THEME_NAMES.get(primary_tid, primary_tid or "")
    n_themes = len(sorted_tids)

    for tid in sorted_tids:
        info = per_theme[tid]
        kw_str = ", ".join(f'"{k}"' for k in info["matched_keywords"]) if info["matched_keywords"] else "domain pattern"
        is_prim = (tid == primary_tid)
        is_brief_ambiguous = (word_count < 6 and info["high_spec_hits"] == 0)
        is_weak_secondary = (not is_prim and n_themes >= 2 and info["high_spec_hits"] == 0 and info["specificity_score"] <= 3)
        is_positive_ambiguous = (score >= 4 and not bool(NEGATIVE_CONTRAST_PATTERN.search(content)))

        needs_manual = bool(is_brief_ambiguous or is_weak_secondary or is_positive_ambiguous)

        if is_brief_ambiguous:
            conf_label = "Uncertain — Flagged for Manual Review"
            reason = (
                f"Matched keyword {kw_str} in a brief {word_count}-word review; "
                f"flagged for manual review due to limited context."
            )
        elif is_positive_ambiguous:
            conf_label = "Uncertain — Flagged for Manual Review"
            reason = (
                f"Matched keyword {kw_str} in a {score}★ review without explicit negative markers; "
                f"flagged for manual verification."
            )
        elif is_weak_secondary:
            conf_label = "Secondary Overlap — Flagged for Manual Review"
            reason = (
                f"Secondary keyword match on {kw_str}; review primarily targets "
                f"{primary_short} ({', '.join(per_theme[primary_tid]['matched_keywords'][:2])})."
            )
        elif is_prim and n_themes == 1:
            conf_label = "Verified Direct Match"
            reason = f"Single-theme direct match on {kw_str}."
        elif is_prim and n_themes > 1:
            other_names = [SHORT_THEME_NAMES.get(ot, ot) for ot in sorted_tids if ot != tid]
            conf_label = "Verified Primary Match (Multi-Symptom)"
            reason = (
                f"Primary complaint match on {kw_str} "
                f"(review also mentions {', '.join(other_names[:2])})."
            )
        else:
            conf_label = f"Justified Multi-Label Match (Primary: {primary_short})"
            reason = (
                f"Distinct multi-symptom clause matching {kw_str} alongside "
                f"primary theme {primary_short}."
            )

        info["is_primary_theme"] = is_prim
        info["needs_manual_review"] = needs_manual
        info["confidence_label"] = conf_label
        info["assignment_reason"] = reason

    return {
        "primary_theme_id": primary_tid,
        "per_theme": per_theme,
    }


def classify_single_review_text(content: str, score: int = 1) -> List[str]:
    """
    Deterministic helper that classifies a single review string using the exact
    same THEME_DEFINITIONS and polarity guard used across all reporting windows.
    """
    clean_txt = str(content or "").strip()
    is_eligible = (int(score) <= 3) or bool(NEGATIVE_CONTRAST_PATTERN.search(clean_txt))
    if not is_eligible:
        return []
    matched: List[str] = []
    for tdef in THEME_DEFINITIONS:
        if re.search(tdef["pattern"], clean_txt, flags=re.IGNORECASE):
            matched.append(tdef["theme_id"])
    return matched


def load_and_classify_snapshot(base_dir: Path, snapshot_id: str = "latest") -> Tuple[pd.DataFrame, Dict[str, Any], Dict[str, Any]]:
    """
    Loads the specified raw snapshot (or 'latest') from data/raw/, deduplicates by reviewId,
    and runs deterministic, polarity-checked classification across all 10 complaint themes.
    """
    raw_dir = base_dir / "data" / "raw"
    if snapshot_id == "latest" or not (raw_dir / f"reviews_raw_{snapshot_id}.jsonl").exists():
        jsonl_path = raw_dir / "reviews_raw_latest.jsonl"
        meta_path = raw_dir / "app_metadata_latest.json"
        manifest_path = raw_dir / "manifest_latest.json"
        resolved_snap_id = "latest"
    else:
        jsonl_path = raw_dir / f"reviews_raw_{snapshot_id}.jsonl"
        meta_path = raw_dir / f"app_metadata_{snapshot_id}.json"
        if not meta_path.exists():
            meta_path = raw_dir / "app_metadata_latest.json"
        manifest_path = raw_dir / f"manifest_{snapshot_id}.json"
        resolved_snap_id = snapshot_id

    records = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    raw_df = pd.DataFrame(records)

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

    df = raw_df.drop_duplicates(subset=["reviewId"], keep="first").copy()
    assert df["reviewId"].is_unique, "Deduplicated review dataframe must have unique reviewId records."

    df["in_cohort_a_unfiltered"] = df["reviewId"].map(lambda x: cohort_map[x]["in_cohort_a_unfiltered"])
    df["in_cohort_b_stratified"] = df["reviewId"].map(lambda x: cohort_map[x]["in_cohort_b_stratified"])
    df["in_multilingual"] = df["reviewId"].map(lambda x: cohort_map[x]["in_multilingual"])
    df["slices_seen"] = df["reviewId"].map(lambda x: "|".join(cohort_map[x]["slices_seen"]))
    df["langs_seen"] = df["reviewId"].map(lambda x: "|".join(cohort_map[x]["langs_seen"]))

    df["at_dt"] = pd.to_datetime(df["at"], errors="coerce")
    df["replied_at_dt"] = pd.to_datetime(df["repliedAt"], errors="coerce")
    df["year_month"] = df["at_dt"].dt.strftime("%Y-%m")
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

    # Polarity guard: 4-5* reviews only match complaint themes if they contain a negative/contrast indicator
    has_neg_contrast = df["content_clean"].str.contains(NEGATIVE_CONTRAST_PATTERN, regex=True)
    complaint_eligible = (df["score"] <= 3) | has_neg_contrast

    theme_cols = []
    for tdef in THEME_DEFINITIONS:
        col = tdef["theme_id"]
        theme_cols.append(col)
        # str.contains returns a single boolean per review (never duplicate keyword match counts)
        raw_match = df["content_clean"].str.contains(tdef["pattern"], case=False, regex=True)
        df[col] = (raw_match & complaint_eligible).astype(bool)

    df["matched_theme_count"] = df[theme_cols].sum(axis=1)
    df["matched_themes_list"] = df.apply(
        lambda r: "|".join([c for c in theme_cols if r[c]]) if r["matched_theme_count"] > 0 else "UNSPECIFIED_OR_GENERIC",
        axis=1,
    )
    df["is_generic_uninformative"] = df["matched_theme_count"] == 0
    df = df.sort_values("at_dt", ascending=False).reset_index(drop=True)

    with open(meta_path, "r", encoding="utf-8") as f:
        app_meta = json.load(f)
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["resolved_snapshot_id"] = resolved_snap_id
    manifest["jsonl_file"] = jsonl_path.name
    manifest["metadata_file"] = meta_path.name
    return df, app_meta, manifest


def compute_date_windows(
    df: pd.DataFrame,
    primary_period_mode: str = "12m",
    trend_comparison_mode: str = "3m",
    custom_start: Optional[str] = None,
    custom_end: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Computes explicit, non-overlapping date boundaries and audits dataset coverage.
    Boundaries are inclusive: [start_date 00:00:00, end_date 23:59:59].
    """
    dataset_min_dt = df["at_dt"].min()
    dataset_max_dt = df["at_dt"].max()

    cohort_a_df = df[df["in_cohort_a_unfiltered"]]
    unfiltered_min_dt = cohort_a_df["at_dt"].min() if len(cohort_a_df) > 0 else dataset_min_dt
    unfiltered_max_dt = cohort_a_df["at_dt"].max() if len(cohort_a_df) > 0 else dataset_max_dt
    five_star_min_dt = df[df["score"] == 5]["at_dt"].min() if len(df[df["score"] == 5]) > 0 else unfiltered_min_dt

    anchor_end_date = dataset_max_dt.normalize()

    mode = str(primary_period_mode).lower().strip()
    if mode == "custom":
        if not custom_start or not custom_end:
            raise ValueError("Custom date range requires both custom_start and custom_end (YYYY-MM-DD).")
        p_start_date = pd.Timestamp(custom_start).normalize()
        p_end_date = pd.Timestamp(custom_end).normalize()
        if p_start_date > p_end_date:
            raise ValueError(f"Start date ({custom_start}) cannot be after end date ({custom_end}).")
        period_label = f"Custom Range ({p_start_date.strftime('%Y-%m-%d')} to {p_end_date.strftime('%Y-%m-%d')})"
    else:
        months_map = {"3m": 3, "6m": 6, "12m": 12}
        m_val = months_map.get(mode, 12)
        p_end_date = anchor_end_date
        p_start_date = (p_end_date - pd.DateOffset(months=m_val) + pd.Timedelta(days=1)).normalize()
        period_label = f"Most Recent {m_val} Months ({p_start_date.strftime('%Y-%m-%d')} to {p_end_date.strftime('%Y-%m-%d')})"

    primary_start = p_start_date
    primary_end = p_end_date + pd.Timedelta(hours=23, minutes=59, seconds=59)
    primary_days = int((p_end_date - p_start_date).days) + 1

    # Trend comparison windows: compare latest M_trend months ending at primary_end
    # against the immediately preceding M_trend months (strictly non-overlapping).
    t_mode = str(trend_comparison_mode).lower().strip()
    trend_months_map = {"1m": 1, "3m": 3, "6m": 6}
    t_months = trend_months_map.get(t_mode, 3)

    recent_end_date = p_end_date
    recent_start_date = (recent_end_date - pd.DateOffset(months=t_months) + pd.Timedelta(days=1)).normalize()
    recent_start = recent_start_date
    recent_end = recent_end_date + pd.Timedelta(hours=23, minutes=59, seconds=59)
    recent_days = int((recent_end_date - recent_start_date).days) + 1

    preceding_end_date = (recent_start_date - pd.Timedelta(days=1)).normalize()
    preceding_start_date = (preceding_end_date - pd.DateOffset(months=t_months) + pd.Timedelta(days=1)).normalize()
    preceding_start = preceding_start_date
    preceding_end = preceding_end_date + pd.Timedelta(hours=23, minutes=59, seconds=59)
    preceding_days = int((preceding_end_date - preceding_start_date).days) + 1

    assert preceding_end < recent_start, "Preceding and Recent windows must never overlap."

    # Coverage & Missing-Interval Audit
    missing_intervals: List[Dict[str, str]] = []
    coverage_warnings: List[str] = []

    ds_min_date = dataset_min_dt.normalize()
    ds_max_date = dataset_max_dt.normalize()
    unf_min_date = unfiltered_min_dt.normalize()
    five_min_date = five_star_min_dt.normalize()

    if p_start_date < ds_min_date:
        gap_end = min(p_end_date, ds_min_date - pd.Timedelta(days=1))
        missing_intervals.append(
            {
                "interval_type": "NO_COLLECTED_DATA_PRIOR_TO_SNAPSHOT",
                "start": p_start_date.strftime("%Y-%m-%d"),
                "end": gap_end.strftime("%Y-%m-%d"),
                "explanation": (
                    f"Earliest review in the stored Play Store snapshot is {ds_min_date.strftime('%Y-%m-%d')}. "
                    f"No reviews exist in the dataset for {p_start_date.strftime('%Y-%m-%d')} to {gap_end.strftime('%Y-%m-%d')}."
                ),
            }
        )
        coverage_warnings.append(
            f"Requested start date ({p_start_date.strftime('%Y-%m-%d')}) precedes the earliest collected review ({ds_min_date.strftime('%Y-%m-%d')})."
        )

    if p_end_date > ds_max_date:
        gap_start = max(p_start_date, ds_max_date + pd.Timedelta(days=1))
        missing_intervals.append(
            {
                "interval_type": "POST_SNAPSHOT_UNCOLLECTED_INTERVAL",
                "start": gap_start.strftime("%Y-%m-%d"),
                "end": p_end_date.strftime("%Y-%m-%d"),
                "explanation": (
                    f"Latest review in the stored Play Store snapshot is {ds_max_date.strftime('%Y-%m-%d')}. "
                    f"Check 'Refresh public Google Play reviews' to fetch newer reviews."
                ),
            }
        )
        coverage_warnings.append(
            f"Requested end date ({p_end_date.strftime('%Y-%m-%d')}) extends past the snapshot ceiling ({ds_max_date.strftime('%Y-%m-%d')})."
        )

    if p_start_date < unf_min_date:
        strat_start = max(p_start_date, ds_min_date)
        strat_end = min(p_end_date, unf_min_date - pd.Timedelta(days=1))
        if strat_start <= strat_end:
            missing_intervals.append(
                {
                    "interval_type": "STRATIFIED_COHORT_B_COVERAGE",
                    "start": strat_start.strftime("%Y-%m-%d"),
                    "end": strat_end.strftime("%Y-%m-%d"),
                    "explanation": (
                        f"Google Play's unfiltered chronological feed (Cohort A) reaches {unf_min_date.strftime('%Y-%m-%d')}. "
                        f"Reviews in {strat_start.strftime('%Y-%m-%d')}..{strat_end.strftime('%Y-%m-%d')} come from rating-stratified (1★–4★) "
                        f"and relevance-sorted slices (5★ reviews reach {five_min_date.strftime('%Y-%m-%d')}), so historical star-rating "
                        f"averages in this interval are incomplete and non-representative."
                    ),
                }
            )
            coverage_warnings.append(
                f"Interval {strat_start.strftime('%Y-%m-%d')} to {strat_end.strftime('%Y-%m-%d')} precedes the unfiltered Cohort A floor "
                f"({unf_min_date.strftime('%Y-%m-%d')}); 5★ reviews are truncated prior to {five_min_date.strftime('%Y-%m-%d')} due to Play Store pagination limits."
            )

    if preceding_start_date < unf_min_date:
        coverage_warnings.append(
            f"Preceding trend comparison window ({preceding_start_date.strftime('%Y-%m-%d')} to {preceding_end_date.strftime('%Y-%m-%d')}) "
            f"extends prior to the unfiltered Cohort A coverage boundary ({unf_min_date.strftime('%Y-%m-%d')})."
        )

    is_fully_covered_unfiltered = (p_start_date >= unf_min_date) and (p_end_date <= ds_max_date)

    return {
        "primary_period_mode": mode,
        "primary_period_label": period_label,
        "trend_comparison_mode": t_mode,
        "trend_months": t_months,
        "timezone": TIMEZONE_LABEL,
        "boundary_convention": "Inclusive start (00:00:00) through Inclusive end (23:59:59); zero overlap between Preceding and Recent windows.",
        "primary_start": p_start_date.strftime("%Y-%m-%d"),
        "primary_end": p_end_date.strftime("%Y-%m-%d"),
        "primary_start_ts": primary_start,
        "primary_end_ts": primary_end,
        "primary_days": primary_days,
        "recent_start": recent_start_date.strftime("%Y-%m-%d"),
        "recent_end": recent_end_date.strftime("%Y-%m-%d"),
        "recent_start_ts": recent_start,
        "recent_end_ts": recent_end,
        "recent_days": recent_days,
        "preceding_start": preceding_start_date.strftime("%Y-%m-%d"),
        "preceding_end": preceding_end_date.strftime("%Y-%m-%d"),
        "preceding_start_ts": preceding_start,
        "preceding_end_ts": preceding_end,
        "preceding_days": preceding_days,
        "dataset_overall_min_date": ds_min_date.strftime("%Y-%m-%d"),
        "dataset_overall_max_date": ds_max_date.strftime("%Y-%m-%d"),
        "unfiltered_complete_min_date": unf_min_date.strftime("%Y-%m-%d"),
        "unfiltered_complete_max_date": ds_max_date.strftime("%Y-%m-%d"),
        "five_star_complete_min_date": five_min_date.strftime("%Y-%m-%d"),
        "is_fully_covered_unfiltered": bool(is_fully_covered_unfiltered),
        "missing_or_partial_intervals": missing_intervals,
        "coverage_warnings": coverage_warnings,
    }


def _star_dist_dict(
    sub: pd.DataFrame,
    label: str,
    window_str: str,
    is_unfiltered_covered: bool = True,
) -> Dict[str, Any]:
    n_total = len(sub)
    counts = sub["score"].value_counts().to_dict() if n_total > 0 else {}
    c1, c2, c3, c4, c5 = [int(counts.get(s, 0)) for s in (1, 2, 3, 4, 5)]
    low_12 = c1 + c2
    pos_45 = c4 + c5
    replies = int(sub["has_developer_reply"].sum()) if n_total > 0 else 0
    low_sub = sub[sub["score"].isin([1, 2])] if n_total > 0 else sub
    low_replies = int(low_sub["has_developer_reply"].sum()) if len(low_sub) > 0 else 0
    actual_min = str(sub["at_dt"].min())[:10] if n_total > 0 else None
    actual_max = str(sub["at_dt"].max())[:10] if n_total > 0 else None

    raw_mean = round(float(sub["score"].mean()), 4) if n_total > 0 else None
    is_representative = bool(is_unfiltered_covered and n_total >= MIN_REPRESENTATIVE_PRIMARY_REVIEWS)

    if n_total == 0:
        mean_display = "No reviews (n=0)"
        representativeness_note = "No reviews collected in this window."
    elif is_representative:
        mean_display = f"{raw_mean:.2f}★ (n={n_total:,})"
        representativeness_note = "Representative of collected written reviews in complete unfiltered window."
    else:
        reason_tag = "sparse sample" if n_total < MIN_REPRESENTATIVE_PRIMARY_REVIEWS else "rating-stratified historical bias"
        mean_display = f"Non-Repr. ({raw_mean:.2f}★ unadjusted, n={n_total:,} — {reason_tag})"
        representativeness_note = (
            f"Non-representative sample (n={n_total:,}; {reason_tag}). "
            f"Do not treat {raw_mean:.2f}★ as a representative population average."
        )

    return {
        "cohort_label": label,
        "date_window": window_str,
        "actual_min_date": actual_min,
        "actual_max_date": actual_max,
        "n_reviews": n_total,
        "sample_mean_rating": raw_mean,
        "is_representative": is_representative,
        "mean_rating_display": mean_display,
        "representativeness_note": representativeness_note,
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
        "count_positive_4_5_star": pos_45,
        "pct_positive_4_5_star": round(pos_45 / n_total * 100, 2) if n_total > 0 else 0.0,
        "dev_reply_count_all": replies,
        "dev_reply_rate_all_pct": round(replies / n_total * 100, 2) if n_total > 0 else 0.0,
        "dev_reply_count_1_2_star": low_replies,
        "dev_reply_rate_1_2_star_pct": round(low_replies / low_12 * 100, 2) if low_12 > 0 else 0.0,
    }


def score_frequency_with_safeguards(pct_of_focus: float, count_focus: int) -> int:
    """
    Computes 1..5 Frequency score with minimum evidence safeguards so a single
    review in a 2-review window (1/2 = 50%) is never scored as a 5/5 high-frequency issue.
    Returns 0 when count_focus == 0.
    """
    if count_focus <= 0:
        return 0
    raw_f = score_frequency_1_to_5(pct_of_focus)
    if count_focus == 1:
        return 1
    if count_focus == 2:
        return min(raw_f, 2)
    if count_focus < 5:
        return min(raw_f, 3)
    if count_focus < 10:
        return min(raw_f, 4)
    return raw_f


def score_classification_and_coverage_confidence_1_to_5(
    cnt_focus: int,
    thumbs_sum: int,
    avg_words: float,
    verified_match_cnt: int,
    verified_primary_cnt: int,
    manual_review_cnt: int,
    is_representative: bool,
) -> int:
    """
    Computes 1..5 Confidence in review classification and data coverage (C_score):
      - Evaluates sample size of matching reviews, thumbs-up corroboration, word depth, and verified classification ratio.
      - Penalizes themes that have zero primary matches or high manual-review flags.
      - Caps confidence at <= 2 when the window sample is incomplete/non-representative or cnt_focus < 3.
    """
    if cnt_focus <= 0:
        return 0
    c_val = int(score_evidence_strength_1_to_5(cnt_focus, thumbs_sum, avg_words))
    if verified_primary_cnt == 0 and manual_review_cnt > 0:
        c_val = max(1, c_val - 1)
    if not is_representative or cnt_focus < MIN_CONFIRMED_THEME_REVIEWS:
        c_val = min(c_val, 2)
    return int(c_val)


def evaluate_trend_with_safeguards(
    cnt_pre: int,
    n_pre: int,
    cnt_rec: int,
    n_rec: int,
    min_window_n: int = MIN_COMPARISON_WINDOW_REVIEWS,
    min_theme_matching_per_window: int = MIN_THEME_MATCHING_PER_WINDOW,
) -> Dict[str, Any]:
    """
    Evaluates Recent vs. Preceding complaint rate change with strict sample-size safeguards:
      - Rate in each window = matching_reviews / window_denominator * 100.0
      - Percentage-point change (delta_pp) = round(rate_rec - rate_pre, 2)
      - If n_pre == 0: returns status "NO_BASELINE_AVAILABLE" ("No baseline available")
      - If n_rec == 0 or n_pre < min_window_n or n_rec < min_window_n:
        returns status "INSUFFICIENT_EVIDENCE" ("Insufficient evidence")
      - If cnt_pre == 0 and cnt_rec == 0:
        returns status "NO_MATCHING_REVIEWS" ("No matching reviews")
      - If cnt_pre < min_theme_matching_per_window or cnt_rec < min_theme_matching_per_window:
        returns status "INSUFFICIENT_EVIDENCE" ("Insufficient evidence") and caps T_score at 3 (neutral)
        so tiny theme samples never inflate trend scores or rank as confident surges.
    """
    rate_pre = round((cnt_pre / n_pre * 100.0), 2) if n_pre > 0 else 0.0
    rate_rec = round((cnt_rec / n_rec * 100.0), 2) if n_rec > 0 else 0.0
    delta_pp = round(rate_rec - rate_pre, 2)
    rel_change = (
        round((rate_rec - rate_pre) / rate_pre * 100.0, 1)
        if rate_pre > 0
        else (100.0 if rate_rec > 0 else 0.0)
    )

    # 1. Missing or zero baseline denominator
    if n_pre == 0:
        rec_part = f"Rec: {cnt_rec}/{n_rec}" if n_rec > 0 else "Rec n=0"
        return {
            "trend_status": "NO_BASELINE_AVAILABLE",
            "trend_confidence": "No Baseline Available",
            "is_meaningful_increase": False,
            "is_valid_comparison": False,
            "rate_pre_pct": None,
            "rate_rec_pct": rate_rec if n_rec > 0 else None,
            "delta_pp": None,
            "rel_change_pct": None,
            "T_score_1_to_5": 3,
            "trend_display": f"No baseline available (Pre n=0, {rec_part}; min n≥{min_window_n})",
            "trend_short_display": f"No baseline available (Pre n=0, {rec_part})",
        }

    if n_rec == 0:
        return {
            "trend_status": "INSUFFICIENT_EVIDENCE",
            "trend_confidence": "Insufficient Evidence",
            "is_meaningful_increase": False,
            "is_valid_comparison": False,
            "rate_pre_pct": rate_pre,
            "rate_rec_pct": None,
            "delta_pp": None,
            "rel_change_pct": None,
            "T_score_1_to_5": 3,
            "trend_display": f"Insufficient evidence (Pre: {cnt_pre}/{n_pre}, Rec n=0; min n≥{min_window_n})",
            "trend_short_display": f"Insufficient evidence (Pre {cnt_pre}/{n_pre}, Rec n=0)",
        }

    # 2. Overall comparison window sample below minimum threshold (n < 10)
    if n_pre < min_window_n or n_rec < min_window_n:
        return {
            "trend_status": "INSUFFICIENT_EVIDENCE",
            "trend_confidence": "Insufficient Evidence",
            "is_meaningful_increase": False,
            "is_valid_comparison": False,
            "rate_pre_pct": rate_pre,
            "rate_rec_pct": rate_rec,
            "delta_pp": delta_pp,
            "rel_change_pct": rel_change,
            "T_score_1_to_5": 3,
            "trend_display": f"Insufficient evidence (Pre: {cnt_pre}/{n_pre}, Rec: {cnt_rec}/{n_rec}; min n≥{min_window_n})",
            "trend_short_display": f"Insufficient evidence (Pre n={n_pre}, Rec n={n_rec})",
        }

    # 3. Zero matching reviews in both comparison windows
    if cnt_pre == 0 and cnt_rec == 0:
        return {
            "trend_status": "NO_MATCHING_REVIEWS",
            "trend_confidence": "No Matching Reviews",
            "is_meaningful_increase": False,
            "is_valid_comparison": False,
            "rate_pre_pct": 0.0,
            "rate_rec_pct": 0.0,
            "delta_pp": 0.0,
            "rel_change_pct": 0.0,
            "T_score_1_to_5": 3,
            "trend_display": f"No matching reviews (Pre: 0/{n_pre} [0.0%] → Rec: 0/{n_rec} [0.0%])",
            "trend_short_display": f"No matching reviews (0/{n_pre} → 0/{n_rec})",
        }

    # 4. Theme matching count below provisional threshold (< 10 matching reviews in either window)
    if cnt_pre < min_theme_matching_per_window or cnt_rec < min_theme_matching_per_window:
        return {
            "trend_status": "INSUFFICIENT_EVIDENCE",
            "trend_confidence": f"Insufficient Evidence (<{min_theme_matching_per_window} matches/window)",
            "is_meaningful_increase": False,
            "is_valid_comparison": False,
            "rate_pre_pct": rate_pre,
            "rate_rec_pct": rate_rec,
            "delta_pp": delta_pp,
            "rel_change_pct": rel_change,
            "T_score_1_to_5": 3,
            "trend_display": (
                f"Insufficient evidence ({cnt_pre}/{n_pre} [{rate_pre:.1f}%] → {cnt_rec}/{n_rec} [{rate_rec:.1f}%]; "
                f"<{min_theme_matching_per_window} matches/window)"
            ),
            "trend_short_display": f"Insufficient evidence ({cnt_pre}/{n_pre} → {cnt_rec}/{n_rec})",
        }

    # 5. Sufficient sample in both comparison windows (cnt_pre >= 10 and cnt_rec >= 10)
    t_score = score_trend_1_to_5(delta_pp, rel_change, cnt_rec)
    conf = "High Confidence" if (n_pre >= 30 and n_rec >= 30 and (cnt_pre + cnt_rec) >= 25) else "Moderate Confidence"
    return {
        "trend_status": "VALID",
        "trend_confidence": conf,
        "is_meaningful_increase": bool(delta_pp > 0.5 and cnt_rec >= min_theme_matching_per_window),
        "is_valid_comparison": True,
        "rate_pre_pct": rate_pre,
        "rate_rec_pct": rate_rec,
        "delta_pp": delta_pp,
        "rel_change_pct": rel_change,
        "T_score_1_to_5": t_score,
        "trend_display": f"{delta_pp:+.2f} pp (Pre: {rate_pre:.2f}% [{cnt_pre}/{n_pre}] → Rec: {rate_rec:.2f}% [{cnt_rec}/{n_rec}])",
        "trend_short_display": f"{delta_pp:+.2f} pp ({cnt_pre}/{n_pre} → {cnt_rec}/{n_rec})",
    }


def _fig_to_base64_and_file(fig: plt.Figure, out_path: Optional[Path] = None) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=220, bbox_inches="tight")
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(buf.getvalue())
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def fmt_date_short(date_str: str) -> str:
    """Formats '2025-10-12' -> '12 Oct 2025'."""
    try:
        d = dt.datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
        return d.strftime("%d %b %Y")
    except Exception:
        return str(date_str)


def fmt_ym_short(ym_str: str) -> str:
    """Formats '2025-10' -> 'Oct \\'25'."""
    try:
        d = dt.datetime.strptime(str(ym_str)[:7], "%Y-%m")
        return d.strftime("%b '%y")
    except Exception:
        return str(ym_str)


def render_dynamic_charts(
    store_meta: Dict[str, Any],
    dist_primary: Dict[str, Any],
    dist_recent: Dict[str, Any],
    dist_preceding: Dict[str, Any],
    monthly_rows: List[Dict[str, Any]],
    theme_rows: List[Dict[str, Any]],
    win_info: Dict[str, Any],
    review_focus: str,
    fig_dir: Optional[Path] = None,
) -> Dict[str, str]:
    """
    Generates 5 clean, uncluttered Matplotlib charts that propagate sample sizes (k/n),
    minimum-evidence trend safeguards, and historical coverage warnings.
    """
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial", "Segoe UI"]
    plt.rcParams["axes.edgecolor"] = "#CBD5E1"
    plt.rcParams["axes.linewidth"] = 0.8

    charts: Dict[str, str] = {}
    p_range_str = f"{fmt_date_short(win_info['primary_start'])} – {fmt_date_short(win_info['primary_end'])}"
    n_prim_all = dist_primary["n_reviews"]
    n_prim_low = dist_primary["count_low_1_2_star"]
    is_rep = dist_primary["is_representative"]
    cov_tag = "" if is_rep else f" [Incomplete/Biased Sample: n={n_prim_all}]"

    # -------------------------------------------------------------------------
    # Chart 1: Star Rating Distribution (Store Baseline vs. Selected Period)
    # -------------------------------------------------------------------------
    hist = store_meta["histogram_1_to_5"]
    hist_sum = store_meta["histogram_sum"]
    store_pcts = [round(h / hist_sum * 100.0, 1) for h in hist]
    prim_pcts = [round(dist_primary[f"pct_{s}_star"], 1) for s in range(1, 6)]

    fig, ax = plt.subplots(figsize=(9.2, 4.3))
    x = np.arange(5)
    w = 0.34

    b1 = ax.bar(
        x - w / 2,
        store_pcts,
        w,
        label=f"Official Store Baseline ({store_meta['exact_unrounded_score']:.2f}★ | n={hist_sum:,})",
        color="#1E3A8A",
        edgecolor="#172554",
        linewidth=0.6,
    )
    sample_lbl = (
        f"Selected Period Sample ({dist_primary['sample_mean_rating'] or 0:.2f}★ | n={n_prim_all:,})"
        if is_rep
        else f"Selected Period Sample (Non-Repr. Bias | n={n_prim_all:,} reviews)"
    )
    b2 = ax.bar(
        x + w / 2,
        prim_pcts,
        w,
        label=sample_lbl,
        color="#3B82F6" if is_rep else "#F59E0B",
        edgecolor="#1D4ED8" if is_rep else "#B45309",
        linewidth=0.6,
    )

    ax.set_xticks(x)
    ax.set_xticklabels(["1 ★", "2 ★", "3 ★", "4 ★", "5 ★"], fontsize=10, fontweight="bold")
    ax.set_ylabel("Share of Ratings (%)", fontsize=9.5, fontweight="bold", color="#1E293B")
    ax.set_ylim(0, 99)
    ax.set_title(
        f"Star Rating Distribution ({p_range_str} | n={n_prim_all:,}){cov_tag}",
        fontsize=10.5,
        fontweight="bold",
        color="#0F172A" if is_rep else "#92400E",
        pad=10,
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend(loc="upper left", fontsize=8.5, frameon=True, facecolor="#F8FAFC", edgecolor="#CBD5E1")

    for bars, col in [(b1, "#1E3A8A"), (b2, "#1D4ED8" if is_rep else "#B45309")]:
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                ax.annotate(
                    f"{h:.1f}%",
                    xy=(bar.get_x() + bar.get_width() / 2, h),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                    fontweight="bold",
                    color=col,
                )

    if not is_rep:
        ax.text(
            0.38,
            0.65,
            f"Coverage Limitation: Incomplete/stratified sample (n={n_prim_all:,}).\n"
            f"Do not treat sample mean ({dist_primary['sample_mean_rating'] or 0:.2f}★) as representative.",
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=8,
            fontweight="bold",
            color="#92400E",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#FFFBEB", edgecolor="#F59E0B"),
        )

    charts["chart_01_distribution"] = _fig_to_base64_and_file(
        fig, fig_dir / "01_rating_distribution_comparison.png" if fig_dir else None
    )

    # -------------------------------------------------------------------------
    # Chart 2: Monthly Trend (Abbreviated Month Names, Clean Line & Bars)
    # -------------------------------------------------------------------------
    fig, ax1 = plt.subplots(figsize=(9.2, 4.3))
    if len(monthly_rows) > 0:
        m_df = pd.DataFrame(monthly_rows)
        xm = np.arange(len(m_df))
        month_labels = [fmt_ym_short(ym) for ym in m_df["year_month"]]

        ax1.bar(xm, m_df["n_reviews"], color="#DBEAFE", edgecolor="#93C5FD", width=0.52, label="Review Volume (n)")
        ax1.set_ylabel("Monthly Review Count (n)", color="#1E40AF", fontsize=9.5, fontweight="bold")
        ax1.set_xticks(xm)
        ax1.set_xticklabels(month_labels, rotation=25, ha="right", fontsize=8.5, fontweight="bold")
        ax1.set_ylim(0, max(int(m_df["n_reviews"].max() * 1.35), 10))
        ax1.spines["top"].set_visible(False)

        ax2 = ax1.twinx()
        ax2.plot(xm, m_df["pct_1_2_star"], color="#E11D48", marker="o", markersize=5.5, linewidth=2.2, label="Low-Star (1–2★) Share %")
        ax2.set_ylabel("Low-Star (1–2★) Share (%)", color="#BE123C", fontsize=9.5, fontweight="bold")
        ax2.set_ylim(0, max(float(m_df["pct_1_2_star"].max()) * 1.38, 55.0))
        ax2.spines["top"].set_visible(False)

        step = 1 if len(m_df) <= 14 else 2
        for idx in range(0, len(m_df), step):
            val = float(m_df.iloc[idx]["pct_1_2_star"])
            c12 = int(m_df.iloc[idx]["count_1_2_star"])
            nm = int(m_df.iloc[idx]["n_reviews"])
            lbl = f"{val:.0f}% ({c12}/{nm})" if len(m_df) <= 6 else f"{val:.0f}%"
            ax2.annotate(
                lbl,
                (idx, val),
                xytext=(0, 6),
                textcoords="offset points",
                ha="center",
                fontsize=8,
                color="#9F1239",
                fontweight="bold",
            )
    else:
        ax1.text(0.5, 0.5, "No reviews in selected period (n=0)", ha="center", va="center", fontsize=11)

    ax1.set_title(
        f"Monthly Review Volume & Low-Star Share ({p_range_str} | N={n_prim_all:,}){cov_tag}",
        fontsize=10.5,
        fontweight="bold",
        color="#0F172A" if is_rep else "#92400E",
        pad=10,
    )
    ax1.grid(axis="y", linestyle="--", alpha=0.35)
    charts["chart_02_monthly_trend"] = _fig_to_base64_and_file(
        fig, fig_dir / "02_monthly_rating_and_complaint_trend.png" if fig_dir else None
    )

    # -------------------------------------------------------------------------
    # Chart 3: Top Complaint Themes in Selected Period (Only Themes with Count > 0)
    # -------------------------------------------------------------------------
    t_df = pd.DataFrame(theme_rows)
    rate_col = "pct_of_all_reviews_primary" if review_focus == "all" else "pct_of_1_2_star_primary"
    cnt_col = "count_all_reviews_primary" if review_focus == "all" else "count_1_2_star_primary"
    denom_n = n_prim_all if review_focus == "all" else n_prim_low
    focus_lbl = f"All Reviews (n={denom_n:,})" if review_focus == "all" else f"Low-Star 1–2★ Reviews (n={denom_n:,})"

    t_pos = (
        t_df[(t_df[cnt_col] > 0) & (t_df["evidence_status"] != "SECONDARY_MULTILABEL_ONLY")]
        .sort_values(cnt_col, ascending=False)
        .head(5)
        if len(t_df) > 0
        else pd.DataFrame()
    )
    fig, ax = plt.subplots(figsize=(9.2, 4.1))
    if len(t_pos) > 0:
        top5_vol = t_pos.iloc[::-1].reset_index(drop=True)
        y_pos = np.arange(len(top5_vol))
        bar_colors = ["#2563EB", "#3B82F6", "#F97316", "#EA580C", "#E11D48"][-len(top5_vol):]

        bars = ax.barh(y_pos, top5_vol[rate_col], color=bar_colors, height=0.54, alpha=0.92)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(
            [SHORT_THEME_NAMES.get(r["theme_id"], r["theme_name"]) for _, r in top5_vol.iterrows()],
            fontsize=9.5,
            fontweight="bold",
            color="#1E293B",
        )
        zero_cnt = int((t_df[cnt_col] == 0).sum())
        zero_note = f" | {zero_cnt} theme(s) had 0 matching reviews" if zero_cnt > 0 else ""
        ax.set_xlabel(f"Share of {focus_lbl} (%){zero_note}", fontsize=9, fontweight="bold", color="#1E293B")
        max_x = max(float(top5_vol[rate_col].max()) * 1.28, 12.0)
        ax.set_xlim(0, max_x)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        for idx, bar in enumerate(bars):
            row = top5_vol.iloc[idx]
            w_val = bar.get_width()
            ax.text(
                w_val + max_x * 0.018,
                bar.get_y() + bar.get_height() / 2,
                f"{w_val:.1f}% ({int(row[cnt_col])}/{denom_n})",
                va="center",
                ha="left",
                fontsize=9,
                fontweight="bold",
                color="#0F172A",
            )

        title_prefix = f"Observed Complaint Themes ({len(t_pos)} with Evidence)" if len(t_pos) < 5 else "Top 5 Complaint Themes"
        ax.set_title(
            f"{title_prefix} ({p_range_str} | n={denom_n:,})",
            fontsize=10.5,
            fontweight="bold",
            color="#0F172A",
            pad=10,
        )
        ax.grid(axis="x", linestyle="--", alpha=0.35)
    else:
        ax.axis("off")
        ax.text(
            0.5,
            0.5,
            f"No direct review evidence in this period ({p_range_str} | n={denom_n} reviews).\n"
            f"0 complaint themes matched in the selected sample.",
            ha="center",
            va="center",
            fontsize=10.5,
            fontweight="bold",
            color="#475569",
            bbox=dict(boxstyle="round,pad=0.6", facecolor="#F8FAFC", edgecolor="#CBD5E1"),
        )

    charts["chart_03_themes_primary"] = _fig_to_base64_and_file(
        fig, fig_dir / "03_complaint_themes_primary_window.png" if fig_dir else None
    )

    # -------------------------------------------------------------------------
    # Chart 4: Validated Complaint Trends (Enforcing n >= 10 matching per window)
    # -------------------------------------------------------------------------
    n_comp_pre = dist_preceding["n_reviews"] if review_focus == "all" else dist_preceding["count_low_1_2_star"]
    n_comp_rec = dist_recent["n_reviews"] if review_focus == "all" else dist_recent["count_low_1_2_star"]
    has_trend_safeguard = (n_comp_pre >= MIN_COMPARISON_WINDOW_REVIEWS) and (n_comp_rec >= MIN_COMPARISON_WINDOW_REVIEWS)

    delta_col = "delta_all_pp" if review_focus == "all" else "delta_1_2_star_pp"
    pre_cnt_col = "count_all_preceding" if review_focus == "all" else "count_1_2_star_preceding"
    rec_cnt_col = "count_all_recent" if review_focus == "all" else "count_1_2_star_recent"

    valid_trend_df = (
        t_df[t_df["trend_status"] == "VALID"].sort_values(delta_col, ascending=False).head(5)
        if (len(t_df) > 0 and has_trend_safeguard)
        else pd.DataFrame()
    )

    fig, ax = plt.subplots(figsize=(9.2, 4.1))
    if has_trend_safeguard and len(valid_trend_df) > 0:
        top5_delta = valid_trend_df.iloc[::-1].reset_index(drop=True)
        yd = np.arange(len(top5_delta))
        d_vals = [float(v or 0.0) for v in top5_delta[delta_col].values]
        d_colors = ["#E11D48" if v > 0 else "#10B981" for v in d_vals]

        ax.barh(yd, d_vals, height=0.54, color=d_colors, alpha=0.92)
        ax.axvline(0, color="#334155", linewidth=1.0)
        ax.set_yticks(yd)
        ax.set_yticklabels(
            [SHORT_THEME_NAMES.get(r["theme_id"], r["theme_name"]) for _, r in top5_delta.iterrows()],
            fontsize=9.5,
            fontweight="bold",
            color="#1E293B",
        )
        min_d = min(float(np.min(d_vals)), 0.0)
        max_d = max(float(np.max(d_vals)), 1.0)
        span = max(max_d - min_d, 4.0)
        ax.set_xlim(min_d - span * 0.34 if min_d < 0 else 0, max_d + span * 0.36)
        ax.set_xlabel(
            f"Percentage-Point Change (pp | Pre n={n_comp_pre:,} vs. Rec n={n_comp_rec:,}; min {MIN_THEME_MATCHING_PER_WINDOW}/win)",
            fontsize=9,
            fontweight="bold",
            color="#1E293B",
        )
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="x", linestyle="--", alpha=0.35)

        for idx, (_, r) in enumerate(top5_delta.iterrows()):
            dv = float(r[delta_col] or 0.0)
            c_pre = int(r[pre_cnt_col])
            c_rec = int(r[rec_cnt_col])
            off = span * 0.02 if dv >= 0 else -span * 0.02
            ha_align = "left" if dv >= 0 else "right"
            ax.text(
                dv + off,
                yd[idx],
                f"{dv:+.2f} pp ({c_pre}/{n_comp_pre} → {c_rec}/{n_comp_rec})",
                va="center",
                ha=ha_align,
                fontsize=8.5,
                fontweight="bold",
                color="#9F1239" if dv >= 0 else "#065F46",
            )

        ax.set_title(
            f"Validated Recent vs. Preceding Trend Shifts (Pre n={n_comp_pre:,} vs. Rec n={n_comp_rec:,})",
            fontsize=10.5,
            fontweight="bold",
            color="#0F172A",
            pad=10,
        )
    else:
        ax.axis("off")
        ax.set_title(
            "Recent vs. Preceding Trend Comparison — Minimum-Evidence Safeguard",
            fontsize=10.5,
            fontweight="bold",
            color="#92400E",
            pad=10,
        )
        status_hdr = "NO BASELINE AVAILABLE" if n_comp_pre == 0 else "TREND RANKING SUPPRESSED: INSUFFICIENT EVIDENCE"
        msg_lines = [
            status_hdr,
            "",
            f"• Preceding Window ({win_info['preceding_start_fmt']} – {win_info['preceding_end_fmt']}): n = {n_comp_pre} relevant reviews",
            f"• Recent Window ({win_info['recent_start_fmt']} – {win_info['recent_end_fmt']}): n = {n_comp_rec} relevant reviews",
            f"• Provisional Threshold: n ≥ {MIN_THEME_MATCHING_PER_WINDOW} matching reviews per comparison window required.",
            "",
            "Why: Computing percentage-point shifts from zero baselines or <10 matching reviews",
            "produces statistically unreliable spikes. See table for exact k/n counts and status labels.",
        ]
        ax.text(
            0.5,
            0.5,
            "\n".join(msg_lines),
            ha="center",
            va="center",
            fontsize=9,
            color="#78350F",
            bbox=dict(boxstyle="round,pad=0.7", facecolor="#FFFBEB", edgecolor="#F59E0B", linewidth=1.4),
        )

    charts["chart_04_trend_deltas"] = _fig_to_base64_and_file(
        fig, fig_dir / "04_recent_90d_vs_prior_90d_deltas.png" if fig_dir else None
    )

    # -------------------------------------------------------------------------
    # Chart 5: Evidence-Backed Priority Recommendations (Excludes 0-Review Themes)
    # -------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(9.4, 4.2))
    ev_df = (
        t_df[(t_df["has_direct_evidence"] == True) & (t_df["evidence_status"] != "SECONDARY_MULTILABEL_ONLY")].copy()
        if len(t_df) > 0 and "has_direct_evidence" in t_df.columns
        else pd.DataFrame()
    )
    if len(ev_df) > 0:
        top6_p = ev_df.head(6).iloc[::-1].reset_index(drop=True)
        yp = np.arange(len(top6_p))
        scores = [float(s or 0.0) for s in top6_p["priority_score_1_to_5"].values]
        bar_cols = []
        for _, r in top6_p.iterrows():
            if r["recommendation_category"] == "SAFETY_ESCALATION":
                bar_cols.append("#7C3AED")
            elif r["evidence_status"] == "PRELIMINARY_LOW_SAMPLE":
                bar_cols.append("#D97706")
            elif float(r["priority_score_1_to_5"] or 0) >= 3.8:
                bar_cols.append("#E11D48")
            else:
                bar_cols.append("#2563EB")

        bars = ax.barh(yp, scores, height=0.54, color=bar_cols, alpha=0.92)
        ax.set_yticks(yp)
        ax.set_yticklabels(
            [
                f"{r['priority_rank']}: {SHORT_THEME_NAMES.get(r['theme_id'], r['theme_name'])}"
                for _, r in top6_p.iterrows()
            ],
            fontsize=9.5,
            fontweight="bold",
            color="#1E293B",
        )
        ax.set_xlim(0, 5.85)
        ax.set_xticks([0, 1, 2, 3, 4, 5])
        ax.set_xlabel("Validated Priority Score (1.0 – 5.0 Scale)", fontsize=9.5, fontweight="bold", color="#1E293B")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="x", linestyle="--", alpha=0.35)

        for idx, bar in enumerate(bars):
            row = top6_p.iloc[idx]
            sc = float(scores[idx])
            cnt_v = int(row[cnt_col])
            ax.text(
                sc + 0.08,
                bar.get_y() + bar.get_height() / 2,
                f"{sc:.2f} / 5.0 (n={cnt_v}/{denom_n})",
                va="center",
                ha="left",
                fontsize=8.5,
                fontweight="bold",
                color="#0F172A",
            )

        chart5_title = (
            f"Top Evidence-Backed Priority Recommendations ({p_range_str} | n={denom_n:,})"
            if denom_n >= MIN_SUFFICIENT_PRIMARY_LOW_REVIEWS
            else f"Preliminary Observations Only — Low Sample ({p_range_str} | n={denom_n} reviews)"
        )
        ax.set_title(
            chart5_title,
            fontsize=10.5,
            fontweight="bold",
            color="#0F172A" if denom_n >= MIN_SUFFICIENT_PRIMARY_LOW_REVIEWS else "#92400E",
            pad=10,
        )
    else:
        ax.axis("off")
        ax.text(
            0.5,
            0.5,
            f"No confirmed complaint priorities in {p_range_str} (0 matching reviews).\n"
            f"Themes without direct review evidence are not ranked.",
            ha="center",
            va="center",
            fontsize=10.5,
            fontweight="bold",
            color="#475569",
        )

    charts["chart_05_priority_matrix"] = _fig_to_base64_and_file(
        fig, fig_dir / "05_prioritization_matrix.png" if fig_dir else None
    )

    return charts


def generate_dynamic_report(
    base_dir: Path,
    primary_period_mode: str = "12m",
    trend_comparison_mode: str = "3m",
    review_focus: str = "negative",
    refresh_reviews: bool = False,
    custom_start: Optional[str] = None,
    custom_end: Optional[str] = None,
    snapshot_id: str = "latest",
    save_artifacts: bool = True,
    min_comparison_reviews: int = MIN_COMPARISON_WINDOW_REVIEWS,
    min_theme_matching_per_window: int = MIN_THEME_MATCHING_PER_WINDOW,
) -> Dict[str, Any]:
    """
    Executes the complete dynamic analysis in a single shared layer for the selected parameters,
    enforcing mathematical consistency across primary-window counts, trend evaluations,
    priority rankings, 7-part recommendations, executive summaries, and HTML/PDF exports.
    """
    refresh_status = {"requested": bool(refresh_reviews), "executed": False, "new_run_id": None, "error": None}
    if refresh_reviews:
        try:
            col_manifest = run_collection(base_dir)
            refresh_status["executed"] = True
            refresh_status["new_run_id"] = col_manifest.get("run_id")
            snapshot_id = "latest"
        except Exception as exc:
            refresh_status["error"] = f"Live Google Play collection failed ({exc}); fell back to stored snapshot '{snapshot_id}'."

    df, app_meta, manifest = load_and_classify_snapshot(base_dir, snapshot_id=snapshot_id)
    win_info = compute_date_windows(
        df=df,
        primary_period_mode=primary_period_mode,
        trend_comparison_mode=trend_comparison_mode,
        custom_start=custom_start,
        custom_end=custom_end,
    )

    review_focus_norm = "all" if str(review_focus).lower().strip() == "all" else "negative"

    # Filter strictly by explicit timestamps (never silently substitute older reviews)
    df_primary = df[(df["at_dt"] >= win_info["primary_start_ts"]) & (df["at_dt"] <= win_info["primary_end_ts"])].copy()
    df_recent = df[(df["at_dt"] >= win_info["recent_start_ts"]) & (df["at_dt"] <= win_info["recent_end_ts"])].copy()
    df_preceding = df[(df["at_dt"] >= win_info["preceding_start_ts"]) & (df["at_dt"] <= win_info["preceding_end_ts"])].copy()
    df_historical_outside = df[df["at_dt"] < win_info["primary_start_ts"]].copy()

    # Validate unique reviewId records in every filtered window
    assert df_primary["reviewId"].is_unique, "Primary window reviews must be deduplicated by reviewId."
    assert df_recent["reviewId"].is_unique, "Recent window reviews must be deduplicated by reviewId."
    assert df_preceding["reviewId"].is_unique, "Preceding window reviews must be deduplicated by reviewId."

    # Pre-compute review-level theme verification & primary theme assignment inside df_primary
    theme_cols = [t["theme_id"] for t in THEME_DEFINITIONS]
    review_audit_map: Dict[str, Dict[str, Any]] = {}
    for _, row in df_primary.iterrows():
        rid = str(row["reviewId"])
        m_tids = [c for c in theme_cols if bool(row[c])]
        review_audit_map[rid] = inspect_review_theme_assignments(
            content=str(row["content_clean"]),
            score=int(row["score"]),
            word_count=int(row["word_count"]),
            matched_theme_ids=m_tids,
        )

    for ts_key in [
        "primary_start_ts",
        "primary_end_ts",
        "recent_start_ts",
        "recent_end_ts",
        "preceding_start_ts",
        "preceding_end_ts",
    ]:
        win_info[ts_key] = win_info[ts_key].strftime("%Y-%m-%d %H:%M:%S")

    win_info["primary_start_fmt"] = fmt_date_short(win_info["primary_start"])
    win_info["primary_end_fmt"] = fmt_date_short(win_info["primary_end"])
    win_info["recent_start_fmt"] = fmt_date_short(win_info["recent_start"])
    win_info["recent_end_fmt"] = fmt_date_short(win_info["recent_end"])
    win_info["preceding_start_fmt"] = fmt_date_short(win_info["preceding_start"])
    win_info["preceding_end_fmt"] = fmt_date_short(win_info["preceding_end"])

    low_primary = df_primary[df_primary["score"].isin([1, 2])].copy()
    low_recent = df_recent[df_recent["score"].isin([1, 2])].copy()
    low_preceding = df_preceding[df_preceding["score"].isin([1, 2])].copy()

    unf_min_str = win_info["unfiltered_complete_min_date"]
    rec_is_unfiltered = win_info["recent_start"] >= unf_min_str
    pre_is_unfiltered = win_info["preceding_start"] >= unf_min_str

    q_end_str = (pd.Timestamp(win_info["primary_start"]) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    dist_primary = _star_dist_dict(
        df_primary,
        f"Selected Primary Window ({win_info['primary_period_label']})",
        f"{win_info['primary_start_fmt']} – {win_info['primary_end_fmt']}",
        is_unfiltered_covered=win_info["is_fully_covered_unfiltered"],
    )
    dist_recent = _star_dist_dict(
        df_recent,
        "Recent Comparison Window",
        f"{win_info['recent_start_fmt']} – {win_info['recent_end_fmt']}",
        is_unfiltered_covered=rec_is_unfiltered,
    )
    dist_preceding = _star_dist_dict(
        df_preceding,
        "Preceding Comparison Window",
        f"{win_info['preceding_start_fmt']} – {win_info['preceding_end_fmt']}",
        is_unfiltered_covered=pre_is_unfiltered,
    )
    dist_quarantined = _star_dist_dict(
        df_historical_outside,
        f"Older Reviews (Prior to {win_info['primary_start_fmt']}, Excluded)",
        f"{fmt_date_short(win_info['dataset_overall_min_date'])} – {fmt_date_short(q_end_str)}",
        is_unfiltered_covered=False,
    )

    win_info["is_sample_representative"] = dist_primary["is_representative"]

    # Monthly trend inside selected primary window
    monthly_rows: List[Dict[str, Any]] = []
    for ym, grp in df_primary.groupby("year_month"):
        n_m = len(grp)
        c12 = int(grp["score"].isin([1, 2]).sum())
        c1 = int((grp["score"] == 1).sum())
        c5 = int((grp["score"] == 5).sum())
        replies_m = int(grp["has_developer_reply"].sum())
        monthly_rows.append(
            {
                "year_month": str(ym),
                "month_label": fmt_ym_short(str(ym)),
                "n_reviews": n_m,
                "mean_rating": round(float(grp["score"].mean()), 3) if n_m > 0 else 0.0,
                "count_1_star": c1,
                "count_1_2_star": c12,
                "count_5_star": c5,
                "pct_1_2_star": round(c12 / n_m * 100.0, 2) if n_m > 0 else 0.0,
                "pct_5_star": round(c5 / n_m * 100.0, 2) if n_m > 0 else 0.0,
                "dev_reply_count": replies_m,
                "dev_reply_rate_pct": round(replies_m / n_m * 100.0, 2) if n_m > 0 else 0.0,
            }
        )
    monthly_rows = sorted(monthly_rows, key=lambda x: x["year_month"])

    # Theme calculations & dynamic evidence-guarded prioritization
    n_low_p = len(low_primary)
    n_all_p = len(df_primary)
    n_low_rec = len(low_recent)
    n_all_rec = len(df_recent)
    n_low_pre = len(low_preceding)
    n_all_pre = len(df_preceding)

    assert n_low_p == dist_primary["count_low_1_2_star"], "Primary low-star denominator mismatch."
    assert n_low_rec == dist_recent["count_low_1_2_star"], "Recent low-star denominator mismatch."
    assert n_low_pre == dist_preceding["count_low_1_2_star"], "Preceding low-star denominator mismatch."

    n_focus_p = n_all_p if review_focus_norm == "all" else n_low_p
    n_focus_pre = n_all_pre if review_focus_norm == "all" else n_low_pre
    n_focus_rec = n_all_rec if review_focus_norm == "all" else n_low_rec
    has_sufficient_trend_sample = (n_focus_pre >= min_comparison_reviews) and (n_focus_rec >= min_comparison_reviews)
    win_info["has_sufficient_trend_sample"] = bool(has_sufficient_trend_sample)
    win_info["min_comparison_reviews_required"] = int(min_comparison_reviews)
    win_info["min_theme_matching_per_window_required"] = int(min_theme_matching_per_window)

    raw_theme_rows: List[Dict[str, Any]] = []
    for tdef in THEME_DEFINITIONS:
        tid = tdef["theme_id"]

        sub_low_p = low_primary[low_primary[tid]]
        sub_all_p = df_primary[df_primary[tid]]

        # Validate that each theme count equals the exact number of unique matching reviewIds
        cnt_low_p = int(len(sub_low_p))
        cnt_all_p = int(len(sub_all_p))
        assert cnt_low_p == int(low_primary[tid].sum()) and sub_low_p["reviewId"].is_unique
        assert cnt_all_p == int(df_primary[tid].sum()) and sub_all_p["reviewId"].is_unique

        pct_low_p = round((cnt_low_p / n_low_p * 100.0), 2) if n_low_p > 0 else 0.0
        pct_all_p = round((cnt_all_p / n_all_p * 100.0), 2) if n_all_p > 0 else 0.0

        cnt_3star_p = int(df_primary[df_primary["score"] == 3][tid].sum()) if n_all_p > 0 else 0
        cnt_45star_p = int(df_primary[df_primary["score"].isin([4, 5])][tid].sum()) if n_all_p > 0 else 0

        cnt_low_rec = int(low_recent[tid].sum()) if n_low_rec > 0 else 0
        cnt_low_pre = int(low_preceding[tid].sum()) if n_low_pre > 0 else 0
        rate_low_rec = round((cnt_low_rec / n_low_rec * 100.0), 2) if n_low_rec > 0 else 0.0
        rate_low_pre = round((cnt_low_pre / n_low_pre * 100.0), 2) if n_low_pre > 0 else 0.0

        cnt_all_rec = int(df_recent[tid].sum()) if n_all_rec > 0 else 0
        cnt_all_pre = int(df_preceding[tid].sum()) if n_all_pre > 0 else 0
        rate_all_rec = round((cnt_all_rec / n_all_rec * 100.0), 2) if n_all_rec > 0 else 0.0
        rate_all_pre = round((cnt_all_pre / n_all_pre * 100.0), 2) if n_all_pre > 0 else 0.0

        trend_low_eval = evaluate_trend_with_safeguards(
            cnt_low_pre,
            n_low_pre,
            cnt_low_rec,
            n_low_rec,
            min_window_n=min_comparison_reviews,
            min_theme_matching_per_window=min_theme_matching_per_window,
        )
        trend_all_eval = evaluate_trend_with_safeguards(
            cnt_all_pre,
            n_all_pre,
            cnt_all_rec,
            n_all_rec,
            min_window_n=min_comparison_reviews,
            min_theme_matching_per_window=min_theme_matching_per_window,
        )
        # Per Requirement 3: calculate each theme's complaint rate trend as matching low-star reviews
        # divided by the relevant low-star review denominator for that window.
        active_trend = trend_low_eval

        focus_sub = sub_all_p if review_focus_norm == "all" else sub_low_p
        cnt_focus = cnt_all_p if review_focus_norm == "all" else cnt_low_p
        pct_focus = pct_all_p if review_focus_norm == "all" else pct_low_p

        thumbs_sum = int(focus_sub["thumbsUpCount"].sum()) if cnt_focus > 0 else 0
        avg_words = float(focus_sub["word_count"].mean()) if cnt_focus > 0 else 0.0
        mean_star_theme = round(float(focus_sub["score"].mean()), 2) if cnt_focus > 0 else None

        # Count how many matching reviews are Verified Primary vs. Uncertain/Manual Review
        verified_primary_cnt = 0
        verified_match_cnt = 0
        weak_secondary_cnt = 0
        manual_review_cnt = 0
        for _, r_row in focus_sub.iterrows():
            rid_str = str(r_row["reviewId"])
            t_info = review_audit_map.get(rid_str, {}).get("per_theme", {}).get(tid, {})
            if t_info.get("is_primary_theme", False):
                verified_primary_cnt += 1
            if t_info.get("needs_manual_review", False):
                manual_review_cnt += 1
                if not t_info.get("is_primary_theme", False):
                    weak_secondary_cnt += 1
            else:
                verified_match_cnt += 1

        has_direct_evidence = bool(cnt_focus > 0)

        if not has_direct_evidence:
            F_score = 0
            # Do not interpret missing data as a zero-severity problem: retain domain severity rating S_score
            S_score = int(tdef["severity_score"])
            T_score = 3
            C_score = 0
            E_ease = int(tdef["ease_score"])
            priority_score: Optional[float] = None
            evidence_status = "NO_DIRECT_EVIDENCE"
            evidence_label = "No direct review evidence in this period"
            recommendation_category = "PREVENTATIVE_UNCONFIRMED"
        else:
            F_score = score_frequency_with_safeguards(pct_focus, cnt_focus)
            S_score = int(tdef["severity_score"])
            T_score = int(active_trend["T_score_1_to_5"])
            C_score = score_classification_and_coverage_confidence_1_to_5(
                cnt_focus=cnt_focus,
                thumbs_sum=thumbs_sum,
                avg_words=avg_words,
                verified_match_cnt=verified_match_cnt,
                verified_primary_cnt=verified_primary_cnt,
                manual_review_cnt=manual_review_cnt,
                is_representative=dist_primary["is_representative"],
            )
            E_ease = int(tdef["ease_score"])

            priority_score = round(
                PRIORITY_WEIGHTS["frequency_F"] * F_score
                + PRIORITY_WEIGHTS["severity_S"] * S_score
                + PRIORITY_WEIGHTS["trend_T"] * T_score
                + PRIORITY_WEIGHTS["confidence_C"] * C_score
                + PRIORITY_WEIGHTS["feasibility_E"] * E_ease,
                2,
            )

            if tdef["track"] == "P0_SAFETY_OVERRIDE":
                recommendation_category = "SAFETY_ESCALATION"
                if cnt_focus >= MIN_CONFIRMED_THEME_REVIEWS and verified_match_cnt >= 1:
                    evidence_status = "CONFIRMED_SAFETY_ESCALATION"
                    evidence_label = f"Safety Escalation ({cnt_focus}/{n_focus_p} reviews; {verified_match_cnt} verified)"
                else:
                    evidence_status = "PRELIMINARY_SAFETY_TRIAGE"
                    evidence_label = f"Safety Triage — Low Sample ({cnt_focus}/{n_focus_p} reviews)"
            else:
                recommendation_category = "EVIDENCE_BACKED_PRIORITY"
                if verified_primary_cnt == 0 and weak_secondary_cnt == cnt_focus:
                    evidence_status = "SECONDARY_MULTILABEL_ONLY"
                    evidence_label = f"Secondary Multi-Label Mention Only ({cnt_focus}/{n_focus_p} reviews)"
                elif cnt_focus >= MIN_CONFIRMED_THEME_REVIEWS and verified_match_cnt >= 1:
                    evidence_status = "CONFIRMED_EVIDENCE"
                    evidence_label = f"Confirmed Evidence ({cnt_focus}/{n_focus_p} reviews)"
                else:
                    evidence_status = "PRELIMINARY_LOW_SAMPLE"
                    evidence_label = f"Preliminary / Low Sample ({cnt_focus}/{n_focus_p} reviews)"

        clean_ease = re.sub(r"\s*\[PROVISIONAL\]\.?", "", tdef["ease_rationale"]).strip()
        if not clean_ease.endswith("."):
            clean_ease += "."

        action_spec = THEME_ACTION_SPECS.get(tid, {})
        supporting_ev_summary = (
            f"{cnt_low_p}/{n_low_p} low-star reviews ({pct_low_p:.1f}%) and "
            f"{cnt_all_p}/{n_all_p} total reviews ({pct_all_p:.1f}%) in {win_info['primary_start_fmt']} – {win_info['primary_end_fmt']}; "
            f"Recent vs. Preceding trend: {active_trend['trend_display']}."
            if has_direct_evidence
            else f"0/{n_low_p} low-star reviews (0.0%) and 0/{n_all_p} total reviews in {win_info['primary_start_fmt']} – {win_info['primary_end_fmt']}. "
                 f"No direct review evidence in this period."
        )

        raw_theme_rows.append(
            {
                "theme_id": tid,
                "theme_name": tdef["theme_name"],
                "short_name": SHORT_THEME_NAMES.get(tid, tdef["theme_name"]),
                "track": tdef["track"],
                "recommendation_category": recommendation_category,
                "has_direct_evidence": has_direct_evidence,
                "evidence_status": evidence_status,
                "evidence_label": evidence_label,
                "verified_primary_count": verified_primary_cnt,
                "verified_match_count": verified_match_cnt,
                "manual_review_flagged_count": manual_review_cnt,
                "user_journey": tdef["user_journey"],
                "owner": tdef["owner"],
                "short_owner": SHORT_OWNER_NAMES.get(tid, tdef["owner"]),
                "count_1_2_star_primary": cnt_low_p,
                "pct_of_1_2_star_primary": pct_low_p,
                "count_all_reviews_primary": cnt_all_p,
                "pct_of_all_reviews_primary": pct_all_p,
                "primary_denom_1_2_star": n_low_p,
                "primary_denom_all": n_all_p,
                "count_3_star_primary": cnt_3star_p,
                "count_4_5_star_primary": cnt_45star_p,
                "mean_star_in_focus": mean_star_theme,
                "count_1_2_star_recent": cnt_low_rec,
                "rate_1_2_star_recent_pct": rate_low_rec,
                "recent_denom_1_2_star": n_low_rec,
                "count_1_2_star_preceding": cnt_low_pre,
                "rate_1_2_star_preceding_pct": rate_low_pre,
                "preceding_denom_1_2_star": n_low_pre,
                "delta_1_2_star_pp": trend_low_eval["delta_pp"],
                "rel_change_1_2_star_pct": trend_low_eval["rel_change_pct"],
                "count_all_recent": cnt_all_rec,
                "rate_all_recent_pct": rate_all_rec,
                "recent_denom_all": n_all_rec,
                "count_all_preceding": cnt_all_pre,
                "rate_all_preceding_pct": rate_all_pre,
                "preceding_denom_all": n_all_pre,
                "delta_all_pp": trend_all_eval["delta_pp"],
                "trend_status": active_trend["trend_status"],
                "trend_confidence": active_trend["trend_confidence"],
                "is_meaningful_increase": active_trend["is_meaningful_increase"],
                "trend_display": active_trend["trend_display"],
                "trend_short_display": active_trend["trend_short_display"],
                "thumbs_up_sum": thumbs_sum,
                "avg_word_count": round(avg_words, 1),
                "F_frequency_1_5": F_score,
                "S_severity_1_5": S_score,
                "T_trend_1_5": T_score,
                "C_confidence_1_5": C_score,
                "V_evidence_1_5": C_score,
                "E_ease_1_5_provisional": E_ease,
                "priority_score_1_to_5": priority_score,
                "ease_rationale": clean_ease,
                "symptom_summary": tdef["symptom_summary"],
                "root_cause_hypothesis": f"[HYPOTHESIS — REQUIRES TELEMETRY CONFIRMATION] {tdef['root_cause_hypothesis']}",
                "telemetry_check": tdef["telemetry_check"],
                # 7-Part Evidence-Backed Recommendation Fields (Requirement 5)
                "user_problem": action_spec.get("user_problem", tdef["symptom_summary"]),
                "supporting_evidence_summary": supporting_ev_summary,
                "why_important": action_spec.get("why_important", ""),
                "first_concrete_action": action_spec.get("first_concrete_action", ""),
                "validation_metric": action_spec.get("validation_metric", ""),
                "missing_telemetry_to_confirm": action_spec.get("missing_telemetry_to_confirm", tdef["telemetry_check"]),
                # Legacy aliases kept for backward compatibility
                "proposed_fix": action_spec.get("first_concrete_action", ""),
                "provisional_target": action_spec.get("validation_metric", ""),
                "_focus_sub_df": focus_sub,
            }
        )

    # Select Verified Representative Quotes with Cross-Theme Deduplication FIRST
    # so secondary-only overlaps are identified before final priority rank assignment.
    used_quote_ids: Set[str] = set()
    allocation_order = sorted(
        raw_theme_rows,
        key=lambda r: (
            0 if r["has_direct_evidence"] else 1,
            0 if r["evidence_status"] != "SECONDARY_MULTILABEL_ONLY" else 1,
            0 if r["recommendation_category"] == "SAFETY_ESCALATION" else 1,
            r["count_1_2_star_primary"],
        ),
    )
    for r in allocation_order:
        tid = r["theme_id"]
        focus_sub = r.pop("_focus_sub_df")
        if not r["has_direct_evidence"] or len(focus_sub) == 0:
            r["supporting_quotes"] = []
            r["shared_evidence_note"] = (
                "No direct review evidence in this period. Absence of sampled Play Store reviews "
                "does not prove this issue does not exist in production; verify via internal telemetry."
            )
            continue

        cand_df = focus_sub[focus_sub["score"].isin([1, 2])] if len(focus_sub[focus_sub["score"].isin([1, 2])]) > 0 else focus_sub
        scored_cands: List[Tuple[Tuple[int, int, int, int, pd.Timestamp], pd.Series, Dict[str, Any]]] = []
        for _, row in cand_df.iterrows():
            rid = str(row["reviewId"])
            t_audit = review_audit_map.get(rid, {}).get("per_theme", {}).get(tid, {})
            is_prim = 1 if t_audit.get("is_primary_theme", False) else 0
            not_manual = 0 if t_audit.get("needs_manual_review", False) else 1
            spec = int(t_audit.get("specificity_score", 1))
            thumbs = int(row["thumbsUpCount"])
            scored_cands.append(((is_prim, not_manual, spec, thumbs, row["at_dt"]), row, t_audit))

        scored_cands.sort(key=lambda x: x[0], reverse=True)

        quotes_list: List[Dict[str, Any]] = []
        skipped_shared_rids: List[Tuple[str, str, str]] = []
        for _, row, t_audit in scored_cands:
            rid = str(row["reviewId"])
            if rid in used_quote_ids:
                prim_tid = review_audit_map.get(rid, {}).get("primary_theme_id")
                prim_name = SHORT_THEME_NAMES.get(prim_tid, prim_tid or "another theme")
                skipped_shared_rids.append((rid[:8], fmt_date_short(str(row["at"])[:10]), prim_name))
                continue
            if not t_audit.get("is_primary_theme", False) and t_audit.get("needs_manual_review", False):
                prim_tid = review_audit_map.get(rid, {}).get("primary_theme_id")
                prim_name = SHORT_THEME_NAMES.get(prim_tid, prim_tid or "another theme")
                skipped_shared_rids.append((rid[:8], fmt_date_short(str(row["at"])[:10]), prim_name))
                continue

            used_quote_ids.add(rid)
            quotes_list.append(
                {
                    "reviewId": rid,
                    "date": fmt_date_short(str(row["at"])[:10]),
                    "score": int(row["score"]),
                    "version": str(row["version_raw"]),
                    "thumbsUpCount": int(row["thumbsUpCount"]),
                    "content": str(row["content_clean"]),
                    "confidence_label": t_audit.get("confidence_label", "Verified Match"),
                    "needs_manual_review": bool(t_audit.get("needs_manual_review", False)),
                    "assignment_reason": t_audit.get("assignment_reason", "Matched theme domain pattern."),
                    "matched_keywords": t_audit.get("matched_keywords", []),
                }
            )
            if len(quotes_list) >= 3:
                break

        r["supporting_quotes"] = quotes_list
        if len(quotes_list) == 0 and len(skipped_shared_rids) > 0:
            ref_rid, ref_dt, ref_prim = skipped_shared_rids[0]
            r["shared_evidence_note"] = (
                f"Matched only as a secondary symptom in a multi-label review ({ref_dt}, primarily classified under "
                f"'{ref_prim}'). To avoid reusing the same review across unrelated themes, the excerpt is shown only under '{ref_prim}'."
            )
            if r["count_1_2_star_primary"] <= 1:
                r["evidence_status"] = "SECONDARY_MULTILABEL_ONLY"
                r["evidence_label"] = f"Secondary Multi-Label Mention Only (see {ref_prim})"
        else:
            r["shared_evidence_note"] = None

    # Now sort themes strictly and assign Priority Ranks once from validated evidence & scores:
    def _rank_sort_key(r: Dict[str, Any]) -> Tuple[int, int, int, float, int]:
        if not r["has_direct_evidence"]:
            return (0, 0, 0, 0.0, 0)
        cat_order = 2 if r["recommendation_category"] == "EVIDENCE_BACKED_PRIORITY" else 1
        if r["evidence_status"] in ("CONFIRMED_EVIDENCE", "CONFIRMED_SAFETY_ESCALATION"):
            conf_order = 3
        elif r["evidence_status"] in ("PRELIMINARY_LOW_SAMPLE", "PRELIMINARY_SAFETY_TRIAGE"):
            conf_order = 2
        else:
            conf_order = 1
        prim_order = 1 if r["verified_primary_count"] > 0 else 0
        sc = float(r["priority_score_1_to_5"] or 0.0)
        cnt_f = r["count_all_reviews_primary"] if review_focus_norm == "all" else r["count_1_2_star_primary"]
        return (cat_order, conf_order, prim_order, sc, cnt_f)

    raw_theme_rows.sort(key=_rank_sort_key, reverse=True)

    ev_rank_counter = 1
    for r in raw_theme_rows:
        if not r["has_direct_evidence"]:
            r["priority_rank"] = "Unranked (0 Reviews)"
        elif r["recommendation_category"] == "SAFETY_ESCALATION":
            r["priority_rank"] = "Safety Escalation"
        elif r["evidence_status"] == "SECONDARY_MULTILABEL_ONLY":
            r["priority_rank"] = "Secondary Overlap"
        else:
            r["priority_rank"] = f"Rank #{ev_rank_counter}"
            ev_rank_counter += 1

    theme_rows = raw_theme_rows

    # Multi-label classification accounting & validation against underlying records
    unmatched_low_p = int((low_primary["matched_theme_count"] == 0).sum()) if n_low_p > 0 else 0
    matched_low_p = int((low_primary["matched_theme_count"] > 0).sum()) if n_low_p > 0 else 0
    single_label_low_p = int((low_primary["matched_theme_count"] == 1).sum()) if n_low_p > 0 else 0
    multi_label_low_p = int((low_primary["matched_theme_count"] >= 2).sum()) if n_low_p > 0 else 0
    total_theme_mentions_low_p = int(low_primary["matched_theme_count"].sum()) if n_low_p > 0 else 0

    assert matched_low_p + unmatched_low_p == n_low_p, "Matched + unmatched low-star reviews must equal total low-star reviews."
    assert single_label_low_p + multi_label_low_p == matched_low_p, "Single + multi-label low-star reviews must equal matched low-star reviews."
    assert sum(r["count_1_2_star_primary"] for r in theme_rows) == total_theme_mentions_low_p, "Sum of theme low-star counts must equal total multi-label assignments."

    # Version-correlated anomaly table within selected Primary Window
    version_rows: List[Dict[str, Any]] = []
    min_ver_n = 10 if len(df_primary) < 1000 else 20
    for ver_fam, grp in df_primary.groupby("version_family"):
        n_v = len(grp)
        if n_v < min_ver_n:
            continue
        low_v = grp[grp["score"].isin([1, 2])]
        n_low_v = len(low_v)
        crash_cnt = int(low_v["T02_CRASH_LAUNCH_PERFORMANCE"].sum())
        version_rows.append(
            {
                "version_family": str(ver_fam),
                "n_reviews": n_v,
                "min_date": fmt_date_short(str(grp["at_dt"].min())[:10]),
                "max_date": fmt_date_short(str(grp["at_dt"].max())[:10]),
                "sample_mean_rating": round(float(grp["score"].mean()), 2),
                "count_1_2_star": n_low_v,
                "pct_1_2_star": round(n_low_v / n_v * 100.0, 2),
                "crash_launch_count": crash_cnt,
                "crash_launch_pct_of_ver": round(crash_cnt / n_v * 100.0, 2),
                "routing_delay_count": int(low_v["T07_ROUTING_CAB_DELAY_ETA"].sum()),
                "scheduling_noshow_count": int(low_v["T08_SCHEDULING_ROSTER_NOSHOW"].sum()),
            }
        )
    version_rows.sort(key=lambda x: x["n_reviews"], reverse=True)

    # Generate simple, human-readable report_id
    now_utc = dt.datetime.now(dt.timezone.utc)
    if win_info["primary_period_mode"] in ("3m", "6m", "12m"):
        base_code = win_info["primary_period_mode"].upper()
        suffix = "-ALL" if review_focus_norm == "all" else ""
        report_id = f"RPT-{base_code}{suffix}"
    else:
        s_short = win_info["primary_start"][2:7].replace("-", "")
        e_short = win_info["primary_end"][2:7].replace("-", "")
        report_id = f"RPT-{s_short}-{e_short}"

    out_dir = base_dir / "reports" / "generated" / report_id if save_artifacts else None
    fig_dir = out_dir / "figures" if out_dir else None

    raw_in = app_meta["raw_html_audit_india_locale"]
    hist_arr = raw_in["ds5_histogram_1_to_5"]
    hist_sum_val = raw_in["ds5_histogram_sum"]
    weighted_mean_val = round(sum((i + 1) * c for i, c in enumerate(hist_arr)) / hist_sum_val, 4)
    store_meta = {
        "score_displayed_text": raw_in["ds5_score_display"],
        "exact_unrounded_score": raw_in["ds5_score_exact"],
        "histogram_weighted_mean": weighted_mean_val,
        "ratings_total_reported": raw_in["ds5_reported_ratings_total"],
        "reviews_total_reported": raw_in["ds5_reported_written_reviews"],
        "histogram_1_to_5": hist_arr,
        "histogram_sum": hist_sum_val,
        "discrepancy_total_minus_sum": raw_in["ds5_discrepancy_total_minus_bucket_sum"],
    }
    charts_b64 = render_dynamic_charts(
        store_meta=store_meta,
        dist_primary=dist_primary,
        dist_recent=dist_recent,
        dist_preceding=dist_preceding,
        monthly_rows=monthly_rows,
        theme_rows=theme_rows,
        win_info=win_info,
        review_focus=review_focus_norm,
        fig_dir=fig_dir,
    )

    # Partition themes from the single shared theme_rows list:
    evidence_backed_themes = [
        r for r in theme_rows
        if r["has_direct_evidence"]
        and r["recommendation_category"] == "EVIDENCE_BACKED_PRIORITY"
        and r["evidence_status"] != "SECONDARY_MULTILABEL_ONLY"
    ]
    safety_escalation_themes = [
        r for r in theme_rows
        if r["has_direct_evidence"] and r["recommendation_category"] == "SAFETY_ESCALATION"
    ]
    unconfirmed_preventative_themes = [
        r for r in theme_rows
        if not r["has_direct_evidence"] or r["evidence_status"] == "SECONDARY_MULTILABEL_ONLY"
    ]

    cnt_col_key = "count_all_reviews_primary" if review_focus_norm == "all" else "count_1_2_star_primary"
    pct_col_key = "pct_of_all_reviews_primary" if review_focus_norm == "all" else "pct_of_1_2_star_primary"
    focus_desc = "reviews" if review_focus_norm == "all" else "low-star (1–2★) reviews"

    top_by_vol = sorted(
        [r for r in theme_rows if r["has_direct_evidence"] and r["evidence_status"] != "SECONDARY_MULTILABEL_ONLY"],
        key=lambda r: r[cnt_col_key],
        reverse=True,
    )[:3]

    # Top 3 Evidence-Backed Problems (Structured list shared across Executive Summary & Main Report)
    is_insufficient_overall_sample = (n_focus_p < MIN_SUFFICIENT_PRIMARY_LOW_REVIEWS)
    top_3_problems: List[Dict[str, Any]] = []
    for r in evidence_backed_themes[:3]:
        top_3_problems.append(
            {
                "priority_rank": r["priority_rank"],
                "theme_id": r["theme_id"],
                "theme_name": r["theme_name"],
                "short_name": r["short_name"],
                "priority_score_1_to_5": r["priority_score_1_to_5"],
                "count_focus": r[cnt_col_key],
                "denom_focus": n_focus_p,
                "pct_focus": r[pct_col_key],
                "trend_short_display": r["trend_short_display"],
                "trend_status": r["trend_status"],
                "evidence_label": r["evidence_label"],
                "user_problem": r["user_problem"],
                "first_concrete_action": r["first_concrete_action"],
                "owner": r["owner"],
                "short_owner": r["short_owner"],
                "validation_metric": r["validation_metric"],
            }
        )

    # Card 1: What Are Users Complaining About? (Only themes with direct evidence)
    if len(top_by_vol) > 0:
        what_users_complain = [
            f"<strong>#{i+1} {r['short_name']} — {r[pct_col_key]:.1f}%</strong>"
            f"<div class='exec-subline'>({r[cnt_col_key]}/{n_focus_p} {focus_desc})</div>"
            for i, r in enumerate(top_by_vol)
        ]
        zero_only_cnt = sum(1 for r in theme_rows if not r["has_direct_evidence"])
        if zero_only_cnt > 0:
            what_users_complain.append(
                f"<em>Note: {zero_only_cnt} of 10 taxonomy themes have "
                f"<strong>0/{n_focus_p}</strong> matching reviews in this period (no direct review evidence).</em>"
            )
    else:
        what_users_complain = [
            f"<strong>No direct review evidence in this period</strong><div class='exec-subline'>(0/{n_focus_p} {focus_desc} matched complaint themes)</div>"
        ]

    # Card 2: Which Problems Are Increasing? (Enforces n >= 10 in both comparison windows)
    if not has_sufficient_trend_sample:
        status_lbl = "No baseline available" if n_focus_pre == 0 else "Insufficient evidence for trend ranking"
        which_increasing = [
            f"<strong>{status_lbl}</strong>"
            f"<div class='exec-subline'>Preceding n={n_focus_pre}, Recent n={n_focus_rec} {focus_desc} (min n ≥ {min_comparison_reviews} required)</div>",
            "Percentage-point shifts from tiny or zero samples are suppressed to avoid false trend claims.",
        ]
    else:
        meaningful_surges = sorted(
            [r for r in theme_rows if r["is_meaningful_increase"] and r["trend_status"] == "VALID"],
            key=lambda r: float(r["delta_all_pp" if review_focus_norm == "all" else "delta_1_2_star_pp"] or 0.0),
            reverse=True,
        )[:3]
        if len(meaningful_surges) > 0:
            which_increasing = [
                f"<strong>{r['short_name']} — <span style='color:#be123c;'>{r['trend_short_display'].split(' (')[0]}</span></strong>"
                f"<div class='exec-subline'>("
                f"{r['rate_all_preceding_pct' if review_focus_norm == 'all' else 'rate_1_2_star_preceding_pct']:.1f}% "
                f"[{r['count_all_preceding' if review_focus_norm == 'all' else 'count_1_2_star_preceding']}/{n_focus_pre}] → "
                f"{r['rate_all_recent_pct' if review_focus_norm == 'all' else 'rate_1_2_star_recent_pct']:.1f}% "
                f"[{r['count_all_recent' if review_focus_norm == 'all' else 'count_1_2_star_recent']}/{n_focus_rec}])</div>"
                for r in meaningful_surges
            ]
        else:
            which_increasing = [
                f"<strong>No statistically meaningful complaint increases</strong>"
                f"<div class='exec-subline'>Requires ≥{min_theme_matching_per_window} matches/window across Preceding (n={n_focus_pre}) vs. Recent (n={n_focus_rec})</div>"
            ]

    # Card 3: What Should MoveInSync Fix First? (Derived strictly from evidence_backed_themes[:3])
    if is_insufficient_overall_sample:
        what_to_fix = [
            f"<strong>Insufficient sample for confident priority ranking (n={n_focus_p} {focus_desc} in period)</strong>"
            f"<div class='exec-subline'>Export full historical logs from Google Play Console or analyze the 19 Jun 2025 – 11 Oct 2026 window.</div>",
        ]
        for r in evidence_backed_themes[:3]:
            what_to_fix.append(
                f"<strong>Preliminary Observation ({r['priority_rank']}: {r['short_name']})</strong>"
                f"<div class='exec-subline'>{r[cnt_col_key]}/{n_focus_p} reviews ({r['evidence_label']}) &bull; {r['short_owner']}</div>"
            )
    else:
        what_to_fix = [
            f"<strong>{r['priority_rank']}: {r['short_name']} — Score {r['priority_score_1_to_5']:.2f} / 5.0</strong>"
            f"<div class='exec-subline'>({r[cnt_col_key]}/{n_focus_p} reviews, {r[pct_col_key]:.1f}%) &bull; {r['short_owner']}</div>"
            for r in evidence_backed_themes[:3]
        ]
        if len(safety_escalation_themes) > 0:
            sr = safety_escalation_themes[0]
            what_to_fix.append(
                f"<strong>Safety Escalation: {sr['short_name']}</strong>"
                f"<div class='exec-subline'>{sr[cnt_col_key]}/{n_focus_p} reviews ({sr[pct_col_key]:.1f}%) &bull; Immediate Ops &amp; Mobile Triage</div>"
            )

    if is_insufficient_overall_sample or not dist_primary["is_representative"]:
        advisory_banner = (
            f"DATA SUFFICIENCY & COVERAGE ADVISORY: The selected period ({win_info['primary_start_fmt']} – {win_info['primary_end_fmt']}) "
            f"contains n={dist_primary['n_reviews']:,} collected reviews ({dist_primary['count_low_1_2_star']:,} low-star). "
            f"{dist_primary['representativeness_note']} "
            f"Comparison windows contain Preceding n={n_focus_pre} and Recent n={n_focus_rec} relevant reviews. "
            f"Next investigation step: export full historical archives from Google Play Console Cloud Storage or analyze the complete "
            f"unfiltered window (19 Jun 2025 – 11 Oct 2026) before locking engineering priorities."
        )
    else:
        advisory_banner = None

    safety_t01_row = next((r for r in theme_rows if r["theme_id"] == "T01_SAFETY_SOS_EMERGENCY"), None)
    if safety_t01_row and safety_t01_row["has_direct_evidence"]:
        safety_escalation_summary = {
            "has_credible_evidence": True,
            "count_low_star": safety_t01_row["count_1_2_star_primary"],
            "denom_low_star": n_low_p,
            "pct_low_star": safety_t01_row["pct_of_1_2_star_primary"],
            "verified_match_count": safety_t01_row["verified_match_count"],
            "priority_score_1_to_5": safety_t01_row["priority_score_1_to_5"],
            "status_label": safety_t01_row["evidence_label"],
            "escalation_note": (
                "Routed on a dedicated Safety Escalation path for immediate operational & mobile triage "
                "alongside Rank #1–#3 engineering priorities."
            ),
            "first_concrete_action": safety_t01_row["first_concrete_action"],
            "owner": safety_t01_row["owner"],
            "validation_metric": safety_t01_row["validation_metric"],
        }
    else:
        safety_escalation_summary = {
            "has_credible_evidence": False,
            "count_low_star": 0,
            "denom_low_star": n_low_p,
            "pct_low_star": 0.0,
            "verified_match_count": 0,
            "priority_score_1_to_5": None,
            "status_label": "No direct review evidence in this period",
            "escalation_note": (
                f"0/{n_low_p} sampled reviews matched Safety & SOS Emergency in {win_info['primary_start_fmt']} – {win_info['primary_end_fmt']}. "
                f"It is not ranked as a confirmed complaint priority, but missing review evidence is never interpreted as proof of safety; "
                f"continuous SOS & night-shift telemetry monitoring remains mandatory."
            ),
            "first_concrete_action": THEME_ACTION_SPECS["T01_SAFETY_SOS_EMERGENCY"]["first_concrete_action"],
            "owner": SHORT_OWNER_NAMES["T01_SAFETY_SOS_EMERGENCY"],
            "validation_metric": THEME_ACTION_SPECS["T01_SAFETY_SOS_EMERGENCY"]["validation_metric"],
        }

    exec_summary = {
        "is_sufficient_evidence": not is_insufficient_overall_sample,
        "advisory_banner": advisory_banner,
        "headline": (
            f"Across {win_info['primary_start_fmt']} – {win_info['primary_end_fmt']} ({win_info['primary_days']} days), "
            f"n={dist_primary['n_reviews']:,} deduplicated written reviews were analyzed "
            f"({dist_primary['mean_rating_display']} vs. Official Play Store "
            f"Rating: {store_meta['exact_unrounded_score']:.2f}★ across n={store_meta['ratings_total_reported']:,} total ratings). "
            f"Low-star (1–2★) complaints account for {dist_primary['count_low_1_2_star']:,}/{dist_primary['n_reviews']:,} reviews "
            f"({dist_primary['pct_low_1_2_star']:.2f}%)."
        ),
        "top_3_evidence_backed_problems": top_3_problems,
        "safety_escalation_summary": safety_escalation_summary,
        "what_users_complain_about_now": what_users_complain,
        "which_problems_are_increasing": which_increasing,
        "what_to_fix_first": what_to_fix,
        "developer_reply_observation": (
            f"Developer reply rate on 1–2★ reviews is "
            f"{dist_primary['dev_reply_rate_1_2_star_pct']:.2f}% ({dist_primary['dev_reply_count_1_2_star']}/{dist_primary['count_low_1_2_star']}) in Primary, "
            f"and {dist_recent['dev_reply_rate_1_2_star_pct']:.2f}% ({dist_recent['dev_reply_count_1_2_star']}/{dist_recent['count_low_1_2_star']}) in Recent."
        ),
    }

    scoring_methodology = {
        "formula_expression": "Priority Score = 0.25*F + 0.25*S + 0.20*T + 0.15*C + 0.15*E (Scale: 1.00 to 5.00)",
        "weights": PRIORITY_WEIGHTS,
        "components": [
            {
                "code": "F",
                "name": "Complaint Frequency",
                "weight_pct": 25,
                "description": (
                    "1–5 scale based on theme share of focus reviews in the Primary window, capped by absolute "
                    "review count (count=1 -> max 1; count=2 -> max 2; count<5 -> max 3; count<10 -> max 4) "
                    "so tiny samples cannot produce high frequency scores."
                ),
            },
            {
                "code": "S",
                "name": "Severity & Commuter Impact",
                "weight_pct": 25,
                "description": (
                    "1–5 scale measuring journey blockage (5 = physical safety or total app launch/integrity lockout; "
                    "4 = missed pickup, auth logout, or auto-cancelled ride; 3 = prompt/support friction; 2 = UI usability). "
                    "Missing review data is never interpreted as zero severity."
                ),
            },
            {
                "code": "T",
                "name": "Recent vs. Preceding Trend",
                "weight_pct": 20,
                "description": (
                    f"1–5 scale from percentage-point shift (Recent rate minus Preceding rate). Requires n >= {min_comparison_reviews} "
                    f"relevant reviews and >= {min_theme_matching_per_window} matching theme reviews per comparison window; "
                    f"otherwise held at neutral T=3 ('Insufficient evidence' or 'No baseline available')."
                ),
            },
            {
                "code": "C",
                "name": "Classification & Coverage Confidence",
                "weight_pct": 15,
                "description": (
                    "1–5 scale combining verified review match count, specificity/detail, and window coverage representativeness "
                    "(capped at <= 2 when historical coverage is incomplete/biased or theme count < 3)."
                ),
            },
            {
                "code": "E",
                "name": "Feasibility & Implementation Ease",
                "weight_pct": 15,
                "description": (
                    "1–5 scale where higher values indicate faster engineering/operational turnaround (5 = UI modal/config change; "
                    "4 = client auth/integrity/UX fix; 3 = crash/tracking/schedule fix; 2 = multi-stop routing solver or multi-vendor ops)."
                ),
            },
        ],
        "safeguard_rules": [
            "Zero-Review Rule: Themes with 0 matching reviews receive Priority Score = None ('Unranked (0 Reviews)') and are separated into preventative monitoring guardrails.",
            "Separate Safety Escalation: Credible safety incidents (T01 count > 0) are escalated on a dedicated Safety Escalation track rather than competing solely on weighted score.",
            "Root-Cause Hypothesis Rule: All technical causes inferred from review text are labeled as hypotheses requiring internal product/operations telemetry confirmation.",
        ],
    }

    data_limitations = [
        (
            "<strong>Rating vs. review sentiment:</strong> The official Google Play rating reflects all ratings, "
            "while sentiment analysis is based on the written reviews collected for the selected period."
        ),
        (
            "<strong>Data coverage:</strong> Review coverage varies by date. Older reviews may come from sampled results, "
            "so the analysis may not represent every review in the selected period."
        ),
        (
            "<strong>Theme overlap:</strong> A review may mention multiple problems. Issue counts can overlap "
            "and should not be added together."
        ),
        (
            "<strong>Evidence threshold:</strong> Trends are reported only when enough relevant reviews are available; "
            "otherwise, the report states that evidence is insufficient."
        ),
    ]

    # Cross-section mathematical consistency verification before returning payload
    for top_prob in exec_summary["top_3_evidence_backed_problems"]:
        matching_row = next(r for r in theme_rows if r["theme_id"] == top_prob["theme_id"])
        assert matching_row["has_direct_evidence"] is True, "Top problem must have direct review evidence."
        assert matching_row[cnt_col_key] > 0, "Top problem count must be strictly positive."
        assert matching_row["priority_rank"] == top_prob["priority_rank"], "Rank mismatch between Executive Summary and Theme Table."
        assert matching_row["priority_score_1_to_5"] == top_prob["priority_score_1_to_5"], "Score mismatch between Executive Summary and Theme Table."

    report_payload: Dict[str, Any] = {
        "report_metadata": {
            "report_id": report_id,
            "generated_at_utc": now_utc.strftime("%d %b %Y, %H:%M UTC"),
            "methodology_version": METHODOLOGY_VERSION,
            "snapshot_id": manifest.get("resolved_snapshot_id", snapshot_id),
            "snapshot_retrieved_utc": manifest.get("collection_completed_utc") or manifest.get("generated_at_ist", "2026-10-12T10:07:15Z"),
            "snapshot_file": manifest.get("jsonl_file", "reviews_raw_latest.jsonl"),
            "snapshot_total_unique_reviews": int(len(df)),
            "review_focus": review_focus_norm,
            "refresh_status": refresh_status,
        },
        "window_configuration": win_info,
        "store_baseline": {
            "app_id": "com.moveinsync.ets",
            "title": "MoveInSync",
            "source_url": "https://play.google.com/store/apps/details?id=com.moveinsync.ets&hl=en&gl=in",
            "displayed_score_text": store_meta["score_displayed_text"],
            "exact_unrounded_score": store_meta["exact_unrounded_score"],
            "histogram_weighted_mean": store_meta["histogram_weighted_mean"],
            "ratings_total_reported": store_meta["ratings_total_reported"],
            "written_reviews_total_reported": store_meta["reviews_total_reported"],
            "histogram_1_to_5": store_meta["histogram_1_to_5"],
            "histogram_sum": store_meta["histogram_sum"],
            "discrepancy_total_minus_sum": store_meta["discrepancy_total_minus_sum"],
        },
        "executive_summary": exec_summary,
        "distributions": {
            "primary": dist_primary,
            "recent": dist_recent,
            "preceding": dist_preceding,
            "quarantined_older": dist_quarantined,
        },
        "classification_coverage": {
            "primary_low_star_total": n_low_p,
            "primary_low_star_matched_themes": matched_low_p,
            "primary_low_star_matched_pct": round(matched_low_p / n_low_p * 100.0, 2) if n_low_p > 0 else 0.0,
            "primary_low_star_single_label": single_label_low_p,
            "primary_low_star_multi_label": multi_label_low_p,
            "primary_low_star_total_theme_assignments": total_theme_mentions_low_p,
            "primary_low_star_generic_unelaborated": unmatched_low_p,
            "primary_low_star_generic_pct": round(unmatched_low_p / n_low_p * 100.0, 2) if n_low_p > 0 else 0.0,
            "multi_label_explanation": (
                f"Reviews can match multiple complaint themes when commuters report multiple issues in one review "
                f"({multi_label_low_p} multi-label and {single_label_low_p} single-label low-star reviews, totaling "
                f"{total_theme_mentions_low_p} theme assignments across {matched_low_p} matched low-star reviews). "
                f"Each theme count reflects distinct matching reviews (reviewId) and must not be summed as mutually exclusive."
            ),
        },
        "scoring_methodology": scoring_methodology,
        "data_limitations": data_limitations,
        "monthly_trend": monthly_rows,
        "themes_and_recommendations": theme_rows,
        "version_anomalies": version_rows,
        "charts": charts_b64,
    }

    if save_artifacts and out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "report_data.json", "w", encoding="utf-8") as f:
            json.dump(report_payload, f, indent=2, ensure_ascii=False)

        standalone_html = build_standalone_export_html(report_payload)
        with open(out_dir / "report_export.html", "w", encoding="utf-8") as f:
            f.write(standalone_html)

        hist_path = base_dir / "reports" / "generated" / "report_history.json"
        history_list: List[Dict[str, Any]] = []
        if hist_path.exists():
            try:
                with open(hist_path, "r", encoding="utf-8") as f:
                    history_list = json.load(f)
            except Exception:
                history_list = []

        history_entry = {
            "report_id": report_id,
            "generated_at_utc": report_payload["report_metadata"]["generated_at_utc"],
            "methodology_version": METHODOLOGY_VERSION,
            "snapshot_id": report_payload["report_metadata"]["snapshot_id"],
            "primary_period_mode": win_info["primary_period_mode"],
            "primary_start": win_info["primary_start"],
            "primary_end": win_info["primary_end"],
            "trend_comparison_mode": win_info["trend_comparison_mode"],
            "recent_window": f"{win_info['recent_start']}..{win_info['recent_end']}",
            "preceding_window": f"{win_info['preceding_start']}..{win_info['preceding_end']}",
            "review_focus": review_focus_norm,
            "n_reviews_primary": dist_primary["n_reviews"],
            "n_low_star_primary": dist_primary["count_low_1_2_star"],
            "sample_mean_primary": dist_primary["sample_mean_rating"],
            "is_sample_representative": dist_primary["is_representative"],
            "top_priority_theme": evidence_backed_themes[0]["theme_id"] if evidence_backed_themes else None,
            "second_priority_theme": evidence_backed_themes[1]["theme_id"] if len(evidence_backed_themes) > 1 else None,
            "export_html_path": f"reports/generated/{report_id}/report_export.html",
        }
        history_list = [h for h in history_list if h.get("report_id") != report_id]
        history_list.insert(0, history_entry)
        history_list = history_list[:50]
        with open(hist_path, "w", encoding="utf-8") as f:
            json.dump(history_list, f, indent=2, ensure_ascii=False)

    return report_payload


def build_standalone_export_html(rep: Dict[str, Any]) -> str:
    """
    Builds a clean, executive-friendly, self-contained HTML/PDF report organized into:
      MAIN REPORT:
        1. Executive Summary & Three Most Important Evidence-Backed Problems (+ Separate Safety Escalation)
        2. Recent-versus-Preceding Trend Summary & Rating Distribution
        3. Recommended Actions in Priority Order (with all 7 required fields)
        4. Owners & Validation Metrics Summary
        5. Data Coverage & Limitations
      APPENDIX:
        - Appendix A: Detailed Theme Counts & Preventative Guardrails
        - Appendix C: Priority Scoring Methodology & Weights
        - Appendix D: Engineering Root-Cause Hypotheses & Internal Telemetry Checks
        - Appendix E: App-Version Anomaly Analysis
    """
    meta = rep["report_metadata"]
    win = rep["window_configuration"]
    sb = rep["store_baseline"]
    ex = rep["executive_summary"]
    dp = rep["distributions"]["primary"]
    dr = rep["distributions"]["recent"]
    dpre = rep["distributions"]["preceding"]
    dq = rep["distributions"]["quarantined_older"]
    cov = rep["classification_coverage"]
    scm = rep["scoring_methodology"]
    lims = rep["data_limitations"]
    themes = rep["themes_and_recommendations"]
    versions = rep["version_anomalies"]
    charts = rep["charts"]

    is_all = meta.get("review_focus") == "all"
    prim_denom = dp["n_reviews"] if is_all else dp["count_low_1_2_star"]
    pre_denom = dpre["n_reviews"] if is_all else dpre["count_low_1_2_star"]
    rec_denom = dr["n_reviews"] if is_all else dr["count_low_1_2_star"]
    focus_col_lbl = "All Reviews" if is_all else "Low-Star 1–2★"

    # Coverage / Data Sufficiency Advisory Banner
    warn_html = ""
    if ex.get("advisory_banner") or not win["is_fully_covered_unfiltered"]:
        items = ""
        if ex.get("advisory_banner"):
            items += f"<li><strong>{ex['advisory_banner']}</strong></li>"
        for w in win.get("coverage_warnings", []):
            items += f"<li>{w}</li>"
        for m in win.get("missing_or_partial_intervals", []):
            items += f"<li><strong>[{m['interval_type']}] {fmt_date_short(m['start'])} – {fmt_date_short(m['end'])}:</strong> {m['explanation']}</li>"
        warn_html = f"""
        <div class="alert-box">
          <strong>Data Sufficiency &amp; Coverage Safeguard Advisory:</strong>
          <ul>{items}</ul>
        </div>
        """

    # Top 3 Evidence-Backed Problems Cards (Main Report Section 1)
    top3 = ex.get("top_3_evidence_backed_problems", [])
    if top3:
        top3_cards_html = '<div class="grid-3">'
        for p in top3:
            sc_txt = f"{p['priority_score_1_to_5']:.2f} / 5.0" if p.get("priority_score_1_to_5") is not None else "N/A"
            top3_cards_html += f"""
            <div class="prob-card">
              <div class="prob-top-row">
                <span class="prob-rank-pill">{p['priority_rank']}</span>
                <span class="prob-score-pill">Score: {sc_txt}</span>
              </div>
              <div class="prob-title">{p['theme_name']}</div>
              <div class="prob-stat-box">
                <div><strong>Primary Share:</strong> {p['pct_focus']:.1f}% ({p['count_focus']}/{p['denom_focus']} {focus_col_lbl})</div>
                <div><strong>Recent Trend:</strong> {p['trend_short_display']}</div>
              </div>
              <div class="prob-desc">{p['user_problem']}</div>
              <div class="prob-meta"><span class="owner-chip">Owner: {p['short_owner']}</span></div>
            </div>
            """
        top3_cards_html += "</div>"
    else:
        top3_cards_html = f"""
        <div class="alert-box">
          <strong>No confirmed evidence-backed problems in {win['primary_start_fmt']} – {win['primary_end_fmt']} (0/{prim_denom} matching reviews).</strong>
          Select a wider date range or collect additional review evidence before ranking priorities.
        </div>
        """

    # Separate Safety Escalation Box (Clean, balanced card layout)
    saf = ex.get("safety_escalation_summary", {})
    if saf.get("has_credible_evidence"):
        saf_html = f"""
        <div class="safety-box active">
          <div class="safety-hdr">
            <div class="safety-hdr-left">
              <span class="safety-badge">🚨 Separate Safety Escalation Track</span>
              <span class="safety-title">Safety, SOS Alarm &amp; Night-Shift Security</span>
            </div>
            <span class="safety-count-pill">{saf['count_low_star']}/{saf['denom_low_star']} low-star reviews ({saf['pct_low_star']:.1f}%)</span>
          </div>
          <div class="safety-note">{saf['escalation_note']}</div>
          <div class="safety-body-card">
            <div class="safety-action-row">
              <strong>First Action:</strong> {saf['first_concrete_action']}
            </div>
            <div class="safety-owner-row">
              <strong>Owner:</strong> <span class="owner-chip">{saf['owner']}</span>
            </div>
          </div>
        </div>
        """
    else:
        saf_html = f"""
        <div class="safety-box">
          <strong>Safety Escalation Status (0/{saf.get('denom_low_star', 0)} matching reviews in period):</strong>
          {saf.get('escalation_note', '')}
        </div>
        """

    # Main Report Section 2: Recent-versus-Preceding Trend Summary Table (Only themes with primary or window matches)
    active_trend_themes = [
        r for r in themes
        if r["has_direct_evidence"] or r["count_1_2_star_preceding"] > 0 or r["count_1_2_star_recent"] > 0
    ]
    trend_summary_rows = ""
    for r in active_trend_themes:
        p_cnt = r["count_all_reviews_primary"] if is_all else r["count_1_2_star_primary"]
        p_pct = r["pct_of_all_reviews_primary"] if is_all else r["pct_of_1_2_star_primary"]
        pre_cnt = r["count_all_preceding"] if is_all else r["count_1_2_star_preceding"]
        pre_pct = r["rate_all_preceding_pct"] if is_all else r["rate_1_2_star_preceding_pct"]
        rec_cnt = r["count_all_recent"] if is_all else r["count_1_2_star_recent"]
        rec_pct = r["rate_all_recent_pct"] if is_all else r["rate_1_2_star_recent_pct"]
        p_cell = (
            f"<strong>{p_pct:.1f}%</strong> ({p_cnt}/{prim_denom})"
            if p_cnt > 0
            else f"0.0% (0/{prim_denom}) — No direct evidence"
        )
        pre_cell = f"{pre_pct:.1f}% ({pre_cnt}/{pre_denom})" if pre_denom > 0 else "No baseline (n=0)"
        rec_cell = f"<strong>{rec_pct:.1f}% ({rec_cnt}/{rec_denom})</strong>" if rec_denom > 0 else "0/0 (n=0)"
        trend_summary_rows += f"""
        <tr>
          <td><span class="tbl-rank-pill">{r['priority_rank']}</span></td>
          <td><strong>{r['short_name']}</strong></td>
          <td>{p_cell}</td>
          <td>{pre_cell}</td>
          <td>{rec_cell}</td>
          <td><strong>{r['trend_short_display']}</strong></td>
        </tr>
        """
    if not trend_summary_rows:
        trend_summary_rows = f'<tr><td colspan="6" style="text-align:center;">No matching complaint reviews in {win["primary_start_fmt"]} – {win["primary_end_fmt"]}.</td></tr>'

    # Main Report Section 3: Recommended Actions in Priority Order (7 Required Fields) & Owners/Metrics Table
    ev_action_themes = [
        r for r in themes
        if r["has_direct_evidence"] and r["evidence_status"] != "SECONDARY_MULTILABEL_ONLY"
    ]
    action_cards_html = ""
    owners_rows_html = ""
    for r in ev_action_themes:
        sc_str = f"{r['priority_score_1_to_5']:.2f} / 5.0" if r["priority_score_1_to_5"] is not None else "N/A"
        top_q = r["supporting_quotes"][0] if r.get("supporting_quotes") else None
        quote_preview = (
            f'<em>"{top_q["content"][:220]}{"..." if len(top_q["content"]) > 220 else ""}"</em> '
            f'[{top_q["score"]}★, {top_q["date"]}, {top_q["confidence_label"]}]'
            if top_q
            else (r.get("shared_evidence_note") or "No standalone verbatim review excerpt in this period.")
        )
        is_saf = r["recommendation_category"] == "SAFETY_ESCALATION"
        border_col = "#7c3aed" if is_saf else "#1e40af"
        rank_cls = "tbl-rank-pill safety" if is_saf else "tbl-rank-pill"
        action_cards_html += f"""
        <div class="rec-card" style="border-left-color:{border_col};">
          <div class="rec-hdr">
            <span><strong>{r['priority_rank']}: {r['theme_name']}</strong> ({r['evidence_label']})</span>
            <span class="rec-score">Priority Score: {sc_str}</span>
          </div>
          <div class="rec-grid">
            <div><strong>1. User Problem:</strong> {r['user_problem']}</div>
            <div><strong>2. Supporting Review Evidence:</strong> {r['supporting_evidence_summary']}<br/>
                 <span style="color:#334155;">Representative Review Evidence ({win['primary_start_fmt']} – {win['primary_end_fmt']}): {quote_preview}</span></div>
            <div><strong>3. Why It Matters:</strong> {r['why_important']}</div>
            <div><strong>4. First Concrete Action:</strong> {r['first_concrete_action']}</div>
            <div><strong>5. Responsible Team:</strong> {r['owner']} &bull; <strong>Effort/Feasibility:</strong> {r['ease_rationale']}</div>
            <div><strong>6. Validation Metric:</strong> {r['validation_metric']}</div>
            <div><strong>7. Missing Internal Telemetry to Confirm Cause:</strong> {r['missing_telemetry_to_confirm']}</div>
          </div>
        </div>
        """
        owners_rows_html += f"""
        <tr>
          <td style="width:12%;white-space:nowrap;"><span class="{rank_cls}">{r['priority_rank']}</span></td>
          <td style="width:18%;">
            <div style="font-weight:800;color:#0f172a;margin-bottom:3px;">{r['short_name']}</div>
            <span class="tbl-sample-pill">{r['count_1_2_star_primary']}/{dp['count_low_1_2_star']} low-star ({r['pct_of_1_2_star_primary']:.1f}%)</span>
          </td>
          <td style="width:16%;"><span class="tbl-owner-pill">{r['short_owner']}</span></td>
          <td style="width:27%;color:#1e293b;">{r['first_concrete_action']}</td>
          <td style="width:27%;color:#0f172a;font-weight:500;">{r['validation_metric']}</td>
        </tr>
        """

    if not action_cards_html:
        action_cards_html = f"""
        <div class="alert-box">
          <strong>No direct review evidence in this period ({win['primary_start_fmt']} – {win['primary_end_fmt']}).</strong>
          Next investigation step: expand the date range or export historical review logs before ranking recommendations.
        </div>
        """
        owners_rows_html = '<tr><td colspan="5" style="text-align:center;">No confirmed evidence-backed priorities in this period.</td></tr>'

    # Appendix A: Full 10-Theme Detailed Counts & Unconfirmed/Preventative Guardrails
    app_a_rows = ""
    for r in themes:
        sc_str = f"{r['priority_score_1_to_5']:.2f} / 5.0" if r["priority_score_1_to_5"] is not None else "N/A (0 reviews)"
        p_low_str = (
            f"<strong>{r['pct_of_1_2_star_primary']:.1f}%</strong> ({r['count_1_2_star_primary']}/{dp['count_low_1_2_star']})"
            if r["count_1_2_star_primary"] > 0
            else f"0.0% (0/{dp['count_low_1_2_star']}) — No direct review evidence in this period"
        )
        p_all_str = f"{r['pct_of_all_reviews_primary']:.1f}% ({r['count_all_reviews_primary']}/{dp['n_reviews']})"
        pre_str = f"{r['rate_1_2_star_preceding_pct']:.1f}% ({r['count_1_2_star_preceding']}/{dpre['count_low_1_2_star']})"
        rec_str = f"{r['rate_1_2_star_recent_pct']:.1f}% ({r['count_1_2_star_recent']}/{dr['count_low_1_2_star']})"
        app_a_rows += f"""
        <tr>
          <td><span class="tbl-rank-pill">{r['priority_rank']}</span></td>
          <td><strong>{r['theme_name']}</strong><br/><span style="font-size:10px;color:#475569;">{r['evidence_label']}</span></td>
          <td>{p_low_str}</td>
          <td>{p_all_str}</td>
          <td>{pre_str}</td>
          <td>{rec_str}</td>
          <td><strong>{r['trend_short_display']}</strong></td>
          <td><strong>{sc_str}</strong><br/><span style="font-size:9.5px;color:#64748b;">F={r['F_frequency_1_5']}, S={r['S_severity_1_5']}, T={r['T_trend_1_5']}, C={r['C_confidence_1_5']}, E={r['E_ease_1_5_provisional']}</span></td>
        </tr>
        """

    # Appendix C: Scoring Methodology
    comp_rows = "".join(
        f"<tr><td><strong>{c['code']}</strong></td><td><strong>{c['name']}</strong></td><td>{c['weight_pct']}%</td><td>{c['description']}</td></tr>"
        for c in scm["components"]
    )
    safeguard_li = "".join(f"<li>{s}</li>" for s in scm["safeguard_rules"])

    # Appendix D: Clean, Structured Engineering Hypotheses & Telemetry Checks
    app_d_rows = ""
    for r in themes:
        is_saf = r["recommendation_category"] == "SAFETY_ESCALATION"
        rk_cls = "tbl-rank-pill safety" if is_saf else "tbl-rank-pill"
        app_d_rows += f"""
        <tr>
          <td style="width:18%;background:#f8fafc;">
            <span class="{rk_cls}">{r['priority_rank']}</span>
            <div style="font-weight:800;color:#0f172a;margin:4px 0 3px 0;font-size:10.8px;">{r['short_name']}</div>
            <span class="tbl-sample-pill">{r['count_1_2_star_primary']}/{dp['count_low_1_2_star']} low-star ({r['pct_of_1_2_star_primary']:.1f}%)</span>
          </td>
          <td style="width:27%;"><div class="appd-cell symptom">{r['symptom_summary']}</div></td>
          <td style="width:27%;"><div class="appd-cell hypothesis">{r['root_cause_hypothesis']}</div></td>
          <td style="width:28%;"><div class="appd-cell telemetry">{r['missing_telemetry_to_confirm']}</div></td>
        </tr>
        """

    # Appendix E: Version Anomalies
    if versions:
        app_e_rows = "".join(
            f"""
            <tr>
              <td><strong>{v['version_family']}</strong></td>
              <td>{v['n_reviews']}</td>
              <td>{v['min_date']} – {v['max_date']}</td>
              <td>{v['sample_mean_rating']:.2f}★</td>
              <td>{v['count_1_2_star']} ({v['pct_1_2_star']}%)</td>
              <td>{v['crash_launch_count']} ({v['crash_launch_pct_of_ver']}%)</td>
              <td>{v['routing_delay_count']}</td>
              <td>{v['scheduling_noshow_count']}</td>
            </tr>
            """
            for v in versions[:6]
        )
    else:
        app_e_rows = f'<tr><td colspan="8" style="text-align:center;">Insufficient per-version sample size in {win["primary_start_fmt"]} – {win["primary_end_fmt"]} (n={dp["n_reviews"]}).</td></tr>'

    now_li = "".join(f"<li>{i}</li>" for i in ex["what_users_complain_about_now"])
    inc_li = "".join(f"<li>{i}</li>" for i in ex["which_problems_are_increasing"])
    fix_li = "".join(f"<li>{i}</li>" for i in ex["what_to_fix_first"])
    lim_li = "".join(f"<li style='margin-bottom:5px;'>{l}</li>" for l in lims)

    h = sb["histogram_1_to_5"]
    h_sum = sb["histogram_sum"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>MoveInSync Play Store Rating Intelligence Report — {meta['report_id']}</title>
  <style>
    @page {{ size: A4; margin: 12mm 13mm; }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      color: #0f172a;
      margin: 0;
      padding: 16px 22px;
      font-size: 11.5px;
      line-height: 1.45;
      background: #ffffff;
    }}
    .header-bar {{
      background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%);
      color: #ffffff;
      padding: 14px 18px;
      border-radius: 8px;
      margin-bottom: 12px;
    }}
    .header-bar h1 {{ font-size: 18px; margin: 0 0 4px 0; color: #ffffff; }}
    .header-sub {{ font-size: 11px; color: #cbd5e1; }}
    .meta-strip {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      background: #ffffff;
      border: 1px solid #cbd5e1;
      border-left: 5px solid #2563eb;
      border-radius: 8px;
      padding: 10px 14px;
      margin-bottom: 12px;
      font-size: 10.8px;
    }}
    .meta-strip > div {{ min-width: 0; }}
    .meta-lbl {{
      font-size: 10px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      color: #1e3a8a;
      margin-bottom: 3px;
    }}
    .meta-dates {{
      font-weight: 800;
      color: #0f172a;
      font-size: 11.2px;
      margin-bottom: 4px;
    }}
    .meta-pills {{
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      margin-top: 3px;
    }}
    .meta-pill {{
      display: inline-block;
      white-space: nowrap;
      padding: 1.5px 6px;
      border-radius: 999px;
      font-size: 9.6px;
      font-weight: 700;
      background: #eff6ff;
      color: #1e40af;
      border: 1px solid #bfdbfe;
    }}
    .meta-pill.rose {{
      background: #fff1f2;
      color: #be123c;
      border-color: #fecdd3;
    }}
    .meta-pill.slate {{
      background: #f1f5f9;
      color: #334155;
      border-color: #cbd5e1;
    }}
    .kpi-row {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }}
    .kpi-box {{
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      padding: 10px 12px;
      background: #f8fafc;
    }}
    .kpi-box.amber {{ background: #fffbeb; border-color: #fde68a; border-top: 3.5px solid #d97706; }}
    .kpi-box.amber .kpi-lbl {{ color: #b45309; }}
    .kpi-box.amber .kpi-val {{ color: #d97706; }}
    .kpi-box.amber .kpi-sub {{ color: #92400e; }}

    .kpi-box.blue {{ background: #eff6ff; border-color: #bfdbfe; border-top: 3.5px solid #2563eb; }}
    .kpi-box.blue .kpi-lbl {{ color: #1d4ed8; }}
    .kpi-box.blue .kpi-val {{ color: #2563eb; }}
    .kpi-box.blue .kpi-sub {{ color: #1e40af; }}

    .kpi-box.rose {{ background: #fff1f2; border-color: #fecdd3; border-top: 3.5px solid #e11d48; }}
    .kpi-box.rose .kpi-lbl {{ color: #be123c; }}
    .kpi-box.rose .kpi-val {{ color: #e11d48; }}
    .kpi-box.rose .kpi-sub {{ color: #9f1239; }}

    .kpi-box.emerald {{ background: #ecfdf5; border-color: #a7f3d0; border-top: 3.5px solid #059669; }}
    .kpi-box.emerald .kpi-lbl {{ color: #047857; }}
    .kpi-box.emerald .kpi-val {{ color: #059669; }}
    .kpi-box.emerald .kpi-sub {{ color: #065f46; }}

    .kpi-lbl {{ font-size: 9.5px; font-weight: 800; text-transform: uppercase; }}
    .kpi-val {{ font-size: 16.5px; font-weight: 800; margin: 3px 0; }}
    .kpi-sub {{ font-size: 9.8px; font-weight: 600; line-height: 1.4; }}
    h2 {{
      font-size: 13.5px;
      color: #ffffff;
      background: linear-gradient(90deg, #1e3a8a 0%, #2563eb 100%);
      padding: 6px 11px;
      border-radius: 6px;
      margin: 14px 0 8px 0;
    }}
    h3 {{ font-size: 12px; color: #1e3a8a; margin: 10px 0 6px 0; font-weight: 800; }}
    .alert-box {{
      background: #fffbeb;
      border: 1px solid #f59e0b;
      border-left: 4px solid #d97706;
      padding: 9px 12px;
      border-radius: 6px;
      margin-bottom: 12px;
      font-size: 11px;
    }}
    .alert-box ul {{ margin: 4px 0 0 16px; padding: 0; }}
    .exec-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 10px;
    }}
    .exec-card {{
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      padding: 10px 12px;
      background: #f8fafc;
      font-size: 10.6px;
    }}
    .exec-card.sky {{ background: #f0f9ff; border-color: #bae6fd; border-top: 3.5px solid #0284c7; }}
    .exec-card.rose {{ background: #fff1f2; border-color: #fecdd3; border-top: 3.5px solid #e11d48; }}
    .exec-card.violet {{ background: #f5f3ff; border-color: #ddd6fe; border-top: 3.5px solid #7c3aed; }}
    .exec-card h3 {{ margin: 0 0 6px 0; font-size: 11.4px; color: #0f172a; }}
    .exec-card ul {{ margin: 0; padding-left: 15px; }}
    .exec-card li {{ margin-bottom: 7px; line-height: 1.38; }}
    .exec-subline {{
      display: block;
      font-size: 9.9px;
      font-weight: 500;
      color: #475569;
      margin-top: 2px;
    }}
    .grid-3 {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 10px;
    }}
    .prob-card {{
      border: 1px solid #bfdbfe;
      border-top: 4px solid #1d4ed8;
      border-radius: 8px;
      padding: 10px 12px;
      background: linear-gradient(180deg, #eff6ff 0%, #f8fafc 100%);
      page-break-inside: avoid;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .prob-top-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 5px;
    }}
    .prob-rank-pill {{
      background: #1d4ed8;
      color: #ffffff;
      font-size: 9.5px;
      font-weight: 800;
      padding: 2px 7px;
      border-radius: 999px;
      text-transform: uppercase;
    }}
    .prob-score-pill {{
      background: #dbeafe;
      color: #1e3a8a;
      border: 1px solid #93c5fd;
      font-size: 9.5px;
      font-weight: 800;
      padding: 2px 7px;
      border-radius: 999px;
    }}
    .prob-title {{ font-size: 11.6px; font-weight: 800; color: #0f172a; margin: 2px 0 6px 0; line-height: 1.3; }}
    .prob-stat-box {{
      background: #ffffff;
      border: 1px solid #dbeafe;
      border-radius: 6px;
      padding: 5px 8px;
      font-size: 10px;
      color: #1e293b;
      margin-bottom: 6px;
      line-height: 1.45;
    }}
    .prob-desc {{ font-size: 10.1px; color: #334155; margin-bottom: 7px; line-height: 1.4; }}
    .prob-meta {{ margin-top: auto; }}
    .owner-chip {{
      display: inline-block;
      background: #e0e7ff;
      color: #1e3a8a;
      border: 1px solid #c7d2fe;
      font-weight: 700;
      font-size: 9.6px;
      padding: 2px 8px;
      border-radius: 5px;
    }}
    .safety-box {{
      border: 1px solid #cbd5e1;
      border-left: 5px solid #64748b;
      background: #f8fafc;
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 10.6px;
      margin-bottom: 12px;
      page-break-inside: avoid;
    }}
    .safety-box.active {{
      border-color: #c4b5fd;
      border-left-color: #7c3aed;
      background: linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%);
      color: #2e1065;
    }}
    .safety-hdr {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 5px;
    }}
    .safety-hdr-left {{
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .safety-title {{ font-weight: 800; font-size: 11.5px; color: #3b0764; }}
    .safety-badge {{
      background: #7c3aed;
      color: #ffffff;
      padding: 2px 9px;
      border-radius: 999px;
      font-size: 9.6px;
      font-weight: 800;
    }}
    .safety-count-pill {{
      background: #ffffff;
      color: #5b21b6;
      border: 1px solid #c4b5fd;
      padding: 2px 9px;
      border-radius: 999px;
      font-size: 9.8px;
      font-weight: 800;
    }}
    .safety-note {{ font-size: 10.2px; color: #4c1d95; margin-bottom: 6px; font-weight: 500; }}
    .safety-body-card {{
      background: #ffffff;
      border: 1px solid #ddd6fe;
      border-radius: 6px;
      padding: 7px 10px;
      font-size: 10.2px;
      color: #1e293b;
    }}
    .safety-action-row {{
      line-height: 1.45;
      margin-bottom: 5px;
    }}
    .safety-owner-row {{
      padding-top: 5px;
      border-top: 1px dashed #ddd6fe;
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 8px 0 12px 0;
      font-size: 10.4px;
    }}
    th, td {{
      border: 1px solid #cbd5e1;
      padding: 6px 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{ background: #e2e8f0; font-weight: 800; color: #0f172a; }}
    .tbl-rank-pill {{
      display: inline-block;
      white-space: nowrap;
      background: #dbeafe;
      color: #1e40af;
      border: 1px solid #93c5fd;
      font-weight: 800;
      font-size: 9.5px;
      padding: 2px 7px;
      border-radius: 999px;
    }}
    .tbl-rank-pill.safety {{
      background: #ede9fe;
      color: #5b21b6;
      border-color: #c4b5fd;
    }}
    .tbl-sample-pill {{
      display: inline-block;
      white-space: nowrap;
      background: #f1f5f9;
      color: #334155;
      border: 1px solid #cbd5e1;
      font-size: 9.3px;
      font-weight: 700;
      padding: 1.5px 6px;
      border-radius: 4px;
    }}
    .tbl-owner-pill {{
      display: inline-block;
      background: #eff6ff;
      color: #1e3a8a;
      border: 1px solid #bfdbfe;
      font-weight: 700;
      font-size: 9.6px;
      padding: 2px 7px;
      border-radius: 5px;
    }}
    .appd-cell {{
      padding: 5px 7px;
      border-radius: 5px;
      line-height: 1.42;
      font-size: 10.1px;
    }}
    .appd-cell.symptom {{ background: #fff1f2; border-left: 3px solid #e11d48; color: #1e293b; }}
    .appd-cell.hypothesis {{ background: #fffbeb; border-left: 3px solid #d97706; color: #1e293b; }}
    .appd-cell.telemetry {{ background: #ecfdf5; border-left: 3px solid #059669; color: #0f172a; font-weight: 500; }}
    .limitations-box {{
      background: #f8fafc;
      border: 1px solid #cbd5e1;
      border-left: 4px solid #2563eb;
      border-radius: 7px;
      padding: 9px 14px;
      margin: 6px 0 12px 0;
    }}
    .limitations-box ul {{ margin: 0; padding-left: 16px; font-size: 10.6px; line-height: 1.5; }}
    .charts-2col {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin: 8px 0 12px 0;
      page-break-inside: avoid;
    }}
    .chart-wrap {{
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      padding: 6px;
      text-align: center;
      background: #ffffff;
    }}
    .chart-wrap img {{ max-width: 100%; height: auto; max-height: 220px; }}
    .rec-card {{
      border: 1px solid #cbd5e1;
      border-left: 4px solid #1e40af;
      border-radius: 6px;
      padding: 9px 12px;
      margin-bottom: 9px;
      background: #ffffff;
      page-break-inside: avoid;
    }}
    .rec-hdr {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid #e2e8f0;
      padding-bottom: 4px;
      margin-bottom: 6px;
      font-size: 11.8px;
      color: #1e3a8a;
    }}
    .rec-score {{
      background: #dbeafe;
      color: #1e40af;
      font-weight: 800;
      padding: 2px 7px;
      border-radius: 999px;
      font-size: 10.5px;
    }}
    .rec-grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 3px;
      font-size: 10.6px;
    }}
    .page-break {{ page-break-before: always; }}
    .footer-note {{
      margin-top: 16px;
      padding-top: 8px;
      border-top: 1px solid #cbd5e1;
      font-size: 10px;
      color: #64748b;
      text-align: center;
    }}
  </style>
</head>
<body>
  <div class="header-bar">
    <h1>MoveInSync (com.moveinsync.ets) — Play Store Rating Intelligence Report</h1>
    <div class="header-sub">
      Report ID: <strong>{meta['report_id']}</strong> &bull; Generated: {meta['generated_at_utc']} &bull;
      Snapshot: {meta['snapshot_file']} (Retrieved: {meta['snapshot_retrieved_utc']})
    </div>
  </div>

  <div class="meta-strip">
    <div>
      <div class="meta-lbl">Primary Analysis Window</div>
      <div class="meta-dates">{win['primary_start_fmt']} – {win['primary_end_fmt']}</div>
      <div class="meta-pills">
        <span class="meta-pill slate">{win['primary_days']} days</span>
        <span class="meta-pill">N = {dp['n_reviews']:,}</span>
        <span class="meta-pill rose">1–2★ = {dp['count_low_1_2_star']:,}</span>
      </div>
    </div>
    <div>
      <div class="meta-lbl">Recent Comparison Window</div>
      <div class="meta-dates">{win['recent_start_fmt']} – {win['recent_end_fmt']}</div>
      <div class="meta-pills">
        <span class="meta-pill">n = {dr['n_reviews']:,}</span>
        <span class="meta-pill rose">1–2★ = {dr['count_low_1_2_star']:,}</span>
      </div>
    </div>
    <div>
      <div class="meta-lbl">Preceding Comparison Window</div>
      <div class="meta-dates">{win['preceding_start_fmt']} – {win['preceding_end_fmt']}</div>
      <div class="meta-pills">
        <span class="meta-pill">n = {dpre['n_reviews']:,}</span>
        <span class="meta-pill rose">1–2★ = {dpre['count_low_1_2_star']:,}</span>
      </div>
    </div>
    <div>
      <div class="meta-lbl">Review Focus &amp; Report ID</div>
      <div class="meta-dates">{focus_col_lbl}</div>
      <div class="meta-pills">
        <span class="meta-pill slate">{meta['report_id']}</span>
      </div>
    </div>
  </div>

  {warn_html}

  <div class="kpi-row">
    <div class="kpi-box amber">
      <div class="kpi-lbl">Official Play Store Rating</div>
      <div class="kpi-val">{sb['exact_unrounded_score']:.2f}★</div>
      <div class="kpi-sub">{sb['ratings_total_reported']:,} ratings | {sb['written_reviews_total_reported']:,} written</div>
    </div>
    <div class="kpi-box blue">
      <div class="kpi-lbl">Selected Window Sample Mean</div>
      <div class="kpi-val">{f"{dp['sample_mean_rating']:.2f}★" if dp['is_representative'] and dp['sample_mean_rating'] is not None else "Non-Repr."}</div>
      <div class="kpi-sub">{dp['mean_rating_display']}</div>
    </div>
    <div class="kpi-box rose">
      <div class="kpi-lbl">Low-Star (1–2★) Reviews</div>
      <div class="kpi-val">{dp['count_low_1_2_star']:,} ({dp['pct_low_1_2_star']}%)</div>
      <div class="kpi-sub">Primary: {dp['count_low_1_2_star']}/{dp['n_reviews']}<br/>Recent: {dr['count_low_1_2_star']}/{dr['n_reviews']}</div>
    </div>
    <div class="kpi-box emerald">
      <div class="kpi-lbl">1–2★ Developer Reply Rate</div>
      <div class="kpi-val">{dp['dev_reply_rate_1_2_star_pct']}%</div>
      <div class="kpi-sub">Primary: {dp['dev_reply_count_1_2_star']}/{dp['count_low_1_2_star']}<br/>Recent: {dr['dev_reply_count_1_2_star']}/{dr['count_low_1_2_star']}</div>
    </div>
  </div>

  <h2>1. Executive Summary &amp; Three Most Important Evidence-Backed Problems</h2>
  <div class="exec-grid">
    <div class="exec-card sky"><h3>What Are Users Complaining About?</h3><ul>{now_li}</ul></div>
    <div class="exec-card rose"><h3>Which Problems Are Increasing?</h3><ul>{inc_li}</ul></div>
    <div class="exec-card violet"><h3>What Should MoveInSync Fix First?</h3><ul>{fix_li}</ul></div>
  </div>

  <h3>Three Most Important Evidence-Backed Problems in Selected Period</h3>
  {top3_cards_html}
  {saf_html}

  <h2>2. Recent-versus-Preceding Trend Summary &amp; Rating Distribution</h2>
  <table>
    <thead>
      <tr>
        <th>Cohort / Window</th>
        <th>Date Range</th>
        <th>Sample Size (n)</th>
        <th>Mean Rating &amp; Status</th>
        <th>1★</th>
        <th>2★</th>
        <th>3★</th>
        <th>4★</th>
        <th>5★</th>
        <th>Low-Star (1–2★)</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>Official Store Baseline</strong></td>
        <td>All-Time (12 Oct 2026)</td>
        <td>{h_sum:,} ratings</td>
        <td><strong>{sb['exact_unrounded_score']:.2f}★ (Official Store)</strong></td>
        <td>{h[0]:,} ({h[0]/h_sum*100:.1f}%)</td>
        <td>{h[1]:,} ({h[1]/h_sum*100:.1f}%)</td>
        <td>{h[2]:,} ({h[2]/h_sum*100:.1f}%)</td>
        <td>{h[3]:,} ({h[3]/h_sum*100:.1f}%)</td>
        <td>{h[4]:,} ({h[4]/h_sum*100:.1f}%)</td>
        <td>{h[0]+h[1]:,} ({(h[0]+h[1])/h_sum*100:.1f}%)</td>
      </tr>
      <tr style="background:#eff6ff;font-weight:700;">
        <td>Selected Primary Window</td>
        <td>{dp['date_window']}</td>
        <td>n={dp['n_reviews']:,}</td>
        <td>{dp['mean_rating_display']}</td>
        <td>{dp['count_1_star']} ({dp['pct_1_star']}%)</td>
        <td>{dp['count_2_star']} ({dp['pct_2_star']}%)</td>
        <td>{dp['count_3_star']} ({dp['pct_3_star']}%)</td>
        <td>{dp['count_4_star']} ({dp['pct_4_star']}%)</td>
        <td>{dp['count_5_star']} ({dp['pct_5_star']}%)</td>
        <td>{dp['pct_low_1_2_star']}% ({dp['count_low_1_2_star']}/{dp['n_reviews']})</td>
      </tr>
      <tr>
        <td>Recent Comparison Window</td>
        <td>{dr['date_window']}</td>
        <td>n={dr['n_reviews']:,}</td>
        <td>{dr['mean_rating_display']}</td>
        <td>{dr['count_1_star']} ({dr['pct_1_star']}%)</td>
        <td>{dr['count_2_star']} ({dr['pct_2_star']}%)</td>
        <td>{dr['count_3_star']} ({dr['pct_3_star']}%)</td>
        <td>{dr['count_4_star']} ({dr['pct_4_star']}%)</td>
        <td>{dr['count_5_star']} ({dr['pct_5_star']}%)</td>
        <td>{dr['pct_low_1_2_star']}% ({dr['count_low_1_2_star']}/{dr['n_reviews']})</td>
      </tr>
      <tr>
        <td>Preceding Comparison Window</td>
        <td>{dpre['date_window']}</td>
        <td>n={dpre['n_reviews']:,}</td>
        <td>{dpre['mean_rating_display']}</td>
        <td>{dpre['count_1_star']} ({dpre['pct_1_star']}%)</td>
        <td>{dpre['count_2_star']} ({dpre['pct_2_star']}%)</td>
        <td>{dpre['count_3_star']} ({dpre['pct_3_star']}%)</td>
        <td>{dpre['count_4_star']} ({dpre['pct_4_star']}%)</td>
        <td>{dpre['count_5_star']} ({dpre['pct_5_star']}%)</td>
        <td>{dpre['pct_low_1_2_star']}% ({dpre['count_low_1_2_star']}/{dpre['n_reviews']})</td>
      </tr>
    </tbody>
  </table>

  <div class="charts-2col">
    <div class="chart-wrap"><img src="{charts['chart_01_distribution']}" alt="Rating Distribution"/></div>
    <div class="chart-wrap"><img src="{charts['chart_02_monthly_trend']}" alt="Monthly Volume and Low-Star Trend"/></div>
  </div>
  <div class="charts-2col">
    <div class="chart-wrap"><img src="{charts['chart_03_themes_primary']}" alt="Top Complaint Themes"/></div>
    <div class="chart-wrap"><img src="{charts['chart_04_trend_deltas']}" alt="Recent vs Preceding Trend Shifts"/></div>
  </div>

  <h3>Recent vs. Preceding Complaint Trend Summary ({focus_col_lbl})</h3>
  <table>
    <thead>
      <tr>
        <th>Priority Rank</th>
        <th>Complaint Theme</th>
        <th>Primary Window ({focus_col_lbl} k/n)</th>
        <th>Preceding ({win['preceding_start_fmt']} – {win['preceding_end_fmt']})</th>
        <th>Recent ({win['recent_start_fmt']} – {win['recent_end_fmt']})</th>
        <th>Percentage-Point Change (pp) / Status</th>
      </tr>
    </thead>
    <tbody>{trend_summary_rows}</tbody>
  </table>

  <h2>3. Recommended Actions in Priority Order</h2>
  <div class="chart-wrap" style="margin-bottom:10px;">
    <img src="{charts['chart_05_priority_matrix']}" alt="Evidence-Backed Priority Matrix" style="max-height:230px;"/>
  </div>
  {action_cards_html}

  <h2>4. Owners &amp; Validation Metrics Summary</h2>
  <table>
    <thead>
      <tr>
        <th>Priority Rank</th>
        <th>Complaint Theme &amp; Sample (k/n)</th>
        <th>Responsible Team</th>
        <th>First Concrete Action</th>
        <th>Validation Metric</th>
      </tr>
    </thead>
    <tbody>{owners_rows_html}</tbody>
  </table>

  <h2>5. Data Coverage &amp; Limitations</h2>
  <div class="limitations-box">
    <ul>{lim_li}</ul>
  </div>

  <!-- APPENDIX -->
  <div class="page-break"></div>
  <h2>Appendix A: Detailed Theme Counts &amp; Preventative Guardrails</h2>
  <table>
    <thead>
      <tr>
        <th>Priority Rank</th>
        <th>Complaint Theme &amp; Status</th>
        <th>Primary 1–2★ (k/n)</th>
        <th>Primary All (k/n)</th>
        <th>Preceding 1–2★ (k/n)</th>
        <th>Recent 1–2★ (k/n)</th>
        <th>Trend Shift / Safeguard</th>
        <th>Priority Score &amp; Factors</th>
      </tr>
    </thead>
    <tbody>{app_a_rows}</tbody>
  </table>

  <h2>Appendix B: Priority Scoring Methodology &amp; Weights</h2>
  <p style="font-size:10.5px;margin:0 0 6px 0;"><strong>Formula:</strong> <code>{scm['formula_expression']}</code></p>
  <table>
    <thead>
      <tr><th>Factor</th><th>Component</th><th>Weight</th><th>Scoring &amp; Safeguard Definition</th></tr>
    </thead>
    <tbody>{comp_rows}</tbody>
  </table>
  <ul style="font-size:10.3px;margin:4px 0 10px 18px;padding:0;">{safeguard_li}</ul>

  <h2>Appendix C: Engineering Root-Cause Hypotheses &amp; Internal Telemetry Checks</h2>
  <table>
    <thead>
      <tr>
        <th>Rank &amp; Theme</th>
        <th>Observed User Symptoms</th>
        <th>Engineering Root-Cause Hypothesis (Unconfirmed)</th>
        <th>Required Internal Telemetry Check</th>
      </tr>
    </thead>
    <tbody>{app_d_rows}</tbody>
  </table>

  <h2>Appendix D: App-Version Anomaly Analysis ({win['primary_start_fmt']} – {win['primary_end_fmt']})</h2>
  <table>
    <thead>
      <tr>
        <th>Version Family</th>
        <th>Reviews (n)</th>
        <th>Observed Dates</th>
        <th>Sample Mean</th>
        <th>Low-Star 1–2★ (%)</th>
        <th>Crash/Launch (% of Version)</th>
        <th>Routing Delay</th>
        <th>Schedule / No-Show</th>
      </tr>
    </thead>
    <tbody>{app_e_rows}</tbody>
  </table>

  <div class="footer-note">
    MoveInSync (com.moveinsync.ets) — Play Store Rating Intelligence Report ({meta['report_id']})
  </div>
</body>
</html>"""


def render_pdf_from_report(rep: Dict[str, Any], pdf_out_path: Path) -> bool:
    """
    Renders a clean PDF document from the shared report payload using headless Microsoft Edge
    (or Chrome) so the generated PDF matches the standalone HTML export with zero undefined values.
    """
    pdf_out_path.parent.mkdir(parents=True, exist_ok=True)
    html_str = build_standalone_export_html(rep)
    temp_html_path = pdf_out_path.with_suffix(".temp_print.html")
    temp_html_path.write_text(html_str, encoding="utf-8")

    browser_candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    browser_exe = next((b for b in browser_candidates if b.exists()), None)
    if browser_exe is None:
        if temp_html_path.exists():
            temp_html_path.unlink(missing_ok=True)
        return False

    try:
        file_uri = temp_html_path.resolve().as_uri()
        cmd = [
            str(browser_exe),
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={str(pdf_out_path.resolve())}",
            file_uri,
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
        return pdf_out_path.exists() and pdf_out_path.stat().st_size > 0
    except Exception:
        return False
    finally:
        if temp_html_path.exists():
            temp_html_path.unlink(missing_ok=True)
