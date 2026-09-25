#!/usr/bin/env python3
"""Build the per-president word-cloud picker (exploration prototype).

Generates one word-cloud PNG per president from `distinctive_words_by_president`
(TF-IDF — each president's DEFINING vocabulary) into `docs/presidents/<slug>.png`,
plus a `docs/presidents.html` page with a <select> that swaps the <img> src —
mirroring the countries-income-disparity country picker.

This is an EXPLORATION prototype for owner review (which per-president view to
ship), not a published artifact yet. Run from the project root:

    .venv/bin/python scripts/build_president_pages.py

Re-runnable; overwrites its outputs. Reads DuckDB read-only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT.parent.parent / "shared"))

import duckdb  # noqa: E402
import pandas as pd  # noqa: E402
from chart_templates import word_cloud  # noqa: E402

DB = PROJECT / "data" / "project.duckdb"
OUT_DIR = PROJECT / "docs" / "presidents"
HTML = PROJECT / "docs" / "presidents.html"
SOURCE = "Miller Center (UVA) speech archive"


def slug(name: str) -> str:
    """Filesystem-safe slug for a president name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB), read_only=True)

    # Presidents ordered chronologically by first speech, with their n_speeches.
    presidents = con.execute(
        """
        SELECT s.president, MIN(s.year) AS first_year,
               COALESCE(t.n_speeches, COUNT(*)) AS n_speeches
        FROM speeches_clean s
        LEFT JOIN president_terms t USING (president)
        GROUP BY s.president, t.n_speeches
        ORDER BY first_year
        """
    ).df()

    distinctive = con.execute(
        "SELECT president, word, tfidf FROM distinctive_words_by_president"
    ).df()
    con.close()

    made = []
    for _, row in presidents.iterrows():
        name = row["president"]
        words = distinctive[distinctive["president"] == name][["word", "tfidf"]]
        if words.empty:
            continue
        img = word_cloud(
            df=words, word_col="word", weight_col="tfidf",
            title=f"{name} — distinctive words",
            subtitle="Words this president used far more than others (TF-IDF). "
                     "Curated corpus; speech as delivered (ghostwriting).",
            source=SOURCE, img_width=1600, img_height=900,
        )
        out = OUT_DIR / f"{slug(name)}.png"
        img.save(out, format="PNG", optimize=True)
        made.append((name, slug(name), int(row["n_speeches"])))

    # default = first president with a cloud
    default_slug = made[0][1] if made else ""
    options = "\n".join(
        f'      <option value="{s}">{n} ({n_sp} speeches)</option>'
        for n, s, n_sp in made
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Presidential speeches — distinctive words by president</title>
<style>
  body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; margin: 0;
          color: #1c2530; background: #fff; }}
  .wrap {{ max-width: 960px; margin: 0 auto; padding: 24px 16px 48px; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  p.lead {{ color: #55606b; font-size: 15px; margin: 0 0 18px; line-height: 1.5; }}
  .controls {{ margin: 0 0 16px; }}
  label {{ font-weight: 600; font-size: 14px; margin-right: 8px; }}
  select {{ font-size: 15px; padding: 7px 10px; border: 1px solid #c7ced5;
            border-radius: 6px; background: #fff; min-width: 320px; }}
  .chart img {{ width: 100%; height: auto; border: 1px solid #eee; border-radius: 6px; }}
  .note {{ color: #77818b; font-size: 13px; margin-top: 14px; line-height: 1.5; }}
  a {{ color: #005F73; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Distinctive words by president</h1>
  <p class="lead">
    Pick a president to see the words they used far more than other presidents
    (TF-IDF over the Miller Center speech corpus). Word size = distinctiveness.
    This is a curated set of major speeches, not every speech, and measures the
    text as delivered (many speeches were ghostwritten).
  </p>
  <div class="controls">
    <label for="pres">President</label>
    <select id="pres" onchange="swap()">
{options}
    </select>
  </div>
  <div class="chart">
    <img id="cloud" src="presidents/{default_slug}.png" alt="distinctive words">
  </div>
  <p class="note">Source: {SOURCE}. Exploration prototype.</p>
</div>
<script>
  function swap() {{
    var s = document.getElementById('pres').value;
    document.getElementById('cloud').src = 'presidents/' + s + '.png';
    document.getElementById('cloud').alt = s + ' distinctive words';
  }}
</script>
</body>
</html>
"""
    HTML.write_text(html, encoding="utf-8")
    print(f"Wrote {len(made)} president clouds -> {OUT_DIR}")
    print(f"Wrote picker -> {HTML}")


if __name__ == "__main__":
    main()
