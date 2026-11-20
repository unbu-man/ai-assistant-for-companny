# Six-Company Bilingual Customer AI

A local bilingual support MVP serves **MAQSU, CLOSO, GIANTFOCUS, FALCORA, ClickHR, and GIANTBROTHER** through one FastAPI app and one PostgreSQL database. The same repository contains the Phase 1 data audit. Read [AGENTS.md](AGENTS.md) and [COMPANY_AI_CODEX_BRIEF.md](COMPANY_AI_CODEX_BRIEF.md) before changing business policy.

**Both business CSVs have been audited locally.** The run preserved **15,279 rows**, produced **830 candidate answer groups** and **30,450 question variants**, and quarantined **54 `BOTH` rows** without assigning them to either company. There are **zero approved business answers**. The MVP demo uses a separate database with clearly labeled synthetic content.

The private audit bundle is in `data/processed/source-run-001/`. Open `report.md` for the summary, `report.json` for every column profile, and `companies/` for six separate company reports. See [docs/PROGRESS.md](docs/PROGRESS.md) for the observed distribution, verification and reviewer handoff. Counts are data observations, not verified business facts.

## Run the local MVP

Install Python 3.11+, PostgreSQL 15+ with pgvector, and libpq. On this Mac, PostgreSQL 17 and pgvector are installed. Use the same PostgreSQL installation for `pg_config`, the database server, and the extension.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[mvp]'
./scripts/run-local.sh demo
```

Open `http://127.0.0.1:8765` and choose a company. Try **What is the sample label?**, **តើ demo label ជាអ្វី?**, and **How much does ERP cost?**. Ask an unrelated question to see **Browse verified questions** open with a selectable synthetic FAQ. Use synthetic details for the quote flow. To test a versioned answer, ask **How do I select the sample label?**, then enter product `demo` and version `1` and submit the same question.

The script starts an isolated PostgreSQL cluster under ignored `data/processed/mvp-dev/`. The database listens on a private Unix socket. The web server listens on loopback. Stop the web server with Ctrl-C. To stop the database after closing all local previews, run `pg_ctl -D data/processed/mvp-dev/postgres -m fast -w stop`. The local demo is for development.

For the separate MAQSU pilot database, use a second terminal.

```bash
COMPANY_AI_HTTP_PORT=8766 ./scripts/run-local.sh pilot
```

Open `http://127.0.0.1:8766`. The pilot starts with an empty approved index. It can ask qualifying questions and collect a consented request. It uses an honest fallback for unsupported product questions.

## Review, import, and operate the pilot

1. Open `data/processed/maqsu-pilot-review-001/review-with-evidence.csv` locally. Filter for `FIRST_BATCH` to see ten proposed bilingual answers with public MAQSU references. A MAQSU reviewer checks the English and Khmer wording against the linked source, edits it if necessary, confirms `verified_source_and_section`, fills `reviewer` and ISO `reviewed_date`, then changes only the verified rows to `APPROVED`. The optional `public_question_en` and `public_question_km` fields are the customer-facing FAQ labels and must also be reviewed. Keep both blank to omit an approved answer from the picker. Keep the original `review.csv` as the audit shortlist. The rows marked `CONFIRM_ACTIVE_SLA` need the applicable support agreement confirmed.
2. Import the explicit decisions. Pending rows are skipped, wrong-company and rejected source candidates are rejected by the importer, and pricing-like content is blocked. Approved FAQ answers use their original question variants to improve matching.

```bash
export PGHOST="$PWD/data/processed/mvp-dev/socket"
export PGPORT=55437
export COMPANY_AI_ADMIN_DATABASE_URL='dbname=company_ai_pilot'
.venv/bin/company-ai-mvp import-reviews data/processed/source-run-001 data/processed/maqsu-pilot-review-001/review-with-evidence.csv
.venv/bin/company-ai-mvp summary MAQSU
```

Use the manual importer for reviewed versioned procedures. Each UTF-8 JSONL record has `decision` set to `APPROVED` and these fields: `company`, `identifier`, `kind` (`procedure`), `product`, `version`, `en`, `km`, `citation`, `reviewer`, `reviewed_on` (ISO date), and a `questions` array. Run `.venv/bin/company-ai-mvp import-manuals data/raw/reviewed-procedures.jsonl`. A writer or reviewer must extract the approved steps from the company’s manual; the MVP imports reviewed entries and requires a product/version match before returning steps.

Other operator commands are `revoke COMPANY CANDIDATE_ID`, `summary COMPANY`, `export-leads COMPANY data/processed/new-export.csv`, `delete-lead COMPANY REFERENCE`, and `cleanup COMPANY --gap-days 30`. Revocation removes the answer from future retrieval. Reuse requires a newer review. Lead export stays local and company scoped. The displayed receipt means the database saved the request. Sales delivery requires an authorized company operator or a future integration.

## Retrieval, testing, and rollout

The chat returns approved wording and a citation using Unicode character matching across question variants. It asks for more information when matches are missing or ambiguous. The FAQ picker gives visitors another path to the current company's reviewed answers. It opens after a general fallback when reviewed labels are available. Items are rechecked at click time and excluded during the quote workflow. FAQ and versioned procedure retrieval both filter by company and approval in SQL. A dedicated runtime role uses PostgreSQL row-level security and cannot publish knowledge or read leads. Chat tokens expire after 24 hours. General chat text stays out of the database by default. The quote workflow runs before retrieval and asks for business scope, then explicit consent, then contact details. Knowledge gaps retain only category and language by default.

Enable semantic search by setting `COMPANY_AI_EMBEDDINGS_URL` to a compatible embeddings API base, `COMPANY_AI_EMBEDDINGS_MODEL` to its multilingual model, and `COMPANY_AI_EMBEDDINGS_KEY` if required. For example, an authorized local inference service can expose BGE-M3 through the compatible API. Re-run review import with the same settings to populate vector columns. With embeddings configured, use only a provider approved to process the approved question variants and user query text. The app masks common contact patterns in model queries. If the service fails, chat can still search lexically.

The operator can run `.venv/bin/company-ai-mvp evaluate data/raw/pilot-evaluation.jsonl` with `COMPANY_AI_DATABASE_URL` set to the restricted runtime connection. Each case has `company`, `language` (`en`, `km`, or `mixed`), `question`, and `expected_id` (the approved answer ID, or an empty string if unsupported). Add `kind`, `product`, and `version` for procedure cases. It reports Recall@3, top result accuracy, no-result rate, and median retrieval latency per language. With a configured provider it compares lexical and hybrid retrieval on the same cases. Use independent support questions and record the published knowledge version. The 16 draft pilot scenarios also cover policy and conversation behavior that retrieval metrics alone cannot measure.

Use `scripts/check-pilot-drafts.py` to measure candidate ranking privately before approvals. It reads source variants and draft prompts without accessing the database or publishing knowledge. To reproduce the optional E5 comparison, start `scripts/serve-local-e5.py --device mps` using a Python environment with Sentence Transformers and cached `intfloat/multilingual-e5-base` weights. Use `--device cpu` on other machines. The server binds to loopback and uses the model's symmetric question matching format. [Multilingual E5 model card](https://huggingface.co/intfloat/multilingual-e5-base)

```bash
.venv/bin/python scripts/check-pilot-drafts.py \
  data/processed/source-run-001 \
  data/processed/maqsu-pilot-review-001/review-with-evidence.csv \
  data/processed/maqsu-pilot-review-001/pilot_checks.csv \
  --local-embeddings http://127.0.0.1:11435/v1 --model multilingual-e5-base
```

Omit the last two options to run only the lexical comparison. Draft checks are a diagnostic. Use fresh bilingual questions, including unsupported questions, to establish safe matching behavior before rollout.

Run the unit and database integration tests against a separate verification database.

```bash
export PGHOST="$PWD/data/processed/mvp-dev/socket"
export PGPORT=55437
createdb company_ai_verification
COMPANY_AI_ADMIN_DATABASE_URL='dbname=company_ai_verification' .venv/bin/company-ai-mvp migrate
COMPANY_AI_ADMIN_DATABASE_URL='dbname=company_ai_verification' .venv/bin/company-ai-mvp grant-runtime company_ai_local
COMPANY_AI_TEST_ADMIN_URL='dbname=company_ai_verification' \
COMPANY_AI_TEST_RUNTIME_URL='dbname=company_ai_verification user=company_ai_local' \
  .venv/bin/python -m unittest discover -s tests -v
```

If the verification database already exists, skip `createdb`. The optional Docker Compose demo uses the same app and a separate synthetic database. Set distinct `COMPANY_AI_DB_ADMIN_PASSWORD` and `COMPANY_AI_DB_APP_PASSWORD` in a private `.env` and run `docker compose up --build` with Docker running. It exposes loopback port 8765. For public rollout, confirm reviewed coverage, test with real Khmer queries, add a public ingress with TLS and rate limiting, and designate sales operators and a lead retention period.

## Setup and tests

Python **3.11 or newer** is required. Phase 1 has no runtime dependencies outside the Python standard library. The commands below run directly from the checkout without downloading packages:

```bash
python3 -m venv .venv
source .venv/bin/activate
export PYTHONPATH="$PWD/src"
python -m unittest discover -s tests -v
python -m company_ai --help
```

Optional: `python -m pip install -e .` installs the `company-ai` console command. This requires pip and the setuptools build dependency; it is not necessary for the commands documented here.

## Run the synthetic demonstration

```bash
export PYTHONPATH="$PWD/src"
python3 -m company_ai inspect \
  tests/fixtures/main_synthetic.csv \
  tests/fixtures/partners_synthetic.csv

python3 -m company_ai prepare \
  tests/fixtures/main_synthetic.csv \
  tests/fixtures/partners_synthetic.csv \
  --synthetic \
  --output data/processed/synthetic-run-001
```

Every demo report is labeled `SYNTHETIC_FIXTURE`. Expected results: **13 preserved rows, 8 candidate canonical answer groups, 19 question variant records, 3 quarantined rows, and 0 approved groups**. All six companies receive JSON and Markdown reports. The fixture deliberately includes duplicate rows, conflicting answer text, an untrusted `APPROVED` status, a mixed-script question, `BOTH`, an unknown company, and a missing answer.

Choose a new output directory on each run, such as `synthetic-run-002`. Existing output directories are refused; originals and previous artifacts are not overwritten.

## Inspect or rerun the real datasets

The supplied files are in the **ignored** local directory. For a fresh checkout, copy the private inputs to the same locations:

```text
data/raw/data_ready1_styled.csv
data/raw/partner_brands_dataset_5000.csv
```

Then inspect their actual schema before preparing them:

```bash
export PYTHONPATH="$PWD/src"
python3 -m company_ai inspect \
  data/raw/data_ready1_styled.csv \
  data/raw/partner_brands_dataset_5000.csv
```

The inspection command profiles **every column**, reporting nonempty/missing counts, distinct nonempty normalized values, maximum length, normalization changes, and script coverage. It never prints cell contents. Actual headers and representative redacted records were inspected before the first source run; the default mapping matches both supplied files. For replacement datasets, inspect representative records privately before confirming mapping and review policy; do not paste private records into shared logs or issues.

Default logical column names follow the brief:

```text
id company category subcategory
question_en question_km answer_en answer_km
keywords_en keywords_km source_document intent_id
source_section confidence status product version
```

Only `company`, at least one question column, and at least one answer column are required. Other columns are optional. Extra columns remain in raw records and column profiles. Missing product/version metadata remains empty; it is not guessed from company names or answer text.

If observed headers differ, create a private mapping file, for example `data/raw/column-mapping.json`:

```json
{
  "company": "tenant",
  "question_en": "query",
  "answer_en": "response"
}
```

Mapping keys are logical fields and values are exact observed CSV column names. Omitted keys keep their defaults. Add `--mapping data/raw/column-mapping.json` to `prepare` when necessary. A single mapping applies to the supplied inputs; prepare files separately when their header mappings differ. Header names are not guessed or silently renamed.

```bash
python3 -m company_ai prepare \
  data/raw/data_ready1_styled.csv \
  data/raw/partner_brands_dataset_5000.csv \
  --output data/processed/source-run-002
```

`source-run-001` already contains the first audit. Use a new run directory for every subsequent import.

Business-file runs are labeled `SOURCE_DATA_UNVERIFIED`. A successful import means the data was preserved and audited, **not** that the answers are approved, correct, current, or safe for customer responses.

## What the pipeline does

1. Reads strict UTF-8 CSV, accepting a UTF-8 BOM. Copies source bytes unchanged and records SHA-256 hashes. Other encodings and unparseable CSV fail with an explicit error and no published bundle. Convert or repair a copy explicitly; retain the original.
2. Preserves **every parsed row**, including blank records, duplicates, missing cells, and extra cells. Records physical line ranges, data-record numbers, source IDs and original IDs. Duplicate/blank headers fail because a reliable mapping is impossible.
3. Creates normalized fields using Unicode NFC and whitespace collapse. Case, punctuation, Khmer characters and source terms are retained. Originals remain available through raw row IDs and snapshots.
4. Resolves companies only from the company field using an explicit six-company allowlist, ignoring letter case and surrounding whitespace. Ambiguous labels and `BOTH` remain unassigned and quarantined. No shared row is copied into MAQSU or CLOSO. Recognized companies on malformed rows remain counted under that company, with the row quarantined.
5. Groups **exact normalized bilingual answer pairs** within company, product, version, category, subcategory and intent. Both question language columns become separate variants tied to their original row. Every duplicate and paraphrase is retained. Different answer text or missing translations stay separate; the pipeline does not infer semantic equivalence or a unique verified fact count.
6. Records source statuses and confidence as untrusted metadata. All candidate groups remain `NEEDS_REVIEW`, or `REJECTED` if any contributing source row is rejected. Even a source declaration of `APPROVED` or high confidence never grants approval. All rows enter the review queue. There is deliberately no approval flag or automated production export.
7. Flags differing answer pairs for repeated questions or intents within a company/product/version. These are **possible** inconsistencies: different wording, missing translations or legitimate intent subtopics may also trigger them. Both answers and their provenance remain intact.
8. Assigns connected answer/topic groups to deterministic train/dev/test splits with nominal 80/10/10 hash buckets. Exact answer pairs across companies share a split without merging company data. Same-company topic, intent, and repeated-question connections stay together. Small datasets may have empty splits; adding data can change connected groups. Freeze a reviewed dataset version before evaluation. Independent held-out questions are still required.

Rows with unresolved company, column-count errors, no question, no answer, or unexpected control characters are quarantined and excluded from canonical groups. Missing translations, missing source-document references, and script mismatches are review issues. Absence of these flags does not prove factual correctness, freshness, or safe content.

Language labels are `km_script`, `latin_script`, `mixed_km_latin`, `unknown`, or `empty`. They measure writing systems, not language quality. Romanized Khmer is usually tagged Latin; a human must verify translations and code-switching. **ភាសាខ្មែរ និងអង់គ្លេសត្រូវរក្សាទុកដាច់ដោយឡែក ហើយមិនបកប្រែដោយស្វ័យប្រវត្តិទេ។**

## Output bundle

| Artifact | Purpose |
| --- | --- |
| `manifest.json` | Hashes, byte sizes, mapping, normalization policy, headers, column profiles and snapshot paths |
| `sources/*.csv` | Byte-for-byte private source snapshots |
| `raw_records.jsonl` | Original cell arrays, source IDs and physical line ranges; join headers through the manifest |
| `normalized_rows.jsonl` | All normalized rows, language tags, tenant assignments, declared/effective statuses and issues |
| `canonical_answers.jsonl` | Unapproved candidate groups with all contributing row/document/section provenance |
| `question_variants.jsonl` | Every nonempty mapped question, source row, company and candidate answer reference |
| `consistency_conflicts.jsonl` | Possible conflicts with row references, without selecting a winner |
| `review_queue.jsonl` | Every row requiring verification or resolution |
| `report.json`, `report.md` | Aggregate quality audit and limitations |
| `companies/{company}.json`, `.md` | Separate reports for all six companies, including zero-count companies |

There are no timestamps in content artifacts except the manifest creation time, so identical input bytes/order and mapping reproduce those artifacts exactly. Input order contributes to source/row IDs; candidate answer IDs depend on tenant, scope, and normalized answer content. Changed inputs produce new provenance rather than claiming continuity of approval.

Bundles use owner-only directory/file permissions and are built in a private temporary directory before publishing the completed output directory. Keep the local workspace and backups access-controlled; files are not encrypted. These are offline preparation artifacts, **not a multi-tenant service**. Future database queries and lead persistence still need server-enforced tenant isolation.

## Layout and scope

```text
src/company_ai/
  cli.py                    # inspect/prepare entry points
  data/
    ingestion.py            # CSV parsing, column profiles, provenance
    normalization.py        # Unicode and script tagging
    preparation.py          # company resolution, candidate groups, conflicts, splits
    reporting.py            # global and six-company quality reports
    pipeline.py             # private artifact publishing
tests/fixtures/             # explicitly synthetic, safe-to-share CSVs
tests/test_preparation.py   # standard-library automated tests
data/raw/                   # private business inputs, ignored
data/processed/             # private output bundles, ignored
docs/PROGRESS.md            # dated decisions, verification, gaps and next step
```

Phase 1 uses portable local artifacts so the audit can run before a database or model is installed. The MVP entry point is `src/company_ai/mvp/app.py`. The migration and operator commands live in the same package. Only a separately reviewed subset reaches the runtime knowledge schema.

## Data and Git safety

`.gitignore` excludes raw and processed data, CSVs other than the synthetic fixtures, JSONL exports, credentials, `.env` files, logs/crash dumps, local environments, model files and caches. Each output bundle also contains its own ignore rule. Ignore rules do not protect files already tracked by Git or artifacts copied elsewhere. Review `git status --short` and `git diff --cached` before any future commit. No business data, API keys, real customer contacts or conversations belong in Git.

## Current verification and next step

See [docs/PROGRESS.md](docs/PROGRESS.md) for executed commands and observed synthetic and actual-input results. **23 automated tests pass.** Independent checks of the actual bundle verified all source bytes/hashes and parsed cells, every company/provenance link, all question variants, review-queue completeness, `BOTH` quarantine, zero approvals and split grouping. Automated tests cover byte/row preservation, all six company reports, tenant boundaries, review statuses, conflicts, duplicates, Khmer/English/mixed scripts, normalization, source-text injection, version separation, reproducibility, split grouping, malformed files and explicit mappings.

Company reviewers must verify source authority, factual accuracy and translations, decide the ownership of the 54 `BOTH` rows, and supply product/version metadata where required. Script presence does not establish translation quality. The text consistency checks do not establish source freshness or semantic consistency.

The local MAQSU pilot review pack in `data/processed/maqsu-pilot-review-001/` narrows the first review to 24 pending bilingual answers. Open `review.csv` for the source references and reviewer fields, and `pilot_checks.csv` for 16 draft checks. Both files are private and ignored by Git. The shortlist and rollout criteria are described in [docs/PROGRESS.md](docs/PROGRESS.md).
