"""
Step 1: Compliant Public Data Collection & Audit Manifest Logger
Fetches official MoveInSync (com.moveinsync.ets) metadata and public Play Store reviews
across Cohort A (Unfiltered Chronological) and Cohort B (Star-Stratified Chronological),
plus a multilingual discovery pass. Preserves immutable raw JSONL snapshots and run manifests.
"""

import datetime
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from google_play_scraper import Sort, app, reviews
from google_play_scraper.constants.regex import Regex
from google_play_scraper.constants.request import Formats
from google_play_scraper.utils.request import get

APP_ID = "com.moveinsync.ets"
DEFAULT_COUNTRY = "in"
DEFAULT_LANG = "en"

PRIMARY_START = datetime.datetime(2025, 9, 1, 0, 0, 0)
PRIMARY_END = datetime.datetime(2026, 9, 30, 23, 59, 59)
RECENT_90D_START = datetime.datetime(2026, 7, 3, 0, 0, 0)
PRIOR_90D_START = datetime.datetime(2026, 4, 4, 0, 0, 0)
PRIOR_90D_END = datetime.datetime(2026, 7, 2, 23, 59, 59)


def fetch_raw_store_blocks(app_id: str, lang: str = "en", country: str = "in") -> Dict[str, Any]:
    """Extracts verbatim ds:5 and ds:9 rating blocks directly from Google Play HTML."""
    url = Formats.Detail.build(app_id=app_id, lang=lang, country=country)
    dom = get(url)
    matches = Regex.SCRIPT.findall(dom)
    dataset = {}
    for match in matches:
        k = Regex.KEY.findall(match)
        v = Regex.VALUE.findall(match)
        if k and v:
            try:
                dataset[k[0]] = json.loads(v[0])
            except Exception:
                pass

    b51 = dataset.get("ds:5", [None, [None, None, {}]])[1][2][51]
    hist_5 = [b51[1][i][1] for i in range(1, 6)] if b51 and b51[1] else []

    b52 = None
    hist_9 = []
    try:
        ds9 = dataset.get("ds:9", [])
        b52 = ds9[1][2][0]["52"]
        hist_9 = [b52[1][i][1] for i in range(1, 6)]
    except Exception:
        pass

    return {
        "source_url": url,
        "retrieved_at_ist": datetime.datetime.now().isoformat(),
        "ds5_raw_block_51": b51,
        "ds5_score_display": b51[0][0] if b51 else None,
        "ds5_score_exact": b51[0][1] if b51 else None,
        "ds5_histogram_1_to_5": hist_5,
        "ds5_histogram_sum": sum(hist_5) if hist_5 else None,
        "ds5_reported_ratings_total": b51[2][1] if b51 and b51[2] else None,
        "ds5_discrepancy_total_minus_bucket_sum": (
            (b51[2][1] - sum(hist_5)) if (b51 and b51[2] and hist_5) else None
        ),
        "ds5_reported_written_reviews": b51[3][1] if b51 and b51[3] else None,
        "ds9_raw_block_52": b52,
        "ds9_histogram_1_to_5": hist_9,
        "ds9_histogram_sum": sum(hist_9) if hist_9 else None,
        "ds9_reported_ratings_total": b52[2][1] if b52 and b52[2] else None,
        "ds9_reported_written_reviews": b52[3][1] if b52 and b52[3] else None,
    }


def serialize_review(r: Dict[str, Any], slice_name: str, lang: str, country: str) -> Dict[str, Any]:
    """Converts datetime fields in review dict to ISO strings and attaches provenance."""
    out = dict(r)
    for dt_key in ("at", "repliedAt"):
        if isinstance(out.get(dt_key), datetime.datetime):
            out[dt_key] = out[dt_key].isoformat()
    out["_slice_name"] = slice_name
    out["_query_lang"] = lang
    out["_query_country"] = country
    return out


def fetch_review_slice(
    app_id: str,
    slice_name: str,
    lang: str,
    country: str,
    sort: Sort,
    filter_score_with: Optional[int],
    stop_before_date: Optional[datetime.datetime],
    max_reviews: int = 3500,
    batch_size: int = 200,
    sleep_sec: float = 0.25,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Paginates through a specific review query slice with retry and audit logging."""
    collected: List[Dict[str, Any]] = []
    continuation_token = None
    pages_fetched = 0
    termination_reason = "unknown"
    errors: List[str] = []
    started_at = datetime.datetime.now().isoformat()

    while len(collected) < max_reviews:
        count_to_fetch = min(batch_size, max_reviews - len(collected))
        batch = []
        for attempt in range(3):
            try:
                if continuation_token is None and pages_fetched == 0:
                    batch, continuation_token = reviews(
                        app_id,
                        lang=lang,
                        country=country,
                        sort=sort,
                        count=count_to_fetch,
                        filter_score_with=filter_score_with,
                    )
                else:
                    batch, continuation_token = reviews(
                        app_id,
                        continuation_token=continuation_token,
                    )
                break
            except Exception as e:
                err_msg = f"Attempt {attempt + 1} error on page {pages_fetched + 1}: {e}"
                errors.append(err_msg)
                time.sleep(1.5 * (attempt + 1))
        else:
            termination_reason = "http_error_after_retries"
            break

        pages_fetched += 1
        if not batch:
            termination_reason = "empty_batch_exhausted"
            break

        collected.extend(batch)

        # Check date cutoff when sorting by NEWEST
        if stop_before_date is not None and sort == Sort.NEWEST:
            oldest_in_batch = min(
                (item["at"] for item in batch if isinstance(item.get("at"), datetime.datetime)),
                default=None,
            )
            if oldest_in_batch is not None and oldest_in_batch < stop_before_date:
                termination_reason = f"reached_date_cutoff_{stop_before_date.strftime('%Y-%m-%d')}"
                break

        if continuation_token is None or getattr(continuation_token, "token", True) is None:
            termination_reason = "continuation_token_exhausted"
            break

        if len(collected) >= max_reviews:
            termination_reason = "max_reviews_cap_reached"
            break

        time.sleep(sleep_sec)

    # Compute slice date and window statistics
    dates = [r["at"] for r in collected if isinstance(r.get("at"), datetime.datetime)]
    n_primary = sum(1 for d in dates if PRIMARY_START <= d <= PRIMARY_END)
    n_recent_90d = sum(1 for d in dates if RECENT_90D_START <= d <= PRIMARY_END)
    n_prior_90d = sum(1 for d in dates if PRIOR_90D_START <= d <= PRIOR_90D_END)
    n_oct_2026 = sum(1 for d in dates if d > PRIMARY_END)
    n_historical = sum(1 for d in dates if d < PRIMARY_START)

    serialized = [serialize_review(r, slice_name, lang, country) for r in collected]
    slice_stats = {
        "slice_name": slice_name,
        "lang": lang,
        "country": country,
        "sort": sort.name if hasattr(sort, "name") else str(sort),
        "filter_score_with": filter_score_with,
        "stop_before_date": stop_before_date.isoformat() if stop_before_date else None,
        "max_reviews_cap": max_reviews,
        "started_at_ist": started_at,
        "completed_at_ist": datetime.datetime.now().isoformat(),
        "pages_fetched": pages_fetched,
        "total_fetched": len(collected),
        "unique_review_ids_in_slice": len({r["reviewId"] for r in collected if r.get("reviewId")}),
        "min_at": min(dates).isoformat() if dates else None,
        "max_at": max(dates).isoformat() if dates else None,
        "count_primary_window_2025_09_to_2026_09": n_primary,
        "count_recent_90d_2026_07_03_to_2026_09_30": n_recent_90d,
        "count_prior_90d_2026_04_04_to_2026_07_02": n_prior_90d,
        "count_post_window_oct_2026": n_oct_2026,
        "count_historical_pre_2025_09": n_historical,
        "termination_reason": termination_reason,
        "errors": errors,
    }
    print(
        f"[{slice_name}] Fetched {len(collected)} reviews ({pages_fetched} pages) | "
        f"Range: {slice_stats['min_at']} .. {slice_stats['max_at']} | "
        f"Primary(Sept25-Sept26): {n_primary} | Termination: {termination_reason}"
    )
    return serialized, slice_stats


def run_collection(base_dir: Path, run_id: Optional[str] = None) -> str:
    """Executes full data collection and saves raw JSONL and manifest."""
    if run_id is None:
        run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    raw_dir = base_dir / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== Starting Data Collection Run: {run_id} ===")

    # 1. Fetch store metadata & raw ds:5 / ds:9 blocks
    app_info = app(APP_ID, lang=DEFAULT_LANG, country=DEFAULT_COUNTRY)
    raw_blocks = fetch_raw_store_blocks(APP_ID, lang=DEFAULT_LANG, country=DEFAULT_COUNTRY)
    us_blocks = fetch_raw_store_blocks(APP_ID, lang=DEFAULT_LANG, country="us")

    metadata_payload = {
        "run_id": run_id,
        "app_id": APP_ID,
        "retrieved_at_ist": datetime.datetime.now().isoformat(),
        "google_play_scraper_app_info": {
            k: app_info.get(k)
            for k in [
                "title",
                "appId",
                "url",
                "score",
                "ratings",
                "reviews",
                "histogram",
                "installs",
                "minInstalls",
                "realInstalls",
                "version",
                "updated",
                "lastUpdatedOn",
                "developer",
                "developerId",
                "developerEmail",
                "developerWebsite",
                "summary",
            ]
        },
        "raw_html_audit_india_locale": raw_blocks,
        "raw_html_audit_us_locale": us_blocks,
    }

    meta_path = raw_dir / f"app_metadata_{run_id}.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata_payload, f, indent=2, ensure_ascii=False)
    # Also write latest pointer copy for deterministic downstream loading
    with open(raw_dir / "app_metadata_latest.json", "w", encoding="utf-8") as f:
        json.dump(metadata_payload, f, indent=2, ensure_ascii=False)

    # 2. Define collection slices
    # Cutoff set to 2025-07-01 for primary slices so Sept 2025 - Sept 2026 is 100% covered
    # and pre-Sept 2025 historical context is also captured and quarantined.
    slices_config = [
        # Cohort A: Unfiltered Chronological (NEWEST)
        ("cohort_a_unfiltered_newest", "en", "in", Sort.NEWEST, None, datetime.datetime(2025, 7, 1), 4000),
        # Cohort B: Star-Stratified Chronological (NEWEST) for 1..5 stars
        ("cohort_b_score_1_newest", "en", "in", Sort.NEWEST, 1, datetime.datetime(2024, 9, 1), 3000),
        ("cohort_b_score_2_newest", "en", "in", Sort.NEWEST, 2, datetime.datetime(2024, 9, 1), 1500),
        ("cohort_b_score_3_newest", "en", "in", Sort.NEWEST, 3, datetime.datetime(2024, 9, 1), 1500),
        ("cohort_b_score_4_newest", "en", "in", Sort.NEWEST, 4, datetime.datetime(2025, 7, 1), 1500),
        ("cohort_b_score_5_newest", "en", "in", Sort.NEWEST, 5, datetime.datetime(2025, 7, 1), 3000),
        # Multiplex / Multilingual Discovery Slices (India locale)
        ("multilingual_hi_newest", "hi", "in", Sort.NEWEST, None, datetime.datetime(2025, 9, 1), 200),
        ("multilingual_kn_newest", "kn", "in", Sort.NEWEST, None, datetime.datetime(2025, 9, 1), 200),
        ("multilingual_ta_newest", "ta", "in", Sort.NEWEST, None, datetime.datetime(2025, 9, 1), 200),
        ("multilingual_te_newest", "te", "in", Sort.NEWEST, None, datetime.datetime(2025, 9, 1), 200),
    ]

    all_raw_records: List[Dict[str, Any]] = []
    slice_manifests: List[Dict[str, Any]] = []

    for s_name, lang, country, sort_mode, score_filter, cutoff_dt, max_rev in slices_config:
        records, stats = fetch_review_slice(
            app_id=APP_ID,
            slice_name=s_name,
            lang=lang,
            country=country,
            sort=sort_mode,
            filter_score_with=score_filter,
            stop_before_date=cutoff_dt,
            max_reviews=max_rev,
        )
        all_raw_records.extend(records)
        slice_manifests.append(stats)

    # Save immutable JSONL snapshot
    jsonl_path = raw_dir / f"reviews_raw_{run_id}.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for rec in all_raw_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Save latest JSONL copy for reproducible offline reruns
    latest_jsonl_path = raw_dir / "reviews_raw_latest.jsonl"
    with open(latest_jsonl_path, "w", encoding="utf-8") as f:
        for rec in all_raw_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    manifest_data = {
        "run_id": run_id,
        "app_id": APP_ID,
        "generated_at_ist": datetime.datetime.now().isoformat(),
        "primary_window": {
            "start": PRIMARY_START.isoformat(),
            "end": PRIMARY_END.isoformat(),
        },
        "recent_90d_window": {
            "start": RECENT_90D_START.isoformat(),
            "end": PRIMARY_END.isoformat(),
        },
        "prior_90d_window": {
            "start": PRIOR_90D_START.isoformat(),
            "end": PRIOR_90D_END.isoformat(),
        },
        "total_raw_records_across_slices": len(all_raw_records),
        "unique_review_ids_across_all_slices": len(
            {r["reviewId"] for r in all_raw_records if r.get("reviewId")}
        ),
        "slices": slice_manifests,
    }

    manifest_path = raw_dir / f"manifest_{run_id}.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)
    with open(raw_dir / "manifest_latest.json", "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)

    print(
        f"=== Collection Complete: {len(all_raw_records)} raw rows "
        f"({manifest_data['unique_review_ids_across_all_slices']} unique reviewIds) ==="
    )
    return run_id


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    run_collection(project_root)
