# Data Sources — presidential-speeches

Source standards are **tiered**:
- **Serious tier** (methodology invites scrutiny): use official government or
  authoritative primary sources only. Crowd-edited references (Wikipedia, etc.)
  are NOT used — credibility is the product.
- **Fun tier** (low-stakes pop-culture): crowd-sourced references (fan wikis,
  SuperSummary, etc.) and owner-as-primary (hand-collected counts from a book or
  broadcast) are fine — just cite them plainly below.

Document every data source here before ingesting it. Include enough detail
that someone else could independently locate and verify the original data.

---

## Source Template

Copy and fill in for each source. The **How the source collects the data**,
**How the source defines the data**, and **Methodology changes / series breaks**
sections are required — they are what keep our analysis honest and prevent
apples-to-oranges comparisons. Do not leave them blank; if something is genuinely
not applicable or unknown, write "N/A" or "unknown" so it's clear it was considered.

### [Source Name]
- **Publisher:** [Agency, organization, or author]
- **URL:** [Direct link to the file or page]
- **Format:** [CSV | JSON | HTML table | ZIP | PDF | hand-curated]
- **License:** [Public domain | CC0 | CC-BY | proprietary | etc.]
- **Fields used:** [Column names or description of what was extracted]
- **Coverage:** [Geographic scope, date range, or other relevant bounds]
- **How the source collects the data:** [How does the publisher actually gather it?
  Survey / administrative records / registration / model estimate / scraped, etc.
  For surveys: sampling frame, sample size, response rate. For counts: the universe
  and denominator. Who is included and who is excluded from the raw collection?]
- **How the source defines the data:** [How is the thing being measured *defined*?
  Spell out the judgment calls in what counts. Example: a "COVID death" can mean died
  *from* COVID (underlying cause) vs. died *with* COVID (contributing/any mention) —
  very different counts. Note the exact definition this source uses.]
- **Methodology changes / series breaks:** [Dates when the definition or collection
  method changed, and which time periods are therefore NOT directly comparable.
  If the whole series is consistent, say so explicitly. This is the flag that stops
  us from charting a pre-change number next to a post-change number as if they match.]
- **Known controversies / debates:** [Any contested measurement choices worth a
  footnote or caveat in a published chart. Optional but encouraged. "None known" is
  a valid answer once you've checked.]
- **Notes:** [Anything else — data-quality quirks, suppression rules, imputation, etc.]
- **Retrieved:** [YYYY-MM-DD]

---

## Sources

**Tier: serious.** Language analysis invites methodological scrutiny, so sources
are authoritative primary corpora (university-curated / government), never
crowd-edited references.

### Miller Center Presidential Speech Archive (PRIMARY — first ingest)
- **Publisher:** University of Virginia, Miller Center of Public Affairs
- **URL:** https://data.millercenter.org/miller_center_speeches.tgz (landing page:
  https://data.millercenter.org/)
- **Format:** gzipped tar archive → expands to `speeches/` containing one JSON file
  per speech (transcript + metadata: title, date of delivery, president).
- **License:** Public domain (the speeches themselves are U.S. government works).
  Miller Center requests a citation for the compiled archive.
- **Fields used:** speech transcript text; president; speech title; date of delivery.
  (Derived downstream: word counts, pronoun counts — self I/me/my/mine vs collective
  we/us/our/ours — readability, vocabulary richness.)
- **Coverage:** 1,000+ speeches, George Washington through the contemporary
  presidency. NOT exhaustive — see collection method below.
- **How the source collects the data:** Miller Center staff compiled and transcribed
  a curated set of major presidential speeches. Transcripts are prepared by the
  Center from public-domain presidential materials.
- **How the source defines the data:** A "speech" here is a discrete address the
  Center chose to include. **Inclusion is an explicit editorial decision** — the
  archive is a curated set of notable/major speeches, not every utterance. This is a
  selection bias to state plainly: it over-represents set-piece addresses (inaugurals,
  State of the Union, major nationally-televised remarks) and under-represents routine
  remarks, minor statements, and off-the-cuff press exchanges.
- **Methodology changes / series breaks:** No formal versioned series breaks in the
  file format. BUT the real comparability hazards for language analysis are: (1)
  **coverage density varies by era** — far more speeches survive/are included for
  modern presidents than for 19th-century ones, so per-president aggregates rest on
  very different sample sizes; (2) the **written-address era vs the broadcast era** —
  pre-radio messages to Congress were written documents, not delivered oratory, and
  read very differently from televised speeches (a genuine style break to flag on any
  1789→present trend). Treat "speeches per president" as a coverage artifact, not a
  behavioral finding.
- **Known controversies / debates:** The self-vs-collective ("I" vs "we") framing is
  a common pop-linguistics claim; the honest caveat is that raw pronoun rates depend
  heavily on **speech type** (a scripted SOTU vs off-the-cuff remarks) and on which
  speeches happen to be in the curated set — so per-president comparisons must control
  for, or at least disclose, the mix of speech types included. Ghostwriting also means
  these measure the *speech as delivered*, not necessarily the president's own diction.
- **Notes:** Bulk download replaced the deprecated API. Raw tgz + extracted JSON saved
  verbatim under `data/raw/`; never edited. For a fuller corpus later, The American
  Presidency Project (UCSB, ~130k documents categorized by type) is the intended
  expansion source — see config.yaml.
- **Retrieved:** 2026-09-25 (1,059 speeches, 45 presidents, 1789-04-30 → 2026-07-16)

---

## Notes on Data Quality

- All source files are saved verbatim to `data/raw/` and never modified.
- Discrepancies between sources should be noted here and resolved explicitly.
- **Series breaks:** whenever a source changed its definition or method mid-series,
  document the break date under that source and treat pre/post as separate series —
  never chart or aggregate across a break without a visible caveat.
- **Definitions drive comparisons:** before comparing two numbers (across years,
  places, or sources), confirm they are defined the same way. If not, say so in the
  chart, the codebook, and any social copy.

---

## Source Provenance in DuckDB

Every table in `data/project.duckdb` has a corresponding entry in the
`_sources` metadata table:

```sql
SELECT * FROM _sources;
```
