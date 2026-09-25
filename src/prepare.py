"""Sellable dataset preparation and export utilities.

Takes a processed DataFrame and packages it for sale/distribution:
  - Drops any PII columns listed in config.yaml
  - Exports to CSV, Excel, and/or Parquet
  - Generates a plain-text codebook (column descriptions)

Usage in a notebook:
    from src.prepare import package_dataset
    package_dataset(df, cfg, name="my_dataset", codebook={"col": "description"})
"""

from __future__ import annotations

import textwrap
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------------
# PII stripping
# ---------------------------------------------------------------------------

def strip_pii(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Drop columns listed under export.strip_pii_columns in config.yaml."""
    cols_to_drop = cfg.get("export", {}).get("strip_pii_columns", [])
    if cols_to_drop:
        existing = [c for c in cols_to_drop if c in df.columns]
        if existing:
            df = df.drop(columns=existing)
            print(f"Stripped PII columns: {existing}")
    return df


# ---------------------------------------------------------------------------
# Codebook
# ---------------------------------------------------------------------------

def build_codebook(
    df: pd.DataFrame,
    descriptions: dict[str, str] | None = None,
    project_name: str = "",
    notes: str = "",
) -> str:
    """Generate a plain-text codebook for the dataset.

    Args:
        df:           The export-ready DataFrame.
        descriptions: Dict mapping column name → human-readable description.
                      Columns not in the dict get a placeholder.
        project_name: Printed in the header.
        notes:        Free-text notes appended at the bottom (source info, license, etc.).

    Returns:
        Codebook as a string (written to a .md file by package_dataset).
    """
    descriptions = descriptions or {}
    today = date.today().isoformat()

    lines = [
        f"# {project_name} — Dataset Codebook",
        f"Generated: {today}",
        "",
        "## Columns",
        "",
    ]

    for col in df.columns:
        dtype = str(df[col].dtype)
        desc = descriptions.get(col, "_No description provided._")
        non_null = df[col].notna().sum()
        total = len(df)
        lines.append(f"### `{col}`")
        lines.append(f"- **Type**: `{dtype}`")
        lines.append(f"- **Non-null**: {non_null:,} / {total:,} ({non_null/total:.1%})")
        lines.append(f"- **Description**: {desc}")
        lines.append("")

    if notes:
        lines += ["## Notes", "", textwrap.dedent(notes).strip(), ""]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def package_dataset(
    df: pd.DataFrame,
    cfg: dict[str, Any],
    name: str,
    codebook: dict[str, str] | None = None,
    notes: str = "",
    formats: list[str] | None = None,
) -> dict[str, Path]:
    """Strip PII, export to configured formats, and write a codebook.

    Args:
        df:       Processed DataFrame ready for packaging.
        cfg:      Loaded config dict.
        name:     Base filename (no extension).
        codebook: Column description dict passed to build_codebook().
        notes:    Free-text appended to the codebook (source, license, etc.).
        formats:  Override config export.formats. Supported: csv, xlsx, parquet.

    Returns:
        Dict of {format: Path} for every file written.
    """
    df = strip_pii(df, cfg)

    export_dir = Path(cfg["paths"]["export"])
    export_dir.mkdir(parents=True, exist_ok=True)

    export_cfg = cfg.get("export", {})
    active_formats = formats or export_cfg.get("formats", ["csv"])
    include_codebook = export_cfg.get("include_codebook", True)
    project_name = cfg.get("project_name", name)

    written: dict[str, Path] = {}

    if "csv" in active_formats:
        p = export_dir / f"{name}.csv"
        df.to_csv(p, index=False, encoding=cfg["settings"]["encoding"])
        written["csv"] = p
        print(f"Exported CSV     → {p}")

    if "xlsx" in active_formats:
        p = export_dir / f"{name}.xlsx"
        with pd.ExcelWriter(p, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="data")
        written["xlsx"] = p
        print(f"Exported Excel   → {p}")

    if "parquet" in active_formats:
        p = export_dir / f"{name}.parquet"
        df.to_parquet(p, index=False, engine=cfg["settings"]["parquet_engine"])
        written["parquet"] = p
        print(f"Exported Parquet → {p}")

    if include_codebook:
        cb_text = build_codebook(df, descriptions=codebook, project_name=project_name, notes=notes)
        cb_path = export_dir / f"{name}_codebook.md"
        cb_path.write_text(cb_text, encoding="utf-8")
        written["codebook"] = cb_path
        print(f"Wrote codebook   → {cb_path}")

    print(f"\n✓  Package complete: {len(df):,} rows × {len(df.columns)} columns")
    return written


# ---------------------------------------------------------------------------
# Quick summary helpers (useful before packaging)
# ---------------------------------------------------------------------------

def value_counts_all(df: pd.DataFrame, top_n: int = 10) -> None:
    """Print top-N value counts for every column — quick sanity check."""
    for col in df.columns:
        print(f"\n── {col} ──")
        print(df[col].value_counts(dropna=False).head(top_n).to_string())


def numeric_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Return describe() output for numeric columns only, transposed for readability."""
    return df.select_dtypes("number").describe().T.round(2)


# ===========================================================================
# FEATURE ENGINEERING (03-prepare stage)
# ===========================================================================
# Derives the analysis-ready columns/tables from the cleaned speeches:
#   - per-speech language metrics: word count + self (I/me/my/mine) vs
#     collective (we/us/our/ours) pronoun use;
#   - institutional speech-type classification (so comparisons are like-for-like);
#   - word frequencies + TF-IDF distinctiveness (for word clouds / defining words).
# Tokenization is deliberately simple and transparent (lowercase word tokens via
# a regex, HTML entities decoded) so every count is explainable in the codebook —
# no hidden NLP model. Contractions ("I'm", "we'll", "let's") are handled
# explicitly. This is feature engineering, NOT cleaning — it lives here in the
# prepare stage (02-clean only does type/name normalization, dedupe, QC).

import re as _re

# Pronoun sets (apostrophes normalized to a straight quote first). Contractions
# are mapped to the pronoun they contain.
_SELF_PRONOUNS = {"i", "me", "my", "mine", "myself"}
_COLLECTIVE_PRONOUNS = {"we", "us", "our", "ours", "ourselves"}
_SELF_CONTRACTIONS = {"i'm", "i've", "i'll", "i'd"}
_COLLECTIVE_CONTRACTIONS = {"we're", "we've", "we'll", "we'd", "let's"}
# note: "let's" = "let us" → collective, a real first-person-plural call to action.

# Word tokenizer: keep intra-word apostrophes so contractions survive.
_WORD_RE = _re.compile(r"[a-z]+(?:'[a-z]+)?")


def tokenize(text: str) -> list[str]:
    """Lowercase word-tokenize, preserving contractions (apostrophes normalized).

    HTML entities in the source transcripts (``&ldquo;`` ``&mdash;`` ``&amp;``
    ``&nbsp;``) are decoded first so their fragments don't leak in as fake words.
    Curly apostrophes (\u2019) are normalized to straight quotes.
    """
    if not text:
        return []
    import html
    t = html.unescape(text).lower().replace("\u2019", "'")
    return _WORD_RE.findall(t)


def count_pronouns(text: str) -> dict[str, int]:
    """Count word tokens, self-pronouns, and collective-pronouns in one text.

    Contractions are attributed to the pronoun they contain (I'm→I, we'll→we,
    let's→we). Returns dict: word_count, self_count, collective_count.
    """
    tokens = tokenize(text)
    self_n = 0
    coll_n = 0
    for tok in tokens:
        if tok in _SELF_PRONOUNS or tok in _SELF_CONTRACTIONS:
            self_n += 1
        elif tok in _COLLECTIVE_PRONOUNS or tok in _COLLECTIVE_CONTRACTIONS:
            coll_n += 1
    return {"word_count": len(tokens), "self_count": self_n, "collective_count": coll_n}


def _title_label(title: str) -> str:
    """Return the descriptive part of a Miller Center title (after the colon)."""
    return title.split(":", 1)[1].strip() if ":" in title else (title or "").strip()


def classify_speech_type(title: str) -> str:
    """Bucket a speech into an institutional type from its title.

    Buckets: 'Inaugural Address', 'State of the Union', 'Annual Message',
    'Farewell Address', 'Press/News Conference', 'Address to Congress',
    'Nomination Acceptance', 'Debate', 'Fireside Chat', 'Oath of Office',
    'Other'. 'State of the Union' and 'Annual Message' are the SAME
    constitutional address under different era-labels — unify them with
    `sotu_series()` for the broad-coverage SOTU comparison.
    """
    l = _title_label(title).lower()
    if "inaugural address" in l:
        return "Inaugural Address"
    if "state of the union" in l:
        return "State of the Union"
    if "annual message" in l:
        return "Annual Message"
    if "farewell" in l:
        return "Farewell Address"
    if "press conference" in l or "news conference" in l:
        return "Press/News Conference"
    if "fireside" in l:
        return "Fireside Chat"
    if "debate" in l:
        return "Debate"
    if "acceptance" in l and ("nomination" in l or "convention" in l):
        return "Nomination Acceptance"
    if "oath" in l:
        return "Oath of Office"
    if "to congress" in l or "joint session" in l:
        return "Address to Congress"
    return "Other"


def sotu_series(speech_type: str) -> bool:
    """True if a speech is part of the unified State-of-the-Union series.

    The Article II annual address to Congress was labeled 'Annual Message'
    through 1928 and 'State of the Union' from 1929 on — same institutional
    speech, unified here for cross-president comparison.
    """
    return speech_type in ("State of the Union", "Annual Message")


def add_speech_metrics(df: pd.DataFrame, text_col: str = "transcript",
                       title_col: str = "title") -> pd.DataFrame:
    """Add per-speech language + classification columns.

    Adds: word_count, self_count, collective_count, self_per_1k, collective_per_1k,
    self_share (self / (self+collective)), speech_type, is_sotu_series. Rates are
    per 1,000 words so speeches of different lengths compare fairly. Pure/
    deterministic — reproducible in the pipeline.
    """
    out = df.copy()
    metrics = out[text_col].fillna("").map(count_pronouns).apply(pd.Series)
    out["word_count"] = metrics["word_count"]
    out["self_count"] = metrics["self_count"]
    out["collective_count"] = metrics["collective_count"]

    wc = out["word_count"].replace(0, pd.NA)
    out["self_per_1k"] = (out["self_count"] * 1000 / wc).astype("Float64").round(2)
    out["collective_per_1k"] = (out["collective_count"] * 1000 / wc).astype("Float64").round(2)
    denom = (out["self_count"] + out["collective_count"]).replace(0, pd.NA)
    out["self_share"] = (out["self_count"] / denom).astype("Float64").round(4)

    out["speech_type"] = out[title_col].fillna("").map(classify_speech_type)
    out["is_sotu_series"] = out["speech_type"].map(sotu_series)
    return out


# Transparent stopword list (function words + a little speech boilerplate). Kept
# explicit so the codebook can state exactly what was removed — no hidden list.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "nor", "so", "yet", "for", "of", "to",
    "in", "on", "at", "by", "with", "from", "as", "into", "onto", "upon", "over",
    "under", "about", "against", "between", "through", "during", "before", "after",
    "above", "below", "up", "down", "out", "off", "than", "then", "once", "here",
    "there", "when", "where", "why", "how", "all", "any", "both", "each", "few",
    "more", "most", "other", "some", "such", "no", "not", "only", "own", "same",
    "too", "very", "can", "will", "just", "should", "now",
    "i", "me", "my", "mine", "myself", "we", "us", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves", "he", "him", "his",
    "himself", "she", "her", "hers", "herself", "it", "its", "itself", "they",
    "them", "their", "theirs", "themselves", "this", "that", "these", "those",
    "who", "whom", "whose", "which", "what",
    "am", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "having", "do", "does", "did", "doing", "would", "could", "shall", "may",
    "might", "must", "ought",
    "i'm", "i've", "i'll", "i'd", "we're", "we've", "we'll", "we'd", "let's",
    "don't", "it's", "that's", "cannot",
    "upon", "great", "every", "made", "make", "also",
    "one", "two", "many", "much", "well", "still", "even", "government",
}


def stopwords() -> set[str]:
    """Return the project's transparent stopword set (copy)."""
    return set(_STOPWORDS)


def word_frequencies(text: str, extra_stop: set[str] | None = None,
                     min_len: int = 3):
    """Count content-word frequencies in one text (stopwords removed).

    Tokens shorter than ``min_len`` and any stopword are dropped. Returns a
    collections.Counter of token -> count.
    """
    import collections
    stop = _STOPWORDS | (extra_stop or set())
    toks = [t for t in tokenize(text)
            if len(t) >= min_len and t not in stop and "'" not in t]
    return collections.Counter(toks)


def top_words_by_group(df: pd.DataFrame, group_col: str, text_col: str,
                       top_n: int = 50, extra_stop: set[str] | None = None,
                       min_len: int = 3) -> pd.DataFrame:
    """Aggregate content-word frequencies per group (e.g. per president).

    Returns long DataFrame: [group_col, word, count, rank] with the top_n words
    per group by raw frequency. Feeds the "common words" word cloud.
    """
    import collections
    rows: list[dict[str, Any]] = []
    for g, sub in df.groupby(group_col):
        counter: collections.Counter = collections.Counter()
        for txt in sub[text_col].fillna(""):
            counter.update(word_frequencies(txt, extra_stop=extra_stop, min_len=min_len))
        for rank, (word, count) in enumerate(counter.most_common(top_n), start=1):
            rows.append({group_col: g, "word": word, "count": count, "rank": rank})
    return pd.DataFrame(rows)


def distinctive_words_by_group(df: pd.DataFrame, group_col: str, text_col: str,
                               top_n: int = 50, extra_stop: set[str] | None = None,
                               min_len: int = 4) -> pd.DataFrame:
    """TF-IDF: words that DISTINGUISH each group from the others.

    Each group (president) = one document (all their speeches). Score = term
    frequency (per 10k content words) × log(N_groups / groups_using_word). High
    score = common for this president, rare across presidents = their defining
    vocabulary. Pure Python (no sklearn), math inspectable.

    Returns long DataFrame: [group_col, word, tf_per_10k, idf, tfidf, rank].
    """
    import collections
    import math

    group_counts: dict[Any, "collections.Counter"] = {}
    group_totals: dict[Any, int] = {}
    doc_freq: "collections.Counter" = collections.Counter()

    for g, sub in df.groupby(group_col):
        counter: collections.Counter = collections.Counter()
        for txt in sub[text_col].fillna(""):
            counter.update(word_frequencies(txt, extra_stop=extra_stop, min_len=min_len))
        group_counts[g] = counter
        group_totals[g] = sum(counter.values())
        for word in counter:
            doc_freq[word] += 1

    n_groups = len(group_counts)
    rows: list[dict[str, Any]] = []
    for g, counter in group_counts.items():
        total = group_totals[g] or 1
        scored = []
        for word, cnt in counter.items():
            if cnt < 3:  # ignore ultra-rare in-group words (noise)
                continue
            tf = cnt * 10000.0 / total
            idf = math.log(n_groups / doc_freq[word])
            scored.append((word, tf, idf, tf * idf))
        scored.sort(key=lambda x: x[3], reverse=True)
        for rank, (word, tf, idf, tfidf) in enumerate(scored[:top_n], start=1):
            rows.append({group_col: g, "word": word, "tf_per_10k": round(tf, 2),
                         "idf": round(idf, 3), "tfidf": round(tfidf, 2), "rank": rank})
    return pd.DataFrame(rows)


def build_president_terms(terms_csv: str | Path, speeches: pd.DataFrame,
                          retrieval_date: str | None = None) -> pd.DataFrame:
    """Build the president tenure table (days in office + tenure-weighted rates).

    Reads a curated CSV of term_start/term_end dates (one row per continuous
    span; non-consecutive presidencies get multiple rows), sums days per
    president, and joins the corpus speech counts to derive speeches_per_year.
    `reliable_rate` flags tenures < 1 year (tiny-denominator artifacts like
    W. Harrison / Garfield) so a per-year rate isn't read as comparable.
    """
    terms_raw = pd.read_csv(terms_csv, parse_dates=["term_start", "term_end"])
    terms_raw["days"] = (terms_raw["term_end"] - terms_raw["term_start"]).dt.days
    terms = (terms_raw.groupby("president", as_index=False)["days"].sum()
             .rename(columns={"days": "days_in_office"}))
    terms["years_in_office"] = (terms["days_in_office"] / 365.25).round(2)

    n_speeches = (speeches.groupby("president", as_index=False).size()
                  .rename(columns={"size": "n_speeches"}))
    terms = terms.merge(n_speeches, on="president", how="left")
    terms["n_speeches"] = terms["n_speeches"].fillna(0).astype(int)
    terms["speeches_per_year"] = (terms["n_speeches"] / terms["years_in_office"]).round(2)
    terms["reliable_rate"] = terms["years_in_office"] >= 1.0
    return terms
