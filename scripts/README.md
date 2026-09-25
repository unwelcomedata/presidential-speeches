# Scripts

## `build_president_pages.py`

Generates the interactive per-president word-cloud picker published on the site:
one word-cloud PNG per president × view (Distinctive / Most-used / Phrases) into
`docs/presidents/`, plus the `docs/presidents.html` picker that switches between
them. Reads the word-frequency and TF-IDF tables from the project DuckDB.

```bash
python scripts/build_president_pages.py
```

## Reproducing the dataset and charts

The pipeline itself lives in `src/` and is narrated stage by stage in the
`notebooks/` on the `main` branch (this `release` branch omits the notebooks):

- `src/ingest.py` — fetch + unpack the Miller Center archive into `data/raw/`.
- `src/clean_quality.py` — clean/standardize into DuckDB + Parquet.
- `src/prepare.py` — feature engineering: pronoun metrics, speech-type
  classification, the transparent word tokenizer, regular-plural folding,
  transcript-scaffolding exclusion, word-frequency / TF-IDF tables, and the
  packaged export + codebook.

`config.yaml` documents the source and settings. See `SOURCES.md` for the full
method, definitions, the written/spoken series break, and known limitations.
