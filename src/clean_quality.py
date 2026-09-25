"""DuckDB-backed cleaning and data quality utilities.

Workflow:
  1. Load raw DataFrame into DuckDB (in the project .duckdb file).
  2. Run cleaning operations as SQL — fast, inspectable, reproducible.
  3. Run quality checks and print a report before writing interim output.
  4. Save cleaned table as Parquet to data/interim/.

All functions accept and return pandas DataFrames so notebooks stay readable,
but the heavy lifting happens inside DuckDB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


# ---------------------------------------------------------------------------
# Source provenance (_sources metadata table)
# ---------------------------------------------------------------------------

_SOURCES_SCHEMA = """
CREATE TABLE IF NOT EXISTS _sources (
    duckdb_table  VARCHAR,
    source_name   VARCHAR,
    url           VARCHAR,
    license       VARCHAR,
    notes         VARCHAR,
    retrieved     VARCHAR,
    methodology   VARCHAR,
    series_breaks VARCHAR
)
"""

# Columns that older databases may be missing (added after the original schema).
_SOURCES_ADDED_COLUMNS = ("methodology", "series_breaks")


def _ensure_sources_columns(con: duckdb.DuckDBPyConnection) -> None:
    """Add later-added _sources columns to pre-existing databases (idempotent)."""
    existing = {row[1] for row in con.execute("PRAGMA table_info('_sources')").fetchall()}
    for col in _SOURCES_ADDED_COLUMNS:
        if col not in existing:
            con.execute(f"ALTER TABLE _sources ADD COLUMN {col} VARCHAR")


def register_source(
    con: duckdb.DuckDBPyConnection,
    table: str,
    name: str,
    url: str = "",
    license: str = "",
    notes: str = "",
    retrieved: str = "",
    methodology: str = "",
    series_breaks: str = "",
) -> None:
    """Register a data source in the _sources metadata table.

    Call this after loading a new table into DuckDB to maintain full provenance.
    Replaces any existing entry for the same table name.

    Every source MUST document, in SOURCES.md and ideally here, how the source
    collects and defines its data (methodology) and any dates/boundaries across
    which the numbers are not comparable (series_breaks). These prevent
    apples-to-oranges comparisons (e.g. a definition that changed mid-series).

    Args:
        con:           Open DuckDB connection.
        table:         DuckDB table name this source populates.
        name:          Human-readable source name (e.g., "NHTSA FARS 2024").
        url:           Direct URL to the data file or page.
        license:       License string (e.g., "Public domain", "CC-BY 4.0").
        notes:         Any caveats or field descriptions.
        retrieved:     Date retrieved as ISO string (YYYY-MM-DD). Defaults to today.
        methodology:   How the source collects and defines the data.
        series_breaks: Dates/boundaries across which the numbers are NOT comparable.
    """
    from datetime import date as _date

    if not retrieved:
        retrieved = _date.today().isoformat()

    con.execute(_SOURCES_SCHEMA)
    _ensure_sources_columns(con)
    con.execute("DELETE FROM _sources WHERE duckdb_table = ?", [table])
    con.execute(
        """INSERT INTO _sources
           (duckdb_table, source_name, url, license, notes, retrieved,
            methodology, series_breaks)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [table, name, url, license, notes, retrieved, methodology, series_breaks],
    )


def get_sources(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return the full _sources provenance table as a DataFrame."""
    con.execute(_SOURCES_SCHEMA)
    return con.execute("SELECT * FROM _sources ORDER BY duckdb_table").df()


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def get_connection(cfg: dict[str, Any]) -> duckdb.DuckDBPyConnection:
    """Open (or create) the project DuckDB file and return a connection."""
    db_path = Path(cfg["settings"]["duckdb_file"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))


def load_to_duckdb(
    df: pd.DataFrame,
    table_name: str,
    con: duckdb.DuckDBPyConnection,
    replace: bool = True,
) -> None:
    """Register a DataFrame as a DuckDB table.

    Args:
        df:         Source DataFrame.
        table_name: Name for the table inside DuckDB.
        con:        Open DuckDB connection.
        replace:    Drop and recreate if the table already exists.
    """
    if replace:
        con.execute(f"DROP TABLE IF EXISTS {table_name}")
    # DuckDB can read a pandas DataFrame directly via the local variable name
    con.execute(f"CREATE TABLE {table_name} AS SELECT * FROM df")


# ---------------------------------------------------------------------------
# Cleaning operations
# ---------------------------------------------------------------------------

def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase column names and replace spaces/hyphens with underscores."""
    df.columns = [
        c.strip().lower().replace(" ", "_").replace("-", "_") for c in df.columns
    ]
    return df


def clean_table(
    df: pd.DataFrame,
    table_name: str,
    con: duckdb.DuckDBPyConnection,
    drop_duplicate_subset: list[str] | None = None,
    strip_columns: list[str] | None = None,
    cast_map: dict[str, str] | None = None,
    where_filter: str | None = None,
) -> pd.DataFrame:
    """Run a cleaning pass on a DataFrame inside DuckDB and return the result.

    Args:
        df:                    Raw DataFrame to clean.
        table_name:            Staging table name in DuckDB.
        con:                   Open DuckDB connection.
        drop_duplicate_subset: Column(s) to use for deduplication (None = all cols).
        strip_columns:         String columns to TRIM whitespace from.
        cast_map:              Dict of {column: duckdb_type} to cast, e.g. {"year": "INTEGER"}.
        where_filter:          Optional SQL WHERE clause (no 'WHERE' keyword) to filter rows.

    Returns:
        Cleaned DataFrame.
    """
    load_to_duckdb(df, table_name, con)

    # Build SELECT list with optional casts and trims
    col_exprs = []
    for col in df.columns:
        expr = f'"{col}"'
        if cast_map and col in cast_map:
            expr = f"TRY_CAST({expr} AS {cast_map[col]}) AS \"{col}\""
        elif strip_columns and col in strip_columns:
            expr = f"TRIM({expr}) AS \"{col}\""
        else:
            expr = f"{expr}"
        col_exprs.append(expr)

    select_clause = ", ".join(col_exprs)
    query = f"SELECT {select_clause} FROM {table_name}"
    if where_filter:
        query += f" WHERE {where_filter}"

    cleaned = con.execute(query).df()

    # Deduplication via pandas (easier to express cross-DB)
    if drop_duplicate_subset is not None:
        cleaned = cleaned.drop_duplicates(subset=drop_duplicate_subset)
    else:
        cleaned = cleaned.drop_duplicates()

    return cleaned.reset_index(drop=True)


def run_sql(sql: str, con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Run arbitrary SQL against the open DuckDB connection and return a DataFrame.

    Useful for custom joins, aggregations, and feature engineering in notebooks.

    Example:
        run_sql("SELECT state, AVG(rate) as avg_rate FROM cleaned GROUP BY state", con)
    """
    return con.execute(sql).df()


# ---------------------------------------------------------------------------
# Quality checks
# ---------------------------------------------------------------------------

def quality_report(
    df: pd.DataFrame,
    table_name: str,
    con: duckdb.DuckDBPyConnection,
    required_columns: list[str] | None = None,
    max_null_pct: float = 0.10,
) -> dict[str, Any]:
    """Run quality checks and print a summary report.

    Checks:
      - Row count
      - Null percentage per column (warns if above max_null_pct)
      - Duplicate row count
      - Presence of required columns

    Returns a dict with check results (useful for notebook assertions).
    """
    load_to_duckdb(df, f"_qc_{table_name}", con, replace=True)

    row_count = con.execute(f"SELECT COUNT(*) FROM _qc_{table_name}").fetchone()[0]
    dup_count = row_count - con.execute(
        f"SELECT COUNT(*) FROM (SELECT DISTINCT * FROM _qc_{table_name})"
    ).fetchone()[0]

    null_pcts: dict[str, float] = {}
    warnings: list[str] = []
    for col in df.columns:
        nulls = con.execute(
            f'SELECT COUNT(*) FROM _qc_{table_name} WHERE "{col}" IS NULL'
        ).fetchone()[0]
        pct = nulls / row_count if row_count else 0.0
        null_pcts[col] = round(pct, 4)
        if pct > max_null_pct:
            warnings.append(f"  ⚠  '{col}' is {pct:.1%} null (threshold {max_null_pct:.0%})")

    missing_cols: list[str] = []
    if required_columns:
        missing_cols = [c for c in required_columns if c not in df.columns]
        if missing_cols:
            warnings.append(f"  ✗  Missing required columns: {missing_cols}")

    print(f"\n── Quality report: {table_name} ──────────────────")
    print(f"  Rows       : {row_count:,}")
    print(f"  Duplicates : {dup_count:,}")
    print(f"  Null %     :")
    for col, pct in null_pcts.items():
        flag = " ⚠" if pct > max_null_pct else ""
        print(f"    {col:<30} {pct:.1%}{flag}")
    if warnings:
        print("\n  Warnings:")
        for w in warnings:
            print(w)
    else:
        print("\n  ✓  No issues found.")
    print("─" * 50)

    return {
        "row_count": row_count,
        "duplicate_count": dup_count,
        "null_pcts": null_pcts,
        "missing_required_columns": missing_cols,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------

def save_interim(df: pd.DataFrame, cfg: dict[str, Any], filename: str) -> Path:
    """Save a cleaned DataFrame to data/interim/ as Parquet."""
    out = Path(cfg["paths"]["data_interim"]) / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False, engine=cfg["settings"]["parquet_engine"])
    print(f"Saved interim → {out}  ({len(df):,} rows)")
    return out


def save_processed(df: pd.DataFrame, cfg: dict[str, Any], filename: str) -> Path:
    """Save an analysis-ready DataFrame to data/processed/ as Parquet."""
    out = Path(cfg["paths"]["data_processed"]) / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False, engine=cfg["settings"]["parquet_engine"])
    print(f"Saved processed → {out}  ({len(df):,} rows)")
    return out


# ---------------------------------------------------------------------------
# Presidential-speech text analysis (project-specific)
# ---------------------------------------------------------------------------
# These derive the per-speech language metrics the project's lead question needs:
# word count, and self (I/me/my/mine) vs collective (we/us/our/ours) pronoun use.
# Tokenization is deliberately simple and transparent (lowercase word tokens via
# a Unicode-word regex) so the counts are explainable in a codebook — no hidden
# NLP model. Contractions matter here ("I'm", "we'll", "let's"), so they are
# handled explicitly rather than split away.

import re as _re

# Pronoun sets. Keys are the surface tokens we count (apostrophes normalized to
# a straight quote first). Contractions are mapped to the pronoun they contain.
_SELF_PRONOUNS = {"i", "me", "my", "mine", "myself"}
_COLLECTIVE_PRONOUNS = {"we", "us", "our", "ours", "ourselves"}

# Contraction → leading pronoun (so "I'm"/"we'll"/"we're" count as I / we).
_SELF_CONTRACTIONS = {"i'm", "i've", "i'll", "i'd"}
_COLLECTIVE_CONTRACTIONS = {"we're", "we've", "we'll", "we'd", "let's"}
# note: "let's" = "let us" → collective, a real first-person-plural call to action.

# Word tokenizer: keep intra-word apostrophes (straight quote) so contractions
# survive; everything else is a boundary.
_WORD_RE = _re.compile(r"[a-z]+(?:'[a-z]+)?")


def tokenize(text: str) -> list[str]:
    """Lowercase word-tokenize, preserving contractions (apostrophes normalized).

    Returns a list of lowercase tokens. HTML entities in the source transcripts
    (e.g. ``&ldquo;`` ``&mdash;`` ``&amp;`` ``&nbsp;``) are decoded first so their
    fragments ("ldquo", "mdash", "amp") don't leak in as fake words. Curly
    apostrophes (\u2019) are normalized to straight quotes so contractions like
    "I\u2019m" and "I'm" tokenize identically.
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


# Speech-type classification -------------------------------------------------
# The Miller Center title format is "Month DD, YYYY: <Description>". The text
# after the colon is a human label we bucket into institutional speech types.
# This is what lets us compare LIKE-with-LIKE (SOTU vs SOTU) instead of pooling
# apples and oranges across the whole curated corpus.

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
    `sotu_series()` when building the broad-coverage SOTU comparison.
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
    through 1928 and 'State of the Union' from 1929 on. Both are the same
    institutional speech — this unifies them for cross-president comparison.
    """
    return speech_type in ("State of the Union", "Annual Message")


def add_speech_metrics(df: pd.DataFrame, text_col: str = "transcript",
                       title_col: str = "title") -> pd.DataFrame:
    """Add per-speech language + classification columns to a speeches DataFrame.

    Adds: word_count, self_count, collective_count, self_per_1k, collective_per_1k,
    self_share (self / (self+collective)), speech_type, is_sotu_series.
    Rates are per 1,000 words so speeches of different lengths are comparable.
    Pure/deterministic — no external state — so it's reproducible in the pipeline.
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


# Word frequency + distinctiveness (for word clouds / "defining words") ------
# A transparent stopword list (function words + a few speech-boilerplate terms).
# Kept explicit so the codebook can state exactly what was removed — no hidden
# library list. Extend deliberately, not reflexively.

_STOPWORDS = {
    # articles / conjunctions / prepositions
    "a", "an", "the", "and", "or", "but", "nor", "so", "yet", "for", "of", "to",
    "in", "on", "at", "by", "with", "from", "as", "into", "onto", "upon", "over",
    "under", "about", "against", "between", "through", "during", "before", "after",
    "above", "below", "up", "down", "out", "off", "than", "then", "once", "here",
    "there", "when", "where", "why", "how", "all", "any", "both", "each", "few",
    "more", "most", "other", "some", "such", "no", "not", "only", "own", "same",
    "too", "very", "can", "will", "just", "should", "now",
    # pronouns / determiners (incl. the I/we set — counted separately, not "words")
    "i", "me", "my", "mine", "myself", "we", "us", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves", "he", "him", "his",
    "himself", "she", "her", "hers", "herself", "it", "its", "itself", "they",
    "them", "their", "theirs", "themselves", "this", "that", "these", "those",
    "who", "whom", "whose", "which", "what",
    # be / have / do / modal verbs
    "am", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "having", "do", "does", "did", "doing", "would", "could", "shall", "may",
    "might", "must", "ought",
    # common contractions (post-tokenizer these survive as one token)
    "i'm", "i've", "i'll", "i'd", "we're", "we've", "we'll", "we'd", "let's",
    "don't", "it's", "that's", "we", "cannot",
    # speech boilerplate that is not "distinctive vocabulary"
    "shall", "upon", "great", "every", "made", "make", "must", "us", "also",
    "one", "two", "many", "much", "well", "still", "even", "much", "government",
}


def stopwords() -> set[str]:
    """Return the project's transparent stopword set (copy)."""
    return set(_STOPWORDS)


def word_frequencies(text: str, extra_stop: set[str] | None = None,
                     min_len: int = 3) -> "collections.Counter":
    """Count content-word frequencies in one text (stopwords removed).

    Tokens shorter than ``min_len`` and any stopword are dropped. Returns a
    collections.Counter of token -> count. Uses the same transparent tokenizer
    as the pronoun counts so results are consistent and codebook-explainable.
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

    Returns a long DataFrame: [group_col, word, count, rank] with the top_n
    words per group by raw frequency. Good for the "common words" word cloud.
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

    Each group (president) is one "document" = all their speeches concatenated.
    Score = term frequency (within the group, per 10k content words) × inverse
    document frequency (log(N_groups / groups_using_word)). High score = the word
    is common for this president but rare across presidents overall — i.e. their
    "defining" vocabulary. Pure Python (no sklearn) so it stays dependency-light
    and the math is inspectable.

    Returns long DataFrame: [group_col, word, tf_per_10k, idf, tfidf, rank].
    """
    import collections
    import math

    group_counts: dict[Any, collections.Counter] = {}
    group_totals: dict[Any, int] = {}
    doc_freq: collections.Counter = collections.Counter()  # groups using each word

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
            # ignore ultra-rare words in the group (noise)
            if cnt < 3:
                continue
            tf = cnt * 10000.0 / total
            idf = math.log(n_groups / doc_freq[word])
            scored.append((word, tf, idf, tf * idf))
        scored.sort(key=lambda x: x[3], reverse=True)
        for rank, (word, tf, idf, tfidf) in enumerate(scored[:top_n], start=1):
            rows.append({group_col: g, "word": word, "tf_per_10k": round(tf, 2),
                         "idf": round(idf, 3), "tfidf": round(tfidf, 2), "rank": rank})
    return pd.DataFrame(rows)
