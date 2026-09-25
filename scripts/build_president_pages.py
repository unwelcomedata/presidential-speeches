#!/usr/bin/env python3
"""Build the per-president word-cloud picker (exploration prototype).

Generates TWO word-cloud PNGs per president:
  - <slug>_distinctive.png  — TF-IDF: words used far more than OTHER presidents
                              (from distinctive_words_by_president)
  - <slug>_common.png       — raw frequency: words the president used most, minus
                              stopwords (from word_freq_by_president)
into docs/presidents/, plus a docs/presidents.html page with a president <select>
AND a view-type toggle (distinctive vs common) that swaps the <img> src —
mirroring the countries-income-disparity picker.

The two views let the owner balance social picks across presidents without
duplicating anyone (some presidents read better as "distinctive", others as
"common"). EXPLORATION prototype for owner review, not a published artifact.

Run from the project root (any env with wordcloud + PIL + duckdb):
    python scripts/build_president_pages.py

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
from chart_templates import word_cloud  # noqa: E402

DB = PROJECT / "data" / "project.duckdb"
OUT_DIR = PROJECT / "docs" / "presidents"
HTML = PROJECT / "docs" / "presidents.html"
SOURCE = "Miller Center (UVA) speech archive"

# The two views: key -> (button label, DuckDB table, weight col, title tail, subtitle).
# "distinctive" = words unusually characteristic of this president vs others (TF-IDF).
# "most-used"   = this president's own most-frequent words (NOT "words in common with
#                 others" — that phrasing misread; this is their raw top vocabulary).
VIEWS = {
    "distinctive": (
        "Distinctive", "distinctive_words_by_president", "tfidf",
        "distinctive words",
        "Words this president used far more than OTHER presidents (TF-IDF).",
    ),
    "most-used": (
        "Most-used", "word_freq_by_president", "count",
        "most-used words",
        "This president\u2019s most frequently spoken words (common function words removed).",
    ),
    "phrases": (
        "Phrases", "distinctive_phrases_by_president", "tfidf",
        "distinctive phrases",
        "Two-word phrases this president used far more than others (\u201cunited states\u201d "
        "as one phrase, not two words).",
    ),
}


def slug(name: str) -> str:
    """Filesystem-safe slug for a president name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB), read_only=True)

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

    view_data = {
        v: con.execute(f"SELECT president, word, {wcol} FROM {tbl}").df()
        for v, (_lbl, tbl, wcol, _t, _s) in VIEWS.items()
    }
    con.close()

    made = []  # (name, slug, n_speeches)
    for _, row in presidents.iterrows():
        name = row["president"]
        s = slug(name)
        rendered_any = False
        for view, (_lbl, tbl, wcol, ttail, sub) in VIEWS.items():
            df = view_data[view]
            words = df[df["president"] == name][["word", wcol]]
            if words.empty:
                continue
            img = word_cloud(
                df=words, word_col="word", weight_col=wcol,
                title=f"{name} \u2014 {ttail}",
                subtitle=f"{sub} Curated corpus; speech as delivered (ghostwriting).",
                source=SOURCE, img_width=1600, img_height=900,
            )
            img.save(OUT_DIR / f"{s}_{view}.png", format="PNG", optimize=True)
            rendered_any = True
        if rendered_any:
            made.append((name, s, int(row["n_speeches"])))

    import time
    build_id = str(int(time.time()))  # cache-buster: changes every regeneration
    default_slug = made[0][1] if made else ""
    view_keys = list(VIEWS.keys())
    default_view = view_keys[0]
    options = "\n".join(
        f'      <option value="{s}">{n} ({n_sp} speeches)</option>'
        for n, s, n_sp in made
    )
    # Toggle buttons + JS generated from VIEWS (no hardcoded view names).
    buttons = "\n".join(
        f'      <button id="btn-{v}" class="{"active" if v == default_view else ""}" '
        f"onclick=\"setView('{v}')\">{VIEWS[v][0]}</button>"
        for v in view_keys
    )
    btn_js = "\n    ".join(
        f"document.getElementById('btn-{v}').className = (view==='{v}')?'active':'';"
        for v in view_keys
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Presidential speeches \u2014 word clouds by president</title>
<style>
  body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; margin: 0;
          color: #1c2530; background: #fff; }}
  .wrap {{ max-width: 960px; margin: 0 auto; padding: 24px 16px 48px; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  p.lead {{ color: #55606b; font-size: 15px; margin: 0 0 18px; line-height: 1.5; }}
  .controls {{ margin: 0 0 16px; display: flex; gap: 20px; flex-wrap: wrap; align-items: center; }}
  label {{ font-weight: 600; font-size: 14px; margin-right: 8px; }}
  select {{ font-size: 15px; padding: 7px 10px; border: 1px solid #c7ced5;
            border-radius: 6px; background: #fff; min-width: 320px; }}
  .seg button {{ font-size: 14px; padding: 7px 14px; border: 1px solid #c7ced5;
            background: #fff; cursor: pointer; }}
  .seg button:first-child {{ border-radius: 6px 0 0 6px; }}
  .seg button:last-child {{ border-radius: 0 6px 6px 0; border-left: none; }}
  .seg button.active {{ background: #005F73; color: #fff; border-color: #005F73; }}
  .chart img {{ width: 100%; height: auto; border: 1px solid #eee; border-radius: 6px; }}
  .note {{ color: #77818b; font-size: 13px; margin-top: 14px; line-height: 1.5; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Word clouds by president</h1>
  <p class="lead">
    Pick a president and a view. <b>Distinctive</b> = words they used far more than
    other presidents (TF-IDF). <b>Most-used</b> = their own most-frequent words
    (common function words removed). Word size = weight. Only words the president
    actually spoke \u2014 transcription cues like [Applause]/[Laughter] are excluded
    (see the separate audience-reaction chart). Curated set of major speeches,
    measured as delivered (many were ghostwritten).
  </p>
  <div class="controls">
    <span><label for="pres">President</label>
    <select id="pres" onchange="swap()">
{options}
    </select></span>
    <span class="seg">
{buttons}
    </span>
  </div>
  <div class="chart">
    <img id="cloud" src="presidents/{default_slug}_{default_view}.png?v={build_id}" alt="word cloud"
         onerror="this.alt='(cloud not generated for this president/view)';">
  </div>
  <p class="note">Source: {SOURCE}. Exploration prototype. build {build_id}</p>
</div>
<script>
  // ?v=BUILD is a cache-buster so the browser always loads the current PNGs
  // (regenerating the picker changes BUILD, forcing a fresh fetch).
  var BUILD = '{build_id}';
  var view = '{default_view}';
  function render() {{
    var s = document.getElementById('pres').value;
    document.getElementById('cloud').src = 'presidents/' + s + '_' + view + '.png?v=' + BUILD;
    document.getElementById('cloud').alt = s + ' ' + view + ' words';
    {btn_js}
  }}
  function swap() {{ render(); }}
  function setView(v) {{ view = v; render(); }}
</script>
</body>
</html>
"""
    HTML.write_text(html, encoding="utf-8")
    print(f"Wrote {len(made)} presidents x {len(VIEWS)} views = "
          f"{len(made) * len(VIEWS)} clouds -> {OUT_DIR}")
    print(f"Wrote picker -> {HTML}")


if __name__ == "__main__":
    main()
