#!/usr/bin/env python
"""Sinh dashboard 6 panel tu data/logs.jsonl thanh mot file HTML tu chua.

Chay:
    python scripts/build_dashboard.py
    python scripts/build_dashboard.py --window 60 --out dashboard.html

Nguon du lieu : data/logs.jsonl (structured log cua ung dung)
Contract      : config/dashboard.yaml (6 panel, unit, threshold, time range 60 phut)

Khong dung thu vien ngoai: chart duoc ve bang SVG sinh tu Python, mo bang
trinh duyet la xem duoc, khong can internet.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.metrics import percentile  # noqa: E402  (tai su dung ham co san)

DEFAULT_LOG_PATH = REPO_ROOT / "data" / "logs.jsonl"
DEFAULT_OUT_PATH = REPO_ROOT / "dashboard.html"
DEFAULT_WINDOW_MINUTES = 60

# Palette lay tu dataviz/references/palette.md, da chay validate_palette.js:
#   light  #2a78d6,#eb6834,#1baf7a,#eda100  -> ALL CHECKS PASS
#   dark   #3987e5,#d95926,#199e70,#c98500  -> ALL CHECKS PASS
SERIES_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
SERIES_DARK = ("#3987e5", "#d95926", "#199e70", "#c98500")
STATUS_CRITICAL = "#d03b3b"

CHART_W = 560
CHART_H = 190
PAD_L, PAD_R, PAD_T, PAD_B = 62, 74, 14, 30


# --------------------------------------------------------------------------
# Doc va tong hop log
# --------------------------------------------------------------------------
@dataclass
class Bucket:
    ts: datetime
    latencies: list[int] = field(default_factory=list)
    ttfts: list[int] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    qualities: list[float] = field(default_factory=list)
    requests: int = 0
    failures: int = 0
    error_types: Counter = field(default_factory=Counter)
    tool_results: list[bool] = field(default_factory=list)


def _parse_ts(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def load_buckets(log_path: Path, window_minutes: int) -> tuple[dict[datetime, Bucket], dict]:
    """Doc log, tra ve (bucket theo phut, tong hop toan cua so)."""
    if not log_path.exists():
        raise SystemExit(f"Khong tim thay {log_path}. Chay app va load test truoc.")

    records = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    stamped = []
    for rec in records:
        ts = _parse_ts(rec.get("ts", ""))
        if ts is not None:
            stamped.append((ts, rec))
    if not stamped:
        raise SystemExit("Khong co dong log nao co timestamp hop le.")

    newest = max(ts for ts, _ in stamped)
    cutoff = newest - timedelta(minutes=window_minutes)

    buckets: dict[datetime, Bucket] = {}
    totals = {
        "requests": 0, "failures": 0, "cost": 0.0,
        "tokens_in": 0, "tokens_out": 0,
        "error_types": Counter(),
    }
    for ts, rec in stamped:
        if ts < cutoff:
            continue
        minute = ts.replace(second=0, microsecond=0)
        b = buckets.setdefault(minute, Bucket(ts=minute))
        event = rec.get("event")
        if event == "request_received":
            b.requests += 1
            totals["requests"] += 1
        elif event == "response_sent":
            if isinstance(rec.get("latency_ms"), (int, float)):
                b.latencies.append(int(rec["latency_ms"]))
            if isinstance(rec.get("ttft_ms"), (int, float)):
                b.ttfts.append(int(rec["ttft_ms"]))
            b.tokens_in += int(rec.get("tokens_in") or 0)
            b.tokens_out += int(rec.get("tokens_out") or 0)
            b.cost += float(rec.get("cost_usd") or 0.0)
            if isinstance(rec.get("quality_score"), (int, float)):
                b.qualities.append(float(rec["quality_score"]))
            if rec.get("tool_success") is not None:
                b.tool_results.append(bool(rec["tool_success"]))
            totals["cost"] += float(rec.get("cost_usd") or 0.0)
            totals["tokens_in"] += int(rec.get("tokens_in") or 0)
            totals["tokens_out"] += int(rec.get("tokens_out") or 0)
        elif event == "request_failed":
            b.failures += 1
            name = rec.get("error_type") or "Unknown"
            b.error_types[name] += 1
            totals["failures"] += 1
            totals["error_types"][name] += 1

    if not buckets:
        raise SystemExit("Cua so thoi gian rong. Chay lai load test roi thu lai.")

    # Dien cac phut trong khong co du lieu de truc thoi gian lien tuc.
    start = min(buckets)
    end = max(buckets)
    cursor = start
    while cursor <= end:
        buckets.setdefault(cursor, Bucket(ts=cursor))
        cursor += timedelta(minutes=1)

    return dict(sorted(buckets.items())), totals


# --------------------------------------------------------------------------
# Ve chart bang SVG
# --------------------------------------------------------------------------
def _scale(value: float, vmin: float, vmax: float, pmin: float, pmax: float) -> float:
    if vmax <= vmin:
        return (pmin + pmax) / 2
    return pmin + (value - vmin) / (vmax - vmin) * (pmax - pmin)


def _fmt(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    if abs(value) >= 1:
        return f"{value:.2f}"
    return f"{value:.3f}"


def _segments(values: list[float | None]) -> list[list[tuple[int, float]]]:
    """Chia chuoi gia tri thanh cac doan lien tuc, cat tai cho thieu du lieu."""
    segments: list[list[tuple[int, float]]] = []
    current: list[tuple[int, float]] = []
    for i, value in enumerate(values):
        if value is None:
            if current:
                segments.append(current)
                current = []
        else:
            current.append((i, value))
    if current:
        segments.append(current)
    return segments


def line_chart(
    labels: list[str],
    series: list[tuple[str, int, list[float | None]]],
    *,
    unit: str,
    threshold: tuple[str, float] | None = None,
    y_max: float | None = None,
) -> str:
    """Ve line chart.

    labels  : nhan truc x
    series  : [(ten, chi so mau 0-3, danh sach gia tri)] - None = khong co du lieu
    unit    : don vi hien tren truc y va tooltip
    threshold: (mo ta, gia tri) cho duong SLO
    """
    n = len(labels)
    plot_w = CHART_W - PAD_L - PAD_R
    plot_h = CHART_H - PAD_T - PAD_B

    all_values = [v for _, _, values in series for v in values if v is not None]
    if not all_values:
        all_values = [0.0]
    if threshold:
        all_values.append(threshold[1])
    vmin = min(all_values + [0.0])
    vmax = max(all_values + [1e-9])
    if y_max is not None:
        vmax = max(vmax, y_max)
    # Cho duong du lieu khong dinh sat mep tren.
    vmax = vmax * 1.12 if vmax > 0 else 1.0
    if vmin > 0:
        vmin = 0.0

    def px(i: int) -> float:
        return PAD_L + (plot_w * i / (n - 1) if n > 1 else plot_w / 2)

    def py(v: float) -> float:
        return PAD_T + plot_h - _scale(v, vmin, vmax, 0, plot_h)

    parts: list[str] = []
    parts.append(
        f'<svg class="chart" viewBox="0 0 {CHART_W} {CHART_H}" role="img" '
        f'aria-label="Bieu do {html.escape(unit)}">'
    )

    # Luoi ngang + nhan truc y (hairline lien, khong dut doan).
    for k in range(5):
        value = vmin + (vmax - vmin) * k / 4
        y = py(value)
        parts.append(
            f'<line class="grid" x1="{PAD_L:.1f}" y1="{y:.1f}" '
            f'x2="{PAD_L + plot_w:.1f}" y2="{y:.1f}"/>'
        )
        parts.append(
            f'<text class="tick" x="{PAD_L - 8:.1f}" y="{y + 3.5:.1f}" '
            f'text-anchor="end">{html.escape(_fmt(value))}</text>'
        )

    # Truc x: chi hien mot so nhan de khong day chu.
    step = max(1, n // 6)
    for i in range(0, n, step):
        parts.append(
            f'<text class="tick" x="{px(i):.1f}" y="{CHART_H - 10:.1f}" '
            f'text-anchor="middle">{html.escape(labels[i])}</text>'
        )

    # Duong SLO.
    if threshold:
        desc, value = threshold
        ty = py(value)
        parts.append(
            f'<line class="slo" x1="{PAD_L:.1f}" y1="{ty:.1f}" '
            f'x2="{PAD_L + plot_w:.1f}" y2="{ty:.1f}"/>'
        )
        parts.append(
            f'<text class="slo-label" x="{PAD_L + plot_w + 6:.1f}" y="{ty + 3.5:.1f}">'
            f'{html.escape(desc)}</text>'
        )

    # Duong du lieu (2px) + diem neo + vung hover.
    # Phut khong co du lieu -> None -> cat doan, khong ve gia tri 0 gia tao.
    ends: list[tuple[int, float, float, str]] = []
    for name, slot, values in series:
        for segment in _segments(values):
            points = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in segment)
            parts.append(
                f'<polyline class="line" style="--c:var(--series-{slot + 1})" '
                f'points="{points}"/>'
            )
        # Cua so thua du lieu: mot doan chi gom 1 diem nen polyline khong ve ra
        # gi, nguoi doc chi thay nhan tro troi ben le phai. Khi do phai ve marker
        # de diem du lieu nhin thay duoc. Dieu kien dua tren SO DIEM CO DU LIEU,
        # khong phai do dai cua so.
        non_null = [v for v in values if v is not None]
        if len(non_null) <= 24:
            for i, v in enumerate(values):
                if v is None:
                    continue
                parts.append(
                    f'<circle class="dot" style="--c:var(--series-{slot + 1})" '
                    f'cx="{px(i):.1f}" cy="{py(v):.1f}" r="4"/>'
                )
        # Vung hover rong hon diem ve, de de tro.
        for i, v in enumerate(values):
            if v is None:
                continue
            parts.append(
                f'<circle class="hit" cx="{px(i):.1f}" cy="{py(v):.1f}" r="12" '
                f'data-tip="{html.escape(name)}: {_fmt(v)} {html.escape(unit)} ({html.escape(labels[i])})"/>'
            )
        # Direct label: chuoi du day thi chi dan nhan diem cuoi; chuoi thua thi
        # dan nhan moi diem, vi mot diem "cuoi" khong du de doc xu huong.
        if len(non_null) <= 6:
            labelled = [(i, v) for i, v in enumerate(values) if v is not None]
        else:
            last_i = next(
                (i for i in range(len(values) - 1, -1, -1) if values[i] is not None),
                None,
            )
            labelled = [(last_i, values[last_i])] if last_i is not None else []
        for i, v in labelled:
            ends.append((slot, px(i) + 8, py(v), _fmt(v)))

    # Day cac nhan cuoi dong ra xa nhau, tranh nhan SLO, va khong tran ra
    # ngoai vung ve (neu tran se de len nhan truc x).
    reserved = [py(threshold[1])] if threshold else []
    min_y = PAD_T + 6
    max_y = PAD_T + plot_h - 4
    ends.sort(key=lambda e: e[2])

    def _collides(y: float, placed: list[float]) -> bool:
        return any(abs(y - r) < 11 for r in reserved) or any(
            abs(y - p) < 12 for p in placed
        )

    placed: list[float] = []
    laid_out: list[tuple[int, float, float, str]] = []
    for slot, x, y, text in ends:
        y = min(max(y, min_y), max_y)
        if _collides(y, placed):
            # Uu tien keo len truoc (du lieu thuong don o day), roi moi keo xuong.
            for candidate in (y - 12, y + 12, y - 24, y + 24, y - 36, y + 36):
                if min_y <= candidate <= max_y and not _collides(candidate, placed):
                    y = candidate
                    break
        placed.append(y)
        laid_out.append((slot, x, y, text))
    ends = laid_out

    for slot, x, y, text in ends:
        parts.append(
            f'<text class="endlabel" style="--c:var(--series-{slot + 1})" '
            f'x="{x:.1f}" y="{y + 3.5:.1f}">{html.escape(text)}</text>'
        )

    # Vach truc y.
    parts.append(
        f'<line class="axis" x1="{PAD_L:.1f}" y1="{PAD_T:.1f}" '
        f'x2="{PAD_L:.1f}" y2="{PAD_T + plot_h:.1f}"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def legend(series: list[tuple[str, int, list[float]]]) -> str:
    if len(series) < 2:
        return ""
    items = "".join(
        f'<span class="legend-item"><i style="--c:var(--series-{slot + 1})"></i>'
        f"{html.escape(name)}</span>"
        for name, slot, _ in series
    )
    return f'<div class="legend">{items}</div>'


def table_view(labels: list[str], series: list[tuple[str, int, list[float]]], unit: str) -> str:
    head = "".join(f"<th>{html.escape(name)} ({html.escape(unit)})</th>" for name, _, _ in series)
    rows = []
    for i, label in enumerate(labels):
        cells = "".join(
            f"<td>{'—' if values[i] is None else _fmt(values[i])}</td>"
            for _, _, values in series
        )
        rows.append(f"<tr><th scope=\"row\">{html.escape(label)}</th>{cells}</tr>")
    return (
        '<details class="table"><summary>Bang so lieu</summary>'
        f'<table><thead><tr><th>Phut</th>{head}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></details>"
    )


def panel(
    title: str,
    unit: str,
    threshold_note: str,
    labels: list[str],
    blocks: list[dict],
) -> str:
    """Mot card dashboard = 1 panel id trong config/dashboard.yaml.

    blocks cho phep panel gop (vi du panel 'errors' gom error rate + retrieval
    success) ma van giu dung 6 panel. Moi block la mot chart rieng voi truc
    rieng - khong dung dual-axis.
    """
    body: list[str] = []
    for blk in blocks:
        series = blk["series"]
        if blk.get("subtitle"):
            body.append(f'<p class="subtitle">{html.escape(blk["subtitle"])}</p>')
        body.append(legend(series))
        body.append(
            line_chart(
                labels,
                series,
                unit=blk.get("unit", unit),
                threshold=blk.get("threshold"),
                y_max=blk.get("y_max"),
            )
        )
        if blk.get("extra"):
            body.append(blk["extra"])
        body.append(table_view(labels, series, blk.get("unit", unit)))
    return f"""<section class="card">
  <header>
    <h2>{html.escape(title)}</h2>
    <span class="unit">{html.escape(unit)}</span>
  </header>
  <p class="threshold">{html.escape(threshold_note)}</p>
  {''.join(body)}
</section>"""


# --------------------------------------------------------------------------
# Dung HTML
# --------------------------------------------------------------------------
CSS = """
:root {
  color-scheme: light;
  --surface-1: #fcfcfb; --page: #f9f9f7;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a; --series-4: #eda100;
  --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --surface-1: #1a1a19; --page: #0d0d0d;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #c98500;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-1: #1a1a19; --page: #0d0d0d;
  --text-primary: #ffffff; --text-secondary: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #c98500;
}
.theme-btn { position: fixed; top: 14px; right: 16px; z-index: 11;
  background: var(--surface-1); color: var(--text-secondary);
  border: 1px solid var(--border); border-radius: 8px;
  padding: 5px 10px; font: inherit; font-size: 12px; cursor: pointer; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
.wrap { max-width: 1240px; margin: 0 auto; padding: 28px 20px 56px; }
h1 { font-size: 21px; margin: 0 0 4px; }
.meta { color: var(--text-secondary); font-size: 13px; margin: 0 0 22px; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px; margin-bottom: 22px; }
.stat { background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 10px; padding: 13px 15px; }
.stat .k { font-size: 12px; color: var(--text-secondary); margin-bottom: 5px; }
.stat .v { font-size: 25px; font-weight: 600; letter-spacing: -0.01em; }
.stat .u { font-size: 13px; color: var(--muted); font-weight: 400; margin-left: 3px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(430px, 1fr)); gap: 16px; }
.card { background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 10px; padding: 15px 17px 13px; }
.card header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.card h2 { font-size: 14px; margin: 0; font-weight: 600; }
.unit { font-size: 11px; color: var(--muted); border: 1px solid var(--border);
  border-radius: 999px; padding: 2px 8px; white-space: nowrap; }
.threshold { font-size: 11.5px; color: var(--text-secondary); margin: 5px 0 8px; }
.subtitle { font-size: 11.5px; font-weight: 600; color: var(--text-secondary);
  margin: 11px 0 4px; }
.legend { display: flex; flex-wrap: wrap; gap: 13px; margin: 0 0 5px; }
.legend-item { font-size: 11.5px; color: var(--text-secondary);
  display: inline-flex; align-items: center; gap: 5px; }
.legend-item i { width: 9px; height: 9px; border-radius: 2px; background: var(--c); }
.chart { width: 100%; height: auto; display: block; }
.chart .grid { stroke: var(--grid); stroke-width: 1; }
.chart .axis { stroke: var(--axis); stroke-width: 1; }
.chart .tick { fill: var(--muted); font-size: 10px; font-variant-numeric: tabular-nums; }
.chart .slo { stroke: var(--critical); stroke-width: 1.5; stroke-dasharray: none; opacity: .75; }
.chart .slo-label { fill: var(--critical); font-size: 9.5px; }
.chart .line { fill: none; stroke: var(--c); stroke-width: 2;
  stroke-linejoin: round; stroke-linecap: round; }
.chart .dot { fill: var(--c); stroke: var(--surface-1); stroke-width: 2; }
.chart .endlabel { fill: var(--c); font-size: 10.5px; font-variant-numeric: tabular-nums; }
.chart .hit { fill: transparent; cursor: crosshair; }
details.table { margin-top: 9px; font-size: 12px; }
details.table summary { color: var(--text-secondary); cursor: pointer; font-size: 11.5px; }
details.table table { border-collapse: collapse; width: 100%; margin-top: 7px; }
details.table th, details.table td { border-bottom: 1px solid var(--border);
  padding: 4px 9px; text-align: right; font-variant-numeric: tabular-nums;
  font-weight: 400; color: var(--text-secondary); }
details.table thead th, details.table tbody th { color: var(--text-primary); }
details.table thead th { font-weight: 600; }
.err-list { font-size: 12px; color: var(--text-secondary); margin: 8px 0 0; }
.err-list code { background: var(--page); border: 1px solid var(--border);
  border-radius: 4px; padding: 1px 5px; }
#tip { position: fixed; pointer-events: none; background: var(--text-primary);
  color: var(--surface-1); font-size: 11.5px; padding: 5px 8px; border-radius: 6px;
  opacity: 0; transition: opacity .1s; z-index: 10; white-space: nowrap; }
"""

JS = """
const tip = document.getElementById('tip');
document.querySelectorAll('.chart .hit').forEach(el => {
  el.addEventListener('mouseenter', () => {
    tip.textContent = el.dataset.tip;
    tip.style.opacity = '1';
  });
  el.addEventListener('mousemove', e => {
    tip.style.left = (e.clientX + 12) + 'px';
    tip.style.top = (e.clientY - 30) + 'px';
  });
  el.addEventListener('mouseleave', () => { tip.style.opacity = '0'; });
});

const root = document.documentElement;
const btn = document.getElementById('theme');
btn.addEventListener('click', () => {
  const dark = root.getAttribute('data-theme') === 'dark';
  root.setAttribute('data-theme', dark ? 'light' : 'dark');
  btn.textContent = dark ? 'Giao dien toi' : 'Giao dien sang';
});
"""


def build_html(buckets: dict[datetime, Bucket], totals: dict, window_minutes: int) -> str:
    minutes = list(buckets.values())
    labels = [b.ts.strftime("%H:%M") for b in minutes]

    def series_values(fn):
        return [fn(b) for b in minutes]

    def pct(values, p):
        return percentile(values, p) if values else 0.0

    def pct_or_none(values, p):
        """None khi phut do khong co mau - tranh ve 0 gia tao."""
        return percentile(values, p) if values else None

    lat_p50 = series_values(lambda b: pct_or_none(b.latencies, 50))
    lat_p95 = series_values(lambda b: pct_or_none(b.latencies, 95))
    lat_p99 = series_values(lambda b: pct_or_none(b.latencies, 99))
    ttft_p95 = series_values(lambda b: pct_or_none(b.ttfts, 95))

    # Traffic: 0 request/phut la so do that, khong phai thieu du lieu.
    traffic = series_values(lambda b: float(b.requests))
    err_rate = series_values(
        lambda b: (b.failures / b.requests * 100) if b.requests else None
    )
    retr_success = series_values(
        lambda b: (sum(b.tool_results) / len(b.tool_results) * 100) if b.tool_results else None
    )
    quality = series_values(
        lambda b: (sum(b.qualities) / len(b.qualities)) if b.qualities else None
    )

    # Cost va tokens: luy ke trong cua so, de so duoc voi nguong SLO tong.
    cum_cost: list[float] = []
    cum_in: list[float] = []
    cum_out: list[float] = []
    running_cost = running_in = running_out = 0.0
    for b in minutes:
        running_cost += b.cost
        running_in += b.tokens_in
        running_out += b.tokens_out
        cum_cost.append(round(running_cost, 6))
        cum_in.append(float(running_in))
        cum_out.append(float(running_out))

    total_lat = [v for b in minutes for v in b.latencies]
    total_quality = [v for b in minutes for v in b.qualities]
    overall_err = (
        totals["failures"] / totals["requests"] * 100 if totals["requests"] else 0.0
    )
    overall_retr = [
        ok for b in minutes for ok in b.tool_results
    ]
    overall_retr_rate = (
        sum(overall_retr) / len(overall_retr) * 100 if overall_retr else 0.0
    )

    err_breakdown = ""
    if totals["error_types"]:
        chips = "".join(
            f"<code>{html.escape(name)}: {count}</code>"
            for name, count in totals["error_types"].most_common()
        )
        err_breakdown = f'<p class="err-list">Breakdown loi: {chips}</p>'
    else:
        err_breakdown = '<p class="err-list">Breakdown loi: khong co loi nao trong cua so.</p>'

    stats = [
        ("Traffic", f"{totals['requests']}", "request"),
        ("Latency P95", _fmt(pct(total_lat, 95)), "ms"),
        ("Error rate", f"{overall_err:.2f}", "%"),
        ("Retrieval success", f"{overall_retr_rate:.0f}", "%"),
        ("Chi phi", f"{totals['cost']:.4f}", "USD"),
        ("Quality trung binh", f"{(sum(total_quality) / len(total_quality) if total_quality else 0):.2f}", "0-1"),
    ]
    stat_html = "".join(
        f'<div class="stat"><div class="k">{html.escape(k)}</div>'
        f'<div class="v">{html.escape(v)}<span class="u">{html.escape(u)}</span></div></div>'
        for k, v, u in stats
    )

    panels = [
        panel(
            "1. Latency percentiles va TTFT", "ms",
            "Nguong SLO: P95 <= 3000 ms (duong do la SLO line)",
            labels,
            [
                {"subtitle": "Latency end-to-end theo phut",
                 "series": [("P50", 0, lat_p50), ("P95", 1, lat_p95),
                            ("P99", 2, lat_p99)],
                 "threshold": ("SLO 3000", 3000.0)},
                {"subtitle": "TTFT P95 theo phut (thang do rieng, cung don vi ms)",
                 "series": [("TTFT P95", 3, ttft_p95)]},
            ],
        ),
        panel(
            "2. Request traffic", "requests/min",
            "Nguong SLO: >= 1 request/phut",
            labels,
            [{"series": [("Requests", 0, traffic)], "threshold": ("San 1", 1.0)}],
        ),
        panel(
            "3. Error rate va retrieval success", "%",
            "Nguong SLO: error rate <= 2% · retrieval success >= 90%",
            labels,
            [
                {"subtitle": "Error rate theo phut",
                 "series": [("Error rate", 1, err_rate)],
                 "threshold": ("SLO 2%", 2.0), "y_max": 2.0, "extra": err_breakdown},
                {"subtitle": "Retrieval success theo phut (tool_success)",
                 "series": [("Retrieval success", 0, retr_success)],
                 "threshold": ("San 90%", 90.0), "y_max": 100.0},
            ],
        ),
        panel(
            "4. Cost tich luy trong cua so", "USD",
            "Nguong SLO: tong <= 2.5 USD trong cua so (bang so lieu co cost tung phut)",
            labels,
            [{"series": [("Cost tich luy", 0, cum_cost)],
              "threshold": ("SLO 2.5", 2.5)}],
        ),
        panel(
            "5. Input / output tokens tich luy", "tokens",
            "Nguong SLO: tong <= 50000 tokens",
            labels,
            [{"series": [("Input tich luy", 0, cum_in),
                         ("Output tich luy", 1, cum_out)],
              "threshold": ("SLO 50000", 50000.0)}],
        ),
        panel(
            "6. Quality proxy", "score 0-1",
            "Nguong SLO: mean >= 0.75",
            labels,
            [{"series": [("Quality", 0, quality)],
              "threshold": ("San 0.75", 0.75), "y_max": 1.0}],
        ),
    ]

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    span = f"{labels[0]} - {labels[-1]}"

    return f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>K4-L3A Day 13 — Dashboard Monitoring &amp; LLMOps</title>
<style>{CSS}</style>
</head>
<body>
<button class="theme-btn" id="theme" type="button">Giao dien toi</button>
<div class="viz-root">
<div class="wrap">
  <h1>K4-L3A Day 13 — Monitoring &amp; LLMOps</h1>
  <p class="meta">Nguon: data/logs.jsonl · 6 panel theo config/dashboard.yaml
     · Time range: {window_minutes} phut ({html.escape(span)})
     · Refresh: 30s · Sinh luc {generated} · {len(minutes)} diem du lieu</p>
  <div class="stats">{stat_html}</div>
  <div class="grid">{''.join(panels)}</div>
</div>
</div>
<div id="tip"></div>
<script>{JS}</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Sinh dashboard 6 panel tu data/logs.jsonl")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW_MINUTES,
                        help="Cua so thoi gian tinh bang phut (contract: 60)")
    args = parser.parse_args()

    buckets, totals = load_buckets(args.log, args.window)
    args.out.write_text(build_html(buckets, totals, args.window), encoding="utf-8")
    print(f"Da sinh {args.out}")
    print(f"  {len(buckets)} diem du lieu, {totals['requests']} request, "
          f"{totals['failures']} loi, {totals['cost']:.4f} USD")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
