"""Bake ``report_data.json`` into the report template to produce a standalone,
date-stamped HTML file that needs no server, no network and no data files.

Run ``breadth_sector.py`` and ``build_report_data.py`` first.

Usage:
    python analysis/build_report.py [--data data/analysis/report_data.json] [--out-dir analysis/reports]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLACEHOLDER = "__REPORT_DATA__"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default=str(REPO / "analysis" / "report_template.html"))
    ap.add_argument("--data", default=str(REPO / "data" / "analysis" / "report_data.json"))
    ap.add_argument("--out-dir", default=str(REPO / "analysis" / "reports"))
    args = ap.parse_args()

    tpl = Path(args.template).read_text(encoding="utf-8")
    if PLACEHOLDER not in tpl:
        raise SystemExit(f"{args.template} has no {PLACEHOLDER} placeholder")

    raw = Path(args.data).read_text(encoding="utf-8")
    payload = json.loads(raw)
    # The payload is inlined inside a <script> tag, so it must not be able to close it.
    if "</script" in raw.lower():
        raise SystemExit("report data contains a </script sequence; refusing to inline it")

    asof = payload["asof"]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"sp500_internals_{asof}.html"
    out.write_text(tpl.replace(PLACEHOLDER, raw), encoding="utf-8")

    print(f"wrote {out} ({out.stat().st_size:,} bytes)")
    print(f"  data as of {asof} · generated {payload.get('generated', 'n/a')}")


if __name__ == "__main__":
    main()
