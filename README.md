# arx — offline annual-report extraction for Indian banks & NBFCs

Reads Indian bank / NBFC annual report PDFs (200–400 pages, some scanned, some
bilingual) and writes the extracted metrics into **your existing Excel template**,
with a confidence and audit layer built on one principle:

> **A wrong number is worse than a missing number.**
> Never guess. Never fill an uncertain cell. Doubt resolves *downwards*, into `ND`.

Fully offline. No LLM API, no network calls at runtime.

---

## 1. Architecture

A PDF is parsed once (pdfplumber, cached by content hash), then **ranked** so we
only ever look at the ~25 pages that matter — Financial Statements first,
Chairman's letter last. Camelot and OCR run *lazily*, only on pages that survive
ranking. Every alias hit anywhere in those pages becomes a **candidate**; nothing
is chosen at extraction time, because choosing early is exactly how last year's
column ends up in this year's cell. Candidates are then grouped by value, given
**independent** corroboration (repeats inside one table count once), and put on
**trial**: a defence argues from provenance, four prosecutors argue from doubt
(conflicting values, year mismatch, unit mismatch, table misalignment), and a
judge scores `defence − Σ penalties`. Survivors face the **Financial DNA** layer
(industry ranges → banking logic → the institution's own history → its peers),
**reverse validation** (is this number *also* some other metric's printed value?
that's a column shift), the **arithmetic identities** (`NII = Interest Earned −
Interest Expended`, `CRAR = Tier 1 + Tier 2`, …), and a **trend** check. The six
resulting components combine into a confidence 0–100, which decides whether the
number is written or replaced by `ND` — and either way, *why* is recorded in the
Audit Trail.

```
input_pdfs/*.pdf
      │
      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 1  parse.py     pdfplumber → text + tables      [cached by sha256] │
│ Stage 2  parse.py     institution (aliases/CIN) + fiscal year            │
│                       "year ended 31 Mar 2023"  ──►  sheet FY22-23       │
└─────────────────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 3  rank.py      score every page, walk in priority order           │
│   Financial Statements > Highlights > 10-Yr > Key Ratios > MD&A > prose  │
│         └─► lazy OCR (only ranked + scanned pages)   [cached per page]   │
│         └─► lazy camelot lattice+stream (only ranked pages)              │
└─────────────────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 4-5  extract.py   EVERY hit becomes a candidate — pick nothing yet │
│            + evidence, deduplicated by (section, table_id)   ◄─ Stage 7  │
└─────────────────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 6-8  courtroom.py                                                  │
│   DEFENCE      in FS? in Highlights? in Notes? multi-section? multi-alias│
│   PROSECUTORS  ① conflicting values  ② YEAR MISMATCH (can sink alone)    │
│                ③ unit mismatch (crore/lakh/mn/USD)  ④ table misalignment │
│   JUDGE        court_score = defence − Σ penalties                       │
└─────────────────────────────────────────────────────────────────────────┘
      │
      ▼  (pass 1 → provisional values → pass 2, because these checks are cross-metric)
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 9   dna.py       L1 ranges · L2 banking logic · L3 history · L4 peers │
│ Stage 10  dna.py       REVERSE validation: value → metric (finds shifts) │
│ Stage 11  formulas.py  identities + safe derivation (capped at 90)       │
│ Stage 12  formulas.py  numerical sanity (decimals, brackets, footnotes)  │
│ Stage 13  formulas.py  trend: 30% normal · 500% investigate, never delete│
│ Stage 14  confidence.py  evidence by tier (A needs many, C may appear 1×)│
│ Stage 15  confidence.py  → confidence 0-100 → decision band              │
└─────────────────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 16  excel_writer.py   copy of the template (openpyxl, never rebuilt)│
│   ≥95 Auto · 80-94 High · 65-79 Manual(+cell comment) · <65 → ND         │
│   sheets: FY21-22 · FY22-23 · FY23-24 · Source References ·              │
│           Missing Cells Report · Audit Trail · Confidence Summary        │
│   + audit/<institution>_<FY>.json  (the full candidate pool, per PDF)    │
└─────────────────────────────────────────────────────────────────────────┘
```

`run.py` (CLI) and `app.py` (Streamlit) are both thin wrappers over
`pipeline.run_batch`. Zero duplicated logic.

---

## 2. Install

**Python 3.11.**

### System dependencies

Camelot shells out to Ghostscript; OCR needs Tesseract and Poppler.

**macOS**

```bash
brew install tesseract poppler ghostscript
```

**Windows**

```powershell
# Tesseract  → https://github.com/UB-Mannheim/tesseract/wiki  (install, then add to PATH)
# Poppler    → https://github.com/oschwartz10612/poppler-windows/releases  (unzip, add \bin to PATH)
# Ghostscript→ https://ghostscript.com/releases/gsdnld.html  (install the 64-bit build)
choco install tesseract poppler ghostscript   # or, if you use Chocolatey
```

**Ubuntu/Debian**

```bash
sudo apt-get install -y tesseract-ocr poppler-utils ghostscript
```

### Python packages

```bash
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Sanity check:

```bash
tesseract --version && pdftoppm -v && gs --version
```

---

## 3. Run

```bash
# CLI — the main path
python -m arx.run --pdfs ./input_pdfs \
                  --template ./FinancialData_Verified_1.xlsx \
                  --out ./FinancialData_Filled.xlsx

# ...with 4 PDFs in parallel and debug logging
python -m arx.run --pdfs ./input_pdfs --template ./FinancialData_Verified_1.xlsx \
                  --out ./FinancialData_Filled.xlsx --workers 4 --verbose

# force a full re-parse (ignore the .cache)
python -m arx.run --pdfs ./input_pdfs --template ./FinancialData_Verified_1.xlsx \
                  --out ./FinancialData_Filled.xlsx --no-cache

# don't have the template? generate a blank one with the exact layout
python -m arx.run --init-template --template ./FinancialData_Verified_1.xlsx \
                  --pdfs ./input_pdfs --out ./out.xlsx

# Streamlit — drag & drop, same library underneath
streamlit run app.py

# Tests
pytest                      # all of them
pytest tests/test_courtroom.py -v
pytest -k golden -v         # just the end-to-end golden test
```

Outputs: `FinancialData_Filled.xlsx`, plus `audit/<institution>_<FY>.json` (the
complete candidate pool — open this when you want to know why one specific cell
came out the way it did) and `.cache/<sha256>/` (parse + OCR cache).

**The golden test.** `tests/test_end_to_end.py` runs a synthetic ICICI FY22-23
report through the whole chain on every `pytest` run. Drop the real annual report
at `tests/fixtures/icici_fy2223.pdf` and the same assertions run against the real
PDF too. Ground truth is your template's ICICI row: Total Assets 1584207,
Deposits 1180841, Gross Advances 1019638, Interest Earned 109231.34, Interest
Expended 47102.74, NII 62129.

---

## 4. How to tune

Everything below is YAML. You should not need to touch Python.

### A metric is being **missed** (comes out `ND`, but the number is in the PDF)

Look up the cell in the **Audit Trail** sheet first — it tells you which of these it is.

| Symptom in the Audit Trail | Fix | Where |
|---|---|---|
| `Candidate count = 0` | The report calls it something you haven't listed. Add the report's exact wording to `aliases`. | `metrics.yaml` |
| Found, but `Reason` says *"Found only in narrative text"* | The number genuinely only appears in prose. Lower `section_weights.narrative`'s cost by raising `defence.in_narrative`, or move the metric to Tier C. | `config.yaml`, `metrics.yaml` |
| Found, but *"Insufficient corroboration … for a Tier-A metric"* | You are demanding multi-source evidence for something the report prints once. Move it to Tier **B** or **C**. | `metrics.yaml: tier` |
| Confidence is 60-64 — just under the wire | Lower `decision_bands.manual_review` (65). Everything 65–79 is still written *and* flagged, so this is a safe knob. | `config.yaml` |
| *"outside the sane range"* but the value is right | Your `sane_range` is too tight for this institution type. | `metrics.yaml: sane_range` |
| The whole PDF yields nothing | It's scanned and OCR isn't running. Raise `ocr.max_pages`, check `tesseract --version`. | `config.yaml`, system deps |

### A **wrong value** is slipping through (worse — fix this first)

| Symptom | Fix | Where |
|---|---|---|
| Last year's number in this year's cell | Raise `prosecutors.year_mismatch.penalty` (60) and `.unlabelled_column_penalty` (25). This is the single most valuable knob in the file. | `config.yaml` |
| Value is 100×/1000× out | Raise `prosecutors.unit_mismatch.penalty` (35) and `.implied_scale_penalty` (15). | `config.yaml` |
| Number from the neighbouring row/column | Raise `prosecutors.table_alignment.penalty` (30) and `.fuzzy_row_label_threshold` (88 → 92). | `config.yaml` |
| An alias is matching the wrong row (e.g. `Interest Earned` catching *Interest Earned on Investments*) | Tighten the regex — anchor it: `^Interest\s+Earned$`. | `metrics.yaml` |
| Wrong numbers generally, everywhere | Raise `decision_bands.manual_review` (65 → 75). Fewer cells filled, more `ND`. **This is the master safety dial.** | `config.yaml` |
| A physically impossible value got written | Add a rule to `banking_rules`, or tighten `sane_range`. Then raise `dna.level2_rule_violation` (0.30). | `metrics.yaml`, `config.yaml` |
| Derived values are wrong | Raise `formulas.derive_min_input_confidence` (80 → 90), or set `derived_confidence_cap` below 65 to stop derivation being written at all. | `config.yaml` |

**Rule of thumb:** to fill *more* cells, edit `metrics.yaml` (aliases, tiers,
ranges). To fill *fewer but safer* cells, edit `config.yaml` (penalties, bands).
Never chase a missing number by lowering a prosecutor penalty — that trades one
missing value for an unknown number of wrong ones.

Adding a new institution is just a block in `institutions.yaml` (canonical name,
category, type, aliases, CIN). `type` drives `applicable_to`, which is what makes
Deposits come out `NA` (not `ND`) for NABARD/REC/PFC and AUM come out `NA` for a
bank.

---

## 5. Known limitations, and what would need an LLM / vision model

**Structural, fixable within this design**

- **Column count.** The template's column bands (4–55) define **52** metrics, not
  55: Headline 8 + P&L 12 + Asset Quality 10 + Capital 10 + Strategic/ESG 11 +
  Technology 1. The code is driven entirely by `metrics.yaml`, so if you meant 55
  distinct metrics, add the missing three rows there and the columns, writer,
  audit and tests all follow. Nothing is hard-coded.
- **Template values are treated as confidence 0** (`excel.assumed_existing_confidence`)
  — a freshly extracted, above-threshold value replaces a hand-keyed one. If your
  template rows are authoritative, raise this to 100 and they become read-only.
- Institutions outside `institutions.yaml` are guessed from the cover page and
  flagged with low confidence rather than skipped.

**Genuinely hard offline**

- **Foreign-currency tables** (EXIM, Tata group USD schedules) are detected and
  effectively rejected. Converting them needs an FX rate, which needs a network
  call. Deliberately not done.
- **Multi-line and merged table headers** (`Year ended` / `March 31, 2023` split
  across two header rows, or a merged cell spanning two year columns) are the main
  residual source of year-mismatch risk. The year prosecutor catches most of it by
  refusing to trust an unlabelled column — the failure mode is `ND`, not a wrong
  number, which is the right way to fail.
- **Scanned + bilingual pages.** OCR is English-only by design (mixing Devanagari
  wrecks digit recognition), so a Hindi-only figure is invisible. Rare in practice:
  the English column is a mirror.
- **ESG / BRSR narrative metrics** (board diversity, tech spend, mobile app users)
  live in prose and infographics. They are Tier C so a single mention is accepted,
  but recall here is the weakest part of the system — expect `ND`.
- **Numbers that only exist in a chart** (a bar labelled "18.34%") are not
  extracted at all. pdfplumber sees a rectangle.

**Where an LLM or vision model would actually earn its place**

1. **Table structure understanding** — a layout model (LayoutLMv3 / Table
   Transformer / Donut) resolving merged and multi-line headers would remove the
   biggest remaining year-mismatch risk, and is worth more than everything else on
   this list combined.
2. **Chart and infographic reading** — a vision model for the "at a glance" spreads
   where numbers are graphics, not text.
3. **Narrative extraction with reasoning** — "our technology spend was ~8% of
   operating expenses" requires reading a sentence and knowing what it implies.
   That is what would move the ESG/Technology block from `ND` to filled.
4. **Alias discovery** — an LLM proposing new aliases from the reports it fails on,
   for a human to approve into `metrics.yaml`. The dictionary stays hand-owned; the
   LLM only suggests.

In every case the LLM should feed **candidates into the courtroom**, never write a
cell directly. The confidence layer is the product; the extractor is replaceable.

---

## 6. Layout

```
arx/
  __init__.py       YAML loading, seeding, logging
  run.py            CLI
  pipeline.py       the orchestrator — the only place the stage order lives
  config.yaml       weights, penalties, thresholds, tolerances
  metrics.yaml      52 metrics + banking rules
  institutions.yaml aliases, category, type
  models.py         pydantic: Candidate, Evidence, Verdict, CellResult, …
  parse.py          Stage 1-2   parsing, lazy OCR, caching, identification
  rank.py           Stage 3     page ranking
  extract.py        Stage 4-5,7 candidates + independent evidence
  normalize.py      Stage 12    numbers, units, scales, Indian formats
  courtroom.py      Stage 6-8   defence, 4 prosecutors, judge
  dna.py            Stage 9-10  4 DNA levels + reverse validation
  formulas.py       Stage 11-13 identities, derivation, sanity, trend
  confidence.py     Stage 14-15 tiers, scoring, decision bands
  excel_writer.py   Stage 16    template-preserving writer + audit sheets
app.py              Streamlit wrapper (no logic of its own)
tests/              128 tests, incl. the end-to-end golden test
```
