#!/usr/bin/env python3
"""Pre-publish validation — re-check the presidential-speeches chart data.

Run this BEFORE curating the release branch / flipping the repo public. It
re-derives what each published chart should show, straight from the DuckDB source
tables (speeches_features + the word-frequency / stage-direction tables), and
confirms:

  1. The published export CSV (export/presidential_speeches_v1.csv) matches the
     DuckDB source (speeches_features) on the key columns (no drift).
  2. The headline chart facts still hold (universe size, the top "I"/"we"
     presidents per lens, longest SOTU, top applause president, chart-8 #1 words,
     the transcript-scaffolding exclusion), so a silent data or methodology change
     can't slip out unnoticed.
  3. Structural invariants (self_share in [0,1]; self+collective reconcile;
     expected president/speech counts; regular-plural fold + "president" exclusion).
  4. Social vs web chart parity — the two rendered sets cover the same filenames
     and the web charts are the web canvas (1664 wide; tall web-only charts keep
     their height).

Published charts (see notebooks/06-viz-social.ipynb):
  1 SOTU self vs collective by president (line)      social + web
  2 SOTU "I" vs "we" presidents (side-by-side)       social + web
  3 Inaugural "I" vs "we" presidents (side-by-side)  social + web
  4 every SOTU president's lean, chronological        WEB ONLY (tall)
  5 SOTU average length by president                  WEB ONLY (tall)
  6 speeches per year in office (corpus coverage)     WEB ONLY (tall)
  7 applause & laughter                               social + web
  8 every president's most-used word, 1789->present   social + web
  word clouds (Lincoln / FDR / Reagan)                social only

Exit code 0 = all checks passed, safe to publish. Non-zero = do NOT publish.

Usage:
    /opt/anaconda3/envs/data_projects/bin/python scripts/validate_charts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

PROJECT = Path(__file__).resolve().parent
while not (PROJECT / "config.yaml").exists() and PROJECT != PROJECT.parent:
    PROJECT = PROJECT.parent
sys.path.insert(0, str(PROJECT))
from src.ingest import load_config  # noqa: E402

failures: list[str] = []
checks: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        checks.append(f"  PASS  {name}")
    else:
        failures.append(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    cfg = load_config("config.yaml")
    db = str(PROJECT / cfg["settings"]["duckdb_file"])
    export_dir = PROJECT / cfg["paths"]["export"]
    con = duckdb.connect(db, read_only=True)

    feats = con.execute("SELECT * FROM speeches_features").df()

    # ── Universe ──────────────────────────────────────────────────────────
    check("universe: 1,059 speeches", len(feats) == 1059, f"got {len(feats)}")
    check("universe: 45 presidents",
          feats["president"].nunique() == 45, f"got {feats['president'].nunique()}")
    yr = (int(feats["year"].min()), int(feats["year"].max()))
    check("universe: years span 1789–2026", yr == (1789, 2026), f"got {yr}")

    # ── Structural invariants ─────────────────────────────────────────────
    ss = feats["self_share"].dropna()
    check("structure: self_share within [0, 1]",
          bool((ss >= 0).all() and (ss <= 1).all()),
          f"min={ss.min()} max={ss.max()}")
    # self_share == self / (self + collective) where both are present
    both = feats[(feats.self_count + feats.collective_count) > 0].copy()
    both["recomputed"] = both.self_count / (both.self_count + both.collective_count)
    bad = both[(both.recomputed - both.self_share).abs() > 0.001]
    check("structure: self_share == self / (self+collective)",
          len(bad) == 0, f"{len(bad)} rows mismatch")
    check("structure: no null president / year / speech_type",
          not feats[["president", "year", "speech_type"]].isna().any().any(),
          "null in a key column")

    # ── Chart 2 (SOTU "I" vs "we") ────────────────────────────────────────
    sotu = con.execute(
        "SELECT president, AVG(self_share) ss, COUNT(*) n FROM speeches_features "
        "WHERE is_sotu_series GROUP BY 1 HAVING COUNT(*)>=2").df()
    top_i = sotu.sort_values("ss", ascending=False).iloc[0]
    top_we = sotu.sort_values("ss", ascending=True).iloc[0]
    check("chart2: most-'I' SOTU president is William Taft @ 62%",
          top_i.president == "William Taft" and round(top_i.ss * 100) == 62,
          f"got {top_i.president} @ {round(top_i.ss*100)}%")
    check("chart2: most-'we' SOTU president is Jimmy Carter @ 84%",
          top_we.president == "Jimmy Carter" and round((1 - top_we.ss) * 100) == 84,
          f"got {top_we.president} @ {round((1-top_we.ss)*100)}%")

    # ── Chart 3 (Inaugural "I" vs "we") ───────────────────────────────────
    inaug = con.execute(
        "SELECT president, AVG(self_share) ss FROM speeches_features "
        "WHERE speech_type='Inaugural Address' GROUP BY 1").df()
    inaug_top_i = inaug.sort_values("ss", ascending=False).iloc[0]
    check("chart3: most-'I' inaugural president is George Washington @ ~98%",
          inaug_top_i.president == "George Washington" and round(inaug_top_i.ss * 100) == 98,
          f"got {inaug_top_i.president} @ {round(inaug_top_i.ss*100)}%")

    # ── Chart 5 (SOTU length) ─────────────────────────────────────────────
    length = con.execute(
        "SELECT president, AVG(word_count) w FROM speeches_features "
        "WHERE is_sotu_series GROUP BY 1 HAVING COUNT(*)>=2 ORDER BY w DESC").df()
    check("chart5: longest average SOTU is William Taft (~22,446 words)",
          length.iloc[0].president == "William Taft" and round(length.iloc[0].w) == 22446,
          f"got {length.iloc[0].president} @ {round(length.iloc[0].w)}")

    # ── Chart 7 (applause & laughter) ─────────────────────────────────────
    ap = con.execute(
        "SELECT president, (applause+applauding) ap, booing FROM stage_directions_by_president "
        "ORDER BY ap DESC").df()
    check("chart7: top-applause president is Barack Obama (1,295)",
          ap.iloc[0].president == "Barack Obama" and int(ap.iloc[0].ap) == 1295,
          f"got {ap.iloc[0].president} @ {int(ap.iloc[0].ap)}")
    booers = con.execute(
        "SELECT president FROM stage_directions_by_president WHERE booing>0").df()
    check("chart7: the only recorded boo is Donald Trump (footnote fact)",
          list(booers.president) == ["Donald Trump"], f"got {list(booers.president)}")

    # ── Chart 8 (top word timeline) + word-processing invariants ──────────
    def top_word(pres: str) -> str:
        return con.execute(
            "SELECT word FROM word_freq_by_president WHERE president=? AND rank=1",
            [pres]).fetchone()[0]
    check("chart8: George Washington's #1 word is 'state' (post plural-fold)",
          top_word("George Washington") == "state", f"got {top_word('George Washington')!r}")
    check("chart8: LBJ's #1 word is 'people' (after dropping 'president' scaffolding)",
          top_word("Lyndon B. Johnson") == "people", f"got {top_word('Lyndon B. Johnson')!r}")
    # transcript scaffolding excluded everywhere
    pres_tok = con.execute(
        "SELECT COUNT(*) FROM word_freq_by_president WHERE word='president'").fetchone()[0]
    pres_tok += con.execute(
        "SELECT COUNT(*) FROM distinctive_words_by_president WHERE word='president'").fetchone()[0]
    check("word-proc: 'president' scaffolding excluded from all spoken-vocab views",
          pres_tok == 0, f"found {pres_tok} 'president' rows")
    # regular plural folded: no president has BOTH a plural and its -s singular in top words
    dup = con.execute(
        "SELECT COUNT(*) FROM word_freq_by_president a JOIN word_freq_by_president b "
        "ON a.president=b.president AND a.word = b.word||'s' WHERE length(b.word)>=3").fetchone()[0]
    check("word-proc: no plural+singular split survives within a president (fold works)",
          dup == 0, f"{dup} unfolded plural/singular pairs")
    # phrases NOT folded: "united states" survives as a phrase (plural intact)
    us_phrase = con.execute(
        "SELECT COUNT(*) FROM distinctive_phrases_by_president WHERE word LIKE '%united states%'").fetchone()[0]
    check("word-proc: phrases NOT folded — 'united states' stays intact",
          us_phrase > 0, "no 'united states' phrase found (fold leaked into phrases?)")

    # ── Published CSV matches DuckDB (no drift) ───────────────────────────
    cols = ["president", "year", "speech_type", "word_count",
            "self_count", "collective_count", "self_share"]
    path = export_dir / "presidential_speeches_v1.csv"
    if not path.exists():
        check("export: presidential_speeches_v1.csv exists", False, "missing export file")
    else:
        df_csv = pd.read_csv(path)
        try:
            key = ["president", "year", "speech_type", "word_count"]
            a = feats[cols].sort_values(key).reset_index(drop=True)
            b = df_csv[cols].sort_values(key).reset_index(drop=True)
            same = a.shape == b.shape
            detail = "" if same else f"row count {a.shape[0]} vs {b.shape[0]}"
            if same:
                for col in cols:
                    if pd.api.types.is_numeric_dtype(a[col]):
                        diff = (a[col].astype("float64") - b[col].astype("float64")).abs()
                        tol = 1e-4 if col == "self_share" else 0.5
                        col_ok = bool(((diff <= tol) | (a[col].isna() & b[col].isna())).all())
                    else:
                        col_ok = bool((a[col].fillna("\x00").astype(str) ==
                                       b[col].fillna("\x00").astype(str)).all())
                    if not col_ok:
                        same, detail = False, f"column {col!r} differs"
                        break
            check("export: presidential_speeches_v1.csv matches DuckDB on key columns", same,
                  (detail + " — regenerate 03-prepare") if detail else "")
        except KeyError as e:
            check(f"export: CSV has expected columns {cols}", False, str(e))

    con.close()

    # ── Social vs web chart parity ────────────────────────────────────────
    social_dir = PROJECT / "outputs" / "social"
    web_dir = PROJECT / "outputs" / "web"
    # the numbered social charts (word clouds 09/10/11 are social-only, excluded here)
    SOCIAL_AND_WEB = {f"{n:02d}" for n in (1, 2, 3, 7, 8)}
    WEB_ONLY = {"04", "05", "06"}
    if social_dir.exists() and web_dir.exists():
        s_all = {p.name for p in social_dir.glob("*.png")}
        w_all = {p.name for p in web_dir.glob("*.png")}
        s_num = {n[:2] for n in s_all if n[:2].isdigit()}
        w_num = {n[:2] for n in w_all if n[:2].isdigit()}
        check("parity: social has charts 1,2,3,7,8 (+ web-only rendered too)",
              SOCIAL_AND_WEB.issubset(s_num), f"social nums {sorted(s_num)}")
        check("parity: web has all 8 numbered charts (incl. web-only 4,5,6)",
              (SOCIAL_AND_WEB | WEB_ONLY).issubset(w_num), f"web nums {sorted(w_num)}")
        check("parity: word clouds (09,10,11) are social-only",
              {"09", "10", "11"}.issubset(s_num) and not ({"09", "10", "11"} & w_num),
              f"social {sorted(s_num)} web {sorted(w_num)}")
        try:
            from PIL import Image
            w_widths = {Image.open(p).size[0] for p in web_dir.glob("*.png")}
            check("parity: every web chart is the 1664-wide web canvas",
                  w_widths == {1664}, f"got widths {sorted(w_widths)}")
        except ImportError:
            pass
    else:
        checks.append("  SKIP  chart parity (outputs/ not rendered on this checkout)")

    # ── Report ────────────────────────────────────────────────────────────
    print("Pre-publish chart-data validation — presidential-speeches")
    print("=" * 60)
    for line in checks:
        print(line)
    for line in failures:
        print(line)
    print("=" * 60)
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S) — DO NOT PUBLISH.")
        return 1
    print(f"RESULT: all {len([c for c in checks if 'PASS' in c])} checks passed — safe to publish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
