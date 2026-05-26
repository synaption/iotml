#!/usr/bin/env python3
"""Generate a self-contained HTML metrics dashboard from JSON metric files.

Reads ML metrics (accuracy, precision, recall, F1, sample counts) and/or
CI metrics (latency percentiles, pipeline duration, escalation rate, etc.)
then produces a single HTML file with Chart.js charts.

Usage
-----
    python scripts/metrics_dashboard.py
    python scripts/metrics_dashboard.py --ml-metrics artifacts/metrics.json \\
        --ci-metrics .artifacts/ci_metrics.json \\
        --output artifacts/dashboard.html
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone

LOGGER = logging.getLogger("metrics_dashboard")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_ML_METRICS = os.path.join("artifacts", "metrics.json")
DEFAULT_CI_METRICS = os.path.join(".artifacts", "ci_metrics.json")
DEFAULT_OUTPUT = os.path.join("artifacts", "dashboard.html")

# Chart.js version pinned for reproducibility
CHARTJS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate HTML metrics dashboard")
    parser.add_argument(
        "--ml-metrics",
        default=os.getenv("ML_METRICS_PATH", DEFAULT_ML_METRICS),
        help="Path to ML metrics JSON file (default: %(default)s)",
    )
    parser.add_argument(
        "--ci-metrics",
        default=os.getenv("CI_METRICS_PATH", DEFAULT_CI_METRICS),
        help="Path to CI metrics JSON file (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        default=os.getenv("DASHBOARD_OUTPUT", DEFAULT_OUTPUT),
        help="Output HTML path (default: %(default)s)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_json(path: str) -> dict | None:
    """Load a JSON file; return None if the file is missing or invalid."""
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        if isinstance(data, dict):
            return data
        LOGGER.warning("Unexpected JSON type in %s; skipping.", path)
        return None
    except FileNotFoundError:
        LOGGER.info("Metrics file not found: %s", path)
        return None
    except json.JSONDecodeError as exc:
        LOGGER.warning("Invalid JSON in %s: %s", path, exc)
        return None


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# HTML generation helpers
# ---------------------------------------------------------------------------

def _js_array(values: list[float]) -> str:
    return "[" + ", ".join(f"{v:.4f}" for v in values) + "]"


def _js_label_array(labels: list[str]) -> str:
    escaped = [lbl.replace("'", "\\'") for lbl in labels]
    return "[" + ", ".join(f"'{lbl}'" for lbl in escaped) + "]"


def build_ml_section(ml: dict) -> str:
    """Return the HTML+JS block for ML classification metrics."""
    pct_keys = ["accuracy", "precision", "recall", "f1"]
    labels = ["Accuracy", "Precision", "Recall", "F1"]
    values = [round(safe_float(ml.get(k, 0)) * 100, 2) for k in pct_keys]

    n_train = int(safe_float(ml.get("n_train", 0)))
    n_test = int(safe_float(ml.get("n_test", 0)))

    colors = [
        "rgba(54, 162, 235, 0.85)",
        "rgba(255, 159, 64, 0.85)",
        "rgba(75, 192, 192, 0.85)",
        "rgba(153, 102, 255, 0.85)",
    ]
    border_colors = [c.replace("0.85", "1") for c in colors]

    return f"""
    <!-- ── ML Metrics ── -->
    <section class="section">
      <h2>ML Classification Metrics</h2>
      <div class="cards">
        <div class="card"><span class="label">Train samples</span><span class="value">{n_train:,}</span></div>
        <div class="card"><span class="label">Test samples</span><span class="value">{n_test:,}</span></div>
        <div class="card"><span class="label">Accuracy</span><span class="value">{values[0]:.2f}%</span></div>
        <div class="card"><span class="label">F1 Score</span><span class="value">{values[3]:.2f}%</span></div>
      </div>
      <div class="chart-container">
        <canvas id="mlChart"></canvas>
      </div>
    </section>
    <script>
    (function() {{
      const ctx = document.getElementById('mlChart').getContext('2d');
      new Chart(ctx, {{
        type: 'bar',
        data: {{
          labels: {_js_label_array(labels)},
          datasets: [{{
            label: 'Score (%)',
            data: {_js_array(values)},
            backgroundColor: {json.dumps(colors)},
            borderColor: {json.dumps(border_colors)},
            borderWidth: 1,
          }}],
        }},
        options: {{
          responsive: true,
          plugins: {{
            legend: {{ display: false }},
            title: {{
              display: true,
              text: 'Classification Metrics (%)',
              font: {{ size: 14 }},
            }},
            tooltip: {{
              callbacks: {{
                label: (ctx) => ctx.parsed.y.toFixed(2) + '%',
              }},
            }},
          }},
          scales: {{
            y: {{
              min: 0,
              max: 100,
              ticks: {{ callback: (v) => v + '%' }},
              title: {{ display: true, text: 'Score (%)' }},
            }},
          }},
        }},
      }});
    }})();
    </script>
"""


def build_ci_section(ci: dict) -> str:
    """Return the HTML+JS block for CI pipeline metrics."""
    duration = safe_float(ci.get("pipeline_duration_seconds", -1))
    run_failed = safe_float(ci.get("run_failed", 0))
    escalation_rate = safe_float(ci.get("escalation_rate", -1))
    agreement_rate = safe_float(ci.get("edge_cloud_agreement_rate", -1))
    detections = int(safe_float(ci.get("detections_total", 0)))
    escalations = int(safe_float(ci.get("escalations_total", 0)))

    # Latency chart
    latency_labels = ["Edge p50 (ms)", "Edge p95 (ms)", "Cloud p95 (ms)"]
    latency_keys = ["edge_latency_p50_ms", "edge_latency_p95_ms", "cloud_latency_p95_ms"]
    latency_raw = [safe_float(ci.get(k, -1)) for k in latency_keys]
    # Only chart values that are non-negative (sentinel -1 = not measured)
    chart_labels = [l for l, v in zip(latency_labels, latency_raw) if v >= 0]
    chart_values = [v for v in latency_raw if v >= 0]

    # Summary card values
    def _fmt(val: float, unit: str = "", pct: bool = False) -> str:
        if val < 0:
            return "N/A"
        display = val * 100 if pct else val
        return f"{display:.2f}{unit}"

    status_badge = (
        '<span class="badge badge-fail">FAILED</span>'
        if run_failed >= 1
        else '<span class="badge badge-pass">PASSED</span>'
    )

    latency_chart_html = ""
    if chart_values:
        lat_colors = [
            "rgba(255, 99, 132, 0.85)",
            "rgba(255, 159, 64, 0.85)",
            "rgba(54, 162, 235, 0.85)",
        ]
        lat_border = [c.replace("0.85", "1") for c in lat_colors]
        latency_chart_html = f"""
      <div class="chart-container">
        <canvas id="latencyChart"></canvas>
      </div>
      <script>
      (function() {{
        const ctx = document.getElementById('latencyChart').getContext('2d');
        new Chart(ctx, {{
          type: 'bar',
          data: {{
            labels: {_js_label_array(chart_labels)},
            datasets: [{{
              label: 'Latency (ms)',
              data: {_js_array(chart_values)},
              backgroundColor: {json.dumps(lat_colors[:len(chart_values)])},
              borderColor: {json.dumps(lat_border[:len(chart_values)])},
              borderWidth: 1,
            }}],
          }},
          options: {{
            responsive: true,
            plugins: {{
              legend: {{ display: false }},
              title: {{
                display: true,
                text: 'Latency Percentiles (ms)',
                font: {{ size: 14 }},
              }},
              tooltip: {{
                callbacks: {{
                  label: (ctx) => ctx.parsed.y.toFixed(2) + ' ms',
                }},
              }},
            }},
            scales: {{
              y: {{
                min: 0,
                ticks: {{ callback: (v) => v + ' ms' }},
                title: {{ display: true, text: 'Milliseconds' }},
              }},
            }},
          }},
        }});
      }})();
      </script>
"""
    else:
        latency_chart_html = "<p class='no-data'>Latency metrics not available for this run.</p>"

    return f"""
    <!-- ── CI Metrics ── -->
    <section class="section">
      <h2>CI Pipeline Metrics</h2>
      <div class="cards">
        <div class="card"><span class="label">Run status</span><span class="value">{status_badge}</span></div>
        <div class="card"><span class="label">Pipeline duration</span><span class="value">{_fmt(duration, 's')}</span></div>
        <div class="card"><span class="label">Detections</span><span class="value">{detections:,}</span></div>
        <div class="card"><span class="label">Escalations</span><span class="value">{escalations:,}</span></div>
        <div class="card"><span class="label">Escalation rate</span><span class="value">{_fmt(escalation_rate, '%', pct=True)}</span></div>
        <div class="card"><span class="label">Edge–cloud agreement</span><span class="value">{_fmt(agreement_rate, '%', pct=True)}</span></div>
      </div>
      {latency_chart_html}
    </section>
"""


def build_html(ml: dict | None, ci: dict | None, generated_at: str) -> str:
    """Assemble the complete HTML page."""
    ml_section = build_ml_section(ml) if ml else ""
    ci_section = build_ci_section(ci) if ci else ""

    if not ml_section and not ci_section:
        body_content = "<p class='no-data'>No metric files were found. Run the training or CI pipeline first.</p>"
    else:
        body_content = ml_section + ci_section

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>iotml Metrics Dashboard</title>
  <script src="{CHARTJS_CDN}"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background: #f0f2f5;
      color: #1a1a2e;
      padding: 2rem;
    }}
    header {{
      margin-bottom: 2rem;
    }}
    header h1 {{
      font-size: 1.8rem;
      font-weight: 700;
      color: #0d1b2a;
    }}
    header p.subtitle {{
      color: #555;
      margin-top: 0.25rem;
      font-size: 0.9rem;
    }}
    .section {{
      background: #fff;
      border-radius: 12px;
      padding: 1.5rem;
      margin-bottom: 2rem;
      box-shadow: 0 2px 8px rgba(0,0,0,0.07);
    }}
    .section h2 {{
      font-size: 1.2rem;
      font-weight: 600;
      margin-bottom: 1rem;
      color: #0d1b2a;
      border-bottom: 2px solid #e8eaf0;
      padding-bottom: 0.5rem;
    }}
    .cards {{
      display: flex;
      flex-wrap: wrap;
      gap: 1rem;
      margin-bottom: 1.5rem;
    }}
    .card {{
      background: #f7f9fc;
      border: 1px solid #e0e4ef;
      border-radius: 8px;
      padding: 0.75rem 1.25rem;
      display: flex;
      flex-direction: column;
      min-width: 140px;
    }}
    .card .label {{
      font-size: 0.75rem;
      color: #666;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 0.3rem;
    }}
    .card .value {{
      font-size: 1.3rem;
      font-weight: 700;
      color: #0d1b2a;
    }}
    .chart-container {{
      position: relative;
      max-width: 600px;
      margin: 0 auto;
    }}
    .badge {{
      display: inline-block;
      padding: 0.2em 0.6em;
      border-radius: 4px;
      font-size: 0.85rem;
      font-weight: 600;
    }}
    .badge-pass {{ background: #d4edda; color: #155724; }}
    .badge-fail {{ background: #f8d7da; color: #721c24; }}
    p.no-data {{
      color: #888;
      font-style: italic;
      padding: 1rem 0;
    }}
    footer {{
      text-align: center;
      font-size: 0.8rem;
      color: #999;
      margin-top: 2rem;
    }}
  </style>
</head>
<body>
  <header>
    <h1>iotml Metrics Dashboard</h1>
    <p class="subtitle">Generated at {generated_at}</p>
  </header>
  {body_content}
  <footer>iotml &mdash; metrics_dashboard.py</footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()

    ml = load_json(args.ml_metrics)
    ci = load_json(args.ci_metrics)

    if ml is None and ci is None:
        LOGGER.warning(
            "Neither ML metrics (%s) nor CI metrics (%s) could be loaded. "
            "Dashboard will render with a 'no data' message.",
            args.ml_metrics,
            args.ci_metrics,
        )

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = build_html(ml, ci, generated_at)

    output_path = args.output
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fp:
        fp.write(html)

    LOGGER.info("Dashboard written to %s", output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
