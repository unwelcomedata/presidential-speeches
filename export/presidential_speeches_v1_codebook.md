# presidential-speeches — Dataset Codebook
Generated: 2026-09-25

## Columns

### `president`
- **Type**: `object`
- **Non-null**: 1,059 / 1,059 (100.0%)
- **Description**: U.S. president who delivered the speech.

### `speech_date`
- **Type**: `datetime64[us]`
- **Non-null**: 1,059 / 1,059 (100.0%)
- **Description**: Date of delivery (YYYY-MM-DD).

### `year`
- **Type**: `int32`
- **Non-null**: 1,059 / 1,059 (100.0%)
- **Description**: Year of delivery.

### `title`
- **Type**: `object`
- **Non-null**: 1,059 / 1,059 (100.0%)
- **Description**: Miller Center speech title.

### `url`
- **Type**: `object`
- **Non-null**: 1,012 / 1,059 (95.6%)
- **Description**: Source URL at millercenter.org.

### `source_file`
- **Type**: `object`
- **Non-null**: 1,059 / 1,059 (100.0%)
- **Description**: Original JSON filename in the Miller Center archive.

### `word_count`
- **Type**: `int64`
- **Non-null**: 1,059 / 1,059 (100.0%)
- **Description**: Total word tokens (transparent lowercase tokenizer, HTML entities decoded).

### `self_count`
- **Type**: `int64`
- **Non-null**: 1,059 / 1,059 (100.0%)
- **Description**: Count of self pronouns: I, me, my, mine, myself (+ contractions I'm/I've/I'll/I'd).

### `collective_count`
- **Type**: `int64`
- **Non-null**: 1,059 / 1,059 (100.0%)
- **Description**: Count of collective pronouns: we, us, our, ours, ourselves (+ we're/we've/we'll/we'd/let's).

### `self_per_1k`
- **Type**: `Float64`
- **Non-null**: 1,059 / 1,059 (100.0%)
- **Description**: self_count per 1,000 words.

### `collective_per_1k`
- **Type**: `Float64`
- **Non-null**: 1,059 / 1,059 (100.0%)
- **Description**: collective_count per 1,000 words.

### `self_share`
- **Type**: `Float64`
- **Non-null**: 1,056 / 1,059 (99.7%)
- **Description**: self_count / (self_count + collective_count). 0.5 = balanced; null if neither present.

### `speech_type`
- **Type**: `object`
- **Non-null**: 1,059 / 1,059 (100.0%)
- **Description**: Institutional type from the title (Inaugural Address, State of the Union, Annual Message, etc.).

### `is_sotu_series`
- **Type**: `bool`
- **Non-null**: 1,059 / 1,059 (100.0%)
- **Description**: True if State of the Union OR (pre-1929) Annual Message — the unified SOTU series.

### `delivery_mode`
- **Type**: `object`
- **Non-null**: 1,059 / 1,059 (100.0%)
- **Description**: written_era (1801-1912 clerk-read messages) vs spoken_era — a comparability break.

## Notes

Source: Miller Center (UVA) presidential speech archive, public domain. CURATED corpus of major speeches (not exhaustive); coverage denser for modern presidents. Measures the speech AS DELIVERED (many were ghostwritten). Pronoun/word metrics from a transparent tokenizer (see src/prepare.py).
