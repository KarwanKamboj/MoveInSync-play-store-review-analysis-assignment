"""
Dynamic Play Store Rating Intelligence & Report Generation Web Server for MoveInSync (com.moveinsync.ets).

Provides a zero-external-dependency HTTP server (built on Python's standard ThreadingHTTPServer)
with REST API endpoints that execute actual backend analysis, dynamic window filtering,
coverage auditing, priority recalculation, and Matplotlib chart + PDF generation:

  - GET  /                          -> Serves the dynamic Rating Intelligence web application (index.html)
  - GET  /api/init                  -> Returns available raw snapshots, report history, and initial default report
  - POST /api/generate              -> Executes generate_dynamic_report() with user-selected options
  - GET  /api/report/<report_id>    -> Reloads a previously generated report bundle from disk (validating schema version)
  - GET  /api/export/<report_id>    -> Downloads a standalone, self-contained HTML report
  - GET  /api/pdf/<report_id>       -> Generates and downloads a clean, executive-friendly PDF report

Usage:
  python app.py [--port 8000]
"""

import argparse
import importlib
import json
import mimetypes
import traceback
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

import src.dynamic_engine as dynamic_engine
import src.preprocess_and_classify as preprocess_and_classify

BASE_DIR = Path(__file__).resolve().parent

# Cache the most recent default report in memory so initial page load is fast,
# while validating methodology_version and module mtime on every request.
_DEFAULT_REPORT_CACHE: Dict[str, Any] = {}
_LAST_ENGINE_MTIME: float = 0.0


def _ensure_fresh_engine() -> None:
    """
    Hot-reloads src.preprocess_and_classify and src.dynamic_engine if their files on disk
    were updated after server startup, preventing stale in-memory code from serving old schemas.
    """
    global _LAST_ENGINE_MTIME, _DEFAULT_REPORT_CACHE
    eng_file = BASE_DIR / "src" / "dynamic_engine.py"
    cls_file = BASE_DIR / "src" / "preprocess_and_classify.py"
    cur_mtime = max(
        eng_file.stat().st_mtime if eng_file.exists() else 0.0,
        cls_file.stat().st_mtime if cls_file.exists() else 0.0,
    )
    if _LAST_ENGINE_MTIME == 0.0:
        _LAST_ENGINE_MTIME = cur_mtime
    elif cur_mtime > _LAST_ENGINE_MTIME:
        importlib.reload(preprocess_and_classify)
        importlib.reload(dynamic_engine)
        _LAST_ENGINE_MTIME = cur_mtime
        _DEFAULT_REPORT_CACHE = {}


def _is_valid_current_report(rep: Dict[str, Any]) -> bool:
    """Checks that a cached report payload matches the current shared analysis schema version."""
    if not isinstance(rep, dict):
        return False
    ver = rep.get("report_metadata", {}).get("methodology_version")
    return ver == dynamic_engine.METHODOLOGY_VERSION


def get_or_create_default_report() -> Dict[str, Any]:
    global _DEFAULT_REPORT_CACHE
    _ensure_fresh_engine()
    if _DEFAULT_REPORT_CACHE and _is_valid_current_report(_DEFAULT_REPORT_CACHE):
        return _DEFAULT_REPORT_CACHE

    hist_path = BASE_DIR / "reports" / "generated" / "report_history.json"
    if hist_path.exists():
        try:
            with open(hist_path, "r", encoding="utf-8") as f:
                hist = json.load(f)
            for item in hist:
                if (
                    item.get("primary_period_mode") == "12m"
                    and item.get("trend_comparison_mode") == "3m"
                    and item.get("review_focus") == "negative"
                ):
                    rep_json = BASE_DIR / "reports" / "generated" / item["report_id"] / "report_data.json"
                    if rep_json.exists():
                        with open(rep_json, "r", encoding="utf-8") as rf:
                            candidate = json.load(rf)
                        if _is_valid_current_report(candidate):
                            _DEFAULT_REPORT_CACHE = candidate
                            return _DEFAULT_REPORT_CACHE
        except Exception:
            pass

    _DEFAULT_REPORT_CACHE = dynamic_engine.generate_dynamic_report(
        BASE_DIR,
        primary_period_mode="12m",
        trend_comparison_mode="3m",
        review_focus="negative",
        refresh_reviews=False,
        snapshot_id="latest",
        save_artifacts=True,
    )
    return _DEFAULT_REPORT_CACHE


def load_or_regenerate_report_by_id(rep_id: str) -> Dict[str, Any]:
    """
    Loads a report bundle by ID, automatically regenerating it if its cached report_data.json
    was produced by an older methodology version.
    """
    _ensure_fresh_engine()
    rep_file = BASE_DIR / "reports" / "generated" / rep_id / "report_data.json"
    if rep_file.exists():
        with open(rep_file, "r", encoding="utf-8") as f:
            rep_data = json.load(f)
        if _is_valid_current_report(rep_data):
            return rep_data
        # Regenerate using stored window parameters if schema is outdated
        win = rep_data.get("window_configuration", {})
        meta = rep_data.get("report_metadata", {})
        return dynamic_engine.generate_dynamic_report(
            BASE_DIR,
            primary_period_mode=win.get("primary_period_mode", "12m"),
            trend_comparison_mode=win.get("trend_comparison_mode", "3m"),
            review_focus=meta.get("review_focus", "negative"),
            refresh_reviews=False,
            custom_start=win.get("primary_start"),
            custom_end=win.get("primary_end"),
            snapshot_id=meta.get("snapshot_id", "latest"),
            save_artifacts=True,
        )
    raise FileNotFoundError(f"Report '{rep_id}' not found on disk.")


def load_history_list() -> list:
    hist_path = BASE_DIR / "reports" / "generated" / "report_history.json"
    if hist_path.exists():
        try:
            with open(hist_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


class RatingIntelligenceHandler(BaseHTTPRequestHandler):

    def end_headers(self):
        self.send_header(
            "Access-Control-Allow-Origin",
            "https://move-in-sync-play-store-review-anal-one.vercel.app"
        )
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, OPTIONS"
        )
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type"
        )
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()
        def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/init":
            try:
                default_rep = get_or_create_default_report()
                snapshots = dynamic_engine.list_available_snapshots(BASE_DIR)
                history = load_history_list()
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "snapshots": snapshots,
                        "history": history,
                        "initial_report": default_rep,
                    },
                )
            except Exception as exc:
                self._send_json(500, {"status": "error", "message": str(exc), "trace": traceback.format_exc()})
            return

        if path.startswith("/api/report/"):
            rep_id = path.replace("/api/report/", "").strip("/")
            try:
                rep_data = load_or_regenerate_report_by_id(rep_id)
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "report": rep_data,
                        "history": load_history_list(),
                    },
                )
            except FileNotFoundError as fnf:
                self._send_json(404, {"status": "error", "message": str(fnf)})
            except Exception as exc:
                self._send_json(500, {"status": "error", "message": str(exc)})
            return

        if path.startswith("/api/export/"):
            rep_id = path.replace("/api/export/", "").strip("/")
            try:
                rep_data = load_or_regenerate_report_by_id(rep_id)
                export_file = BASE_DIR / "reports" / "generated" / rep_id / "report_export.html"
                html_str = dynamic_engine.build_standalone_export_html(rep_data)
                export_file.parent.mkdir(parents=True, exist_ok=True)
                export_file.write_text(html_str, encoding="utf-8")
                content = export_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="MoveInSync_Report_{rep_id}.html"')
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except FileNotFoundError as fnf:
                self._send_json(404, {"status": "error", "message": str(fnf)})
            except Exception as exc:
                self._send_json(500, {"status": "error", "message": str(exc)})
            return

        if path.startswith("/api/pdf/"):
            rep_id = path.replace("/api/pdf/", "").strip("/")
            try:
                rep_data = load_or_regenerate_report_by_id(rep_id)
                pdf_file = BASE_DIR / "reports" / "generated" / rep_id / f"MoveInSync_Report_{rep_id}.pdf"
                ok = dynamic_engine.render_pdf_from_report(rep_data, pdf_file)
                if not ok or not pdf_file.exists():
                    self._send_json(500, {"status": "error", "message": "Headless PDF generation failed."})
                    return
                content = pdf_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", f'attachment; filename="MoveInSync_Report_{rep_id}.pdf"')
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)
            except FileNotFoundError as fnf:
                self._send_json(404, {"status": "error", "message": str(fnf)})
            except Exception as exc:
                self._send_json(500, {"status": "error", "message": str(exc)})
            return

        # Serve static files from BASE_DIR
        rel_path = "index.html" if path in ("/", "") else path.lstrip("/")
        target_file = (BASE_DIR / rel_path).resolve()
        if not str(target_file).startswith(str(BASE_DIR.resolve())) or not target_file.is_file():
            self.send_error(404, f"File not found: {path}")
            return

        ctype, _ = mimetypes.guess_type(str(target_file))
        ctype = ctype or "application/octet-stream"
        data = target_file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/generate":
            self._send_json(404, {"status": "error", "message": f"Unknown endpoint {parsed.path}"})
            return

        try:
            _ensure_fresh_engine()
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            params = json.loads(raw_body)

            primary_period_mode = str(params.get("primary_period_mode", "12m"))
            trend_comparison_mode = str(params.get("trend_comparison_mode", "3m"))
            review_focus = str(params.get("review_focus", "negative"))
            refresh_reviews = bool(params.get("refresh_reviews", False))
            custom_start = params.get("custom_start") or None
            custom_end = params.get("custom_end") or None
            snapshot_id = str(params.get("snapshot_id", "latest"))

            report_payload = dynamic_engine.generate_dynamic_report(
                base_dir=BASE_DIR,
                primary_period_mode=primary_period_mode,
                trend_comparison_mode=trend_comparison_mode,
                review_focus=review_focus,
                refresh_reviews=refresh_reviews,
                custom_start=custom_start,
                custom_end=custom_end,
                snapshot_id=snapshot_id,
                save_artifacts=True,
            )

            if primary_period_mode == "12m" and trend_comparison_mode == "3m" and review_focus == "negative":
                global _DEFAULT_REPORT_CACHE
                _DEFAULT_REPORT_CACHE = report_payload

            self._send_json(
                200,
                {
                    "status": "ok",
                    "report": report_payload,
                    "snapshots": dynamic_engine.list_available_snapshots(BASE_DIR),
                    "history": load_history_list(),
                },
            )
        except ValueError as ve:
            self._send_json(400, {"status": "error", "message": str(ve)})
        except Exception as exc:
            self._send_json(
                500,
                {
                    "status": "error",
                    "message": f"Report generation failed: {exc}",
                    "trace": traceback.format_exc(),
                },
            )


def run_server(port: int = 8000) -> None:
    print(f"Initializing MoveInSync Dynamic Play Store Rating Intelligence System on port {port}...")
    get_or_create_default_report()
    server = ThreadingHTTPServer(("0.0.0.0", port), RatingIntelligenceHandler)
    print(f"\n=========================================================================")
    print(f" MoveInSync Dynamic Rating Intelligence App is LIVE at:")
    print(f"   http://localhost:{port}")
    print(f" Press Ctrl+C to stop the server.")
    print(f"=========================================================================\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run MoveInSync Dynamic Rating Intelligence Web Server"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", 8000))
    )
    args = parser.parse_args()
    run_server(port=args.port)