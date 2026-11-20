# Progress

## 2026-11-20 — Phase 1: data audit and preparation

### Starting state and scope

Read `AGENTS.md` and `COMPANY_AI_CODEX_BRIEF.md` completely before editing. No specification conflict was found. The repository contained those two tracked instruction files and an existing local JVM crash log. There was no README, source code, configuration, test suite, or CSV dataset. The crash log was left untouched and is now covered by ignore rules.

At the initial implementation stage, neither `data_ready1_styled.csv` nor `partner_brands_dataset_5000.csv` was present. The business-data audit was therefore pending then. Both files subsequently arrived and were audited as recorded in the later entry below.

### Implemented

- A standard-library Python package and CLI for strict CSV inspection, preservation, validation, normalization, conservative candidate-answer grouping, variant retention and quality reports.
- Exact source snapshots with SHA-256, all raw cells and extra columns, row IDs independent of potentially repeated original IDs, line provenance and per-column profiles.
- Explicit six-company resolution. Unknown/ambiguous and `BOTH` labels are quarantined without cross-company expansion. Missing or malformed records are retained and excluded from candidate groups.
- Source status/confidence retention without automatic approval; rejected source content stays rejected at group level. Every source row enters the local review queue.
- Possible answer inconsistency reports for repeated questions/intents, duplicate measurements, per-column script coverage and deterministic connected-group split assignments.
- Private global and separate JSON/Markdown reports for all six companies, including companies with no rows. Outputs have owner-only permissions and local ignore rules.
- README setup, demo and real-input commands; `.gitignore`; `pyproject.toml`; clearly synthetic bilingual fixtures and automated tests.

### Design decisions

Use local JSONL artifacts for Phase 1 so provenance and audit rules can be tested before introducing a database/model. This is not a substitute for PostgreSQL tenant filters in Phase 2. No API, retrieval, LLM, price-response system, lead capture, approval/publishing UI or deployment was added.

Group exact normalized answer pairs within tenant/product/version/topic/intent. Do not infer equivalence between translations or merge answer text semantically. Counts represent candidate groups, not verified facts. Preserve source content, including potentially disallowed customer-facing material, only in private artifacts; no source text is served to customers.

Treat `APPROVED` strings and high confidence as untrusted declarations. Human source verification and explicit shared-company approval remain necessary. There is no approval switch in this importer.

Use script tags instead of overstating language identification. Khmer, Latin and mixed-script presence are measured; translation quality, romanized Khmer and factual correctness require independent review. Connected topics, repeated questions and identical answer pairs share a split, while records and provenance retain separate company IDs.

### Verification

Executed on local Python 3.14.7; support is declared for Python 3.11+, but other interpreter versions have not been exercised in this environment.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Initial tests detected misplaced commas in three synthetic fixture rows. Corrected the fixture structure; the importer correctly quarantined those malformed rows rather than dropping cells or silently accepting them. Subsequent test run: **23 tests passed**.

Executed the documented `inspect` and `prepare --synthetic` CLI commands against both fixtures. Inspection found 12 columns / 7 rows in the main fixture and 15 columns / 6 rows in the partner fixture, with zero structural errors after correction. The generated bundle is in `data/processed/synthetic-run-001/`; every report is labeled `SYNTHETIC_FIXTURE` and ignored by Git.

| Synthetic-only observation | Result |
| --- | ---: |
| Preserved input rows | 13 |
| Mapped rows | 10 |
| Quarantined rows | 3 |
| Candidate canonical answer groups | 8 |
| Question variant records | 19 |
| Approved answer groups | 0 |
| Exact duplicate source rows | 1 |
| Normalized duplicate Q&A rows | 1 |
| Repeated question variants | 4 |
| Possible consistency-conflict records | 3 |
| Nonempty English question / answer columns | 13 / 12 |
| Nonempty Khmer question / answer columns | 9 / 9 |

| Company | Synthetic rows | Candidate groups | Quarantined |
| --- | ---: | ---: | ---: |
| MAQSU | 4 | 2 | 1 |
| CLOSO | 1 | 1 | 0 |
| GIANTFOCUS | 2 | 1 | 0 |
| FALCORA | 1 | 1 | 0 |
| ClickHR | 2 | 2 | 0 |
| GIANTBROTHER | 1 | 1 | 0 |
| Unassigned (`BOTH`, unknown) | 2 | 0 | 2 |

Inspected the generated global and ClickHR Markdown reports and confirmed that the synthetic declared `APPROVED` status still produces zero approved groups. These counts describe fixtures only and say nothing about the companies' actual product knowledge.

`python3 -m compileall -q src tests` and CLI help commands completed successfully. `git diff --check` reported no tracked-file whitespace problems. `git check-ignore` confirmed exclusion of both future raw CSV paths, generated reports, `.env`, the existing crash log, logs and model artifacts. Review of all untracked/nonignored files found only source, documentation, project configuration, synthetic fixtures/tests and empty data-directory markers; no private business CSVs or generated bundles are candidates for Git.

Created the documented `.venv` and repeated the suite with `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`: **23 tests passed without installing any runtime packages**. The optional editable package installation was not exercised.

### Limitations at the initial implementation stage

- Both private business CSVs are missing. Put them under `data/raw/` using the exact filenames documented in README, inspect actual columns and samples privately, confirm or customize mapping, then run preparation into a new `data/processed/` directory.
- No production answer is approved. `BOTH` ownership, conflicting text, missing translations, unknown companies, source freshness, product/version mapping and technical accuracy require company reviewers.
- Conflict detection is textual and may flag benign wording differences or missing translations. It does not detect every semantic contradiction. Script coverage is not language quality evaluation.
- Split assignments prepare a future benchmark; they are not evidence of accuracy. Independent held-out English, Khmer, mixed-language and adversarial questions are still needed. Adding data can change connected components and split assignments.
- Owner-only filesystem permissions and Git ignore rules are local controls, not encryption, authentication, database row security, or retention enforcement.
- No business-source audit, model benchmark, chatbot pricing/consent test, external integration or deployment result is claimed. No commit or publication was requested or performed.

### Next step

Complete the real-data Phase 1 audit and reviewer handoff. Record observed counts and issues only after processing the actual files. Remain in Phase 1 until these gaps are addressed; no Phase 2 work has been started.

## 2026-11-20 — Phase 1: actual business CSV audit

### Inputs and mapping

The user supplied both files under `data/raw/`. Re-read repository instructions, README, brief and existing code/tests before this work. Inspected actual headers and representative records from every company, including `BOTH`; contact values and numbers were redacted in sample output. Source text was treated only as untrusted data. The default column mapping matches the observed files; no source edits or code changes were needed.

| Input | Parsed rows | Columns | Structural errors | Declared status |
| --- | ---: | ---: | ---: | --- |
| `data_ready1_styled.csv` | 10,279 | 12 | 0 | No status column; all `UNSPECIFIED` |
| `partner_brands_dataset_5000.csv` | 5,000 | 15 | 0 | All `NEEDS_REVIEW` |

The main file contains the 12 columns described in the brief. The partner file has `source_section`, `confidence` and `status` in place of `intent_id`, for 15 columns total. All supplied columns are populated on every row. Neither file has product/version columns. Partner confidence is textual source metadata and is not interpreted as a calibrated probability or approval.

### Executed commands and outputs

```bash
PYTHONPATH=src .venv/bin/python -m company_ai prepare \
  data/raw/data_ready1_styled.csv \
  data/raw/partner_brands_dataset_5000.csv \
  --output data/processed/source-run-001

PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

The import succeeded and the **23 automated tests passed**. Output is labeled `SOURCE_DATA_UNVERIFIED`. The local bundle includes `report.md`, full column profiles in `report.json`, six company reports under `companies/`, all row/variant/review artifacts and byte-for-byte source snapshots. Raw data and generated bundles remain excluded from Git.

| Company | Source rows | Candidate answer groups | Quarantined | Approved groups |
| --- | ---: | ---: | ---: | ---: |
| MAQSU | 6,143 | 363 | 0 | 0 |
| CLOSO | 4,082 | 238 | 0 | 0 |
| GIANTFOCUS | 1,598 | 72 | 0 | 0 |
| FALCORA | 1,171 | 56 | 0 | 0 |
| ClickHR | 1,117 | 51 | 0 | 0 |
| GIANTBROTHER | 1,114 | 50 | 0 | 0 |
| Unassigned `BOTH` | 54 | 0 | 54 | 0 |
| **Total** | **15,279** | **830** | **54** | **0** |

All **15,279 original rows** were preserved. The **15,225 company-assigned rows** yielded **30,450 question variants**, retaining every question in both columns. Every source row appears in the review queue. All 830 candidate groups remain `NEEDS_REVIEW`; no source was approved or published. The 54 shared rows have no tenant assignment or candidate-answer reference and were not copied into MAQSU or CLOSO.

### Quality findings

- All four English/Khmer question/answer columns are nonempty on all 15,279 rows. This establishes presence only; it does not verify fluency, translation equivalence, or factual correctness.
- English question columns contain 13,730 Latin-script and 1,549 mixed Khmer/Latin records. Khmer question columns contain 115 Khmer-script and 15,164 mixed-script records. All English answers contain Latin script; Khmer answers contain 27 Khmer-script and 15,252 mixed-script records. Product terms can legitimately contribute Latin script to Khmer text.
- No exact full-source duplicate rows, normalized duplicate Q&A pairs, or repeated original IDs within a source were found. Two repeated question variants were found after case folding within company/product/version scope, both in MAQSU. Different question variants commonly share an answer: the 830 candidate groups are substantially fewer than the 15,225 assigned rows. These are not 830 verified facts.
- Current repeated-question/intent checks found zero possible answer-conflict records. An additional diagnostic found no same-company/product/version English answer mapping to multiple Khmer texts, or vice versa. These checks do not establish semantic consistency, translation accuracy or freshness. Partner rows lack `intent_id`, so intent-level checks cannot run on those rows.
- Nonempty normalized English answer lengths have medians of **100 characters** in the main file and **132 characters** in the partner file. Khmer answer medians are **111** and **126** characters respectively. These short answers do not establish detailed procedural coverage.
- Main-file answer normalization changed whitespace in 556 English and 556 Khmer cells. Original cells and source bytes remain unchanged. No other column-normalization changes were observed.
- All source-document fields are populated, with 99 distinct references in the main file and 49 in the partner file. A populated reference is not proof that the underlying source is current, available, authorized or reviewed.
- All 15,279 rows lack explicit product/version fields. Do not infer compatibility or version-specific procedures from company names or feature descriptions.
- The candidate split has **425 connected leakage groups** and **683 train / 68 dev / 79 test answer groups**. These are preparation assignments, not a retrieval benchmark or model evaluation. Independent held-out questions and reviewer-verified sources are still required.

### Independent bundle verification

Executed an assertion-based check against the original CSVs and generated artifacts. Confirmed:

- Both original files are byte-for-byte equal to their snapshots, and their SHA-256 values match the manifest.
- Every parsed cell array, including all original IDs and metadata, is preserved in source order; raw, normalized and review-queue row-ID sets match exactly across all 15,279 records.
- All 830 answer groups link only to rows of the same company; all 30,450 question variants link to the correct company, row, answer and split.
- Every assigned row contributes to exactly one candidate answer group; all 54 `BOTH` rows stay quarantined and unassigned; every row and group remains unapproved.
- All six company report counts reconcile with source rows. Identical answer pairs and connected topics/intents/questions never span splits.

No private raw Q&A, contact values or source-document contents were copied into committed-source candidates. No files were staged, committed or published. No Phase 2 implementation or customer-facing price/lead/chat capability is claimed.

### Next step and remaining review

The Phase 1 importer and actual-data audit are tested. Company reviewers must verify the 830 candidate groups against authorized sources, check Khmer/English wording, resolve the 54 shared rows explicitly, confirm source freshness and supply product/version metadata where needed. Keep all source material unapproved until that review is recorded. Do not treat the absence of text-conflict flags as evidence of verified knowledge. Phase 2 has not started.

## 2026-11-20 — Phase 1: MAQSU pilot review pack

The recommended pilot uses a private Dify Chatflow with a small, approved MAQSU knowledge base. Dify already supports keyword and semantic retrieval, citations and retrieval testing. The project can reuse an existing multilingual model and use search to find approved answers at runtime. Start by returning the approved wording in the customer's language and ask one focused question or offer support when there is no applicable answer. For the eventual rollout, the server must enforce company access and handle ERP quote requests and consent separately from answer generation. [Dify Knowledge Pipeline](https://www.dify.ai/rag)

The local review pack is in `data/processed/maqsu-pilot-review-001/`. It contains 24 MAQSU-only candidates selected for breadth across module overviews, product basics, industries, support, and ERP buying guidance. CSV paraphrase counts do not measure customer demand. Have MAQSU support check the topic priorities against recent common questions. For each candidate, compare both languages with the authoritative source, record the source and section, and record the reviewer and decision. All 24 decisions begin as `PENDING`. The review file contains private candidate text and is for local review.

`pilot_checks.csv` contains 16 draft scenarios, including English, Khmer, and mixed-language wording, a follow-up, missing evidence, ERP quoting, consent, and cross-company requests. The answerable checks point to candidate IDs and require approval first. Checked that the draft utterances are absent as exact normalized matches from both source question columns. These are authored checks. Add independently collected, anonymized support questions for the actual evaluation. No chatbot or retrieval tests have run against the draft scenarios.

Compare keyword search with multilingual hybrid search on answerable questions. Track whether the correct source appears in the top three, whether the final answer is supported and uses the requested language, and whether the assistant handles unknowns without unsupported claims. Any observed pricing disclosure, cross-company result, or lead written without consent blocks a customer rollout. Report results separately for English, Khmer and mixed-language queries. If a missing answer is common, ask for the applicable FAQ or version-specific manual so the coverage grows where customers need it.

Verified the local CSVs contain exactly 24 pending candidates and 16 unrun checks with valid links. The review pack is Git ignored. The existing 23 automated tests passed with `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`. The pilot is still at source review, with no answers approved or imported into Dify.

## 2026-11-20 — Local MVP

The user authorized moving past the audited Phase 1 into a working MVP. Implemented and started a local FastAPI service with a responsive chat page and PostgreSQL 17 / pgvector 0.8.7. The browser demo uses a separate database with 12 labeled synthetic entries across six companies. The separate MAQSU pilot imports only explicit reviewer approvals from the audit. A run using the actual pending review sheet published zero rows.

The MVP uses a single engine with server-selected company scope, explicit SQL filters, row-level security, and a restricted application role. It returns reviewed bilingual wording and a citation. The lexical matcher uses Unicode character trigrams, including Khmer. The optional multilingual embedding adapter adds semantic scoring with pgvector. Retrieval abstains when signals are weak or competing. Versioned procedure entries require a source, reviewer, product, and version. The backend logs unanswered requests without storing their text by default.

ERP price detection runs before evidence retrieval. The state machine asks for business type and modules, records an explicit reply to consent, and only then accepts a contact. One transaction persists the company-scoped lead and advances the session before the client sees a reference. Sales operators can export or delete records by company. It is a local intake queue, with no external dispatch configured.

Chose a repository-native local pilot so it can run with the installed database, separate the operator and customer roles, and be tested without transferring business data or setting up a Dify account. The app uses reviewed wording directly. It has no open-ended generation provider configured. The optional embeddings adapter was exercised against PostgreSQL with controlled fixture vectors, and a live language model has not been benchmarked.

Verification executed:

- `./scripts/run-local.sh demo` and `COMPANY_AI_HTTP_PORT=8766 ./scripts/run-local.sh pilot` ran successfully. Both health checks passed.
- **32 automated tests passed**, including 9 MVP integration tests against a dedicated database and the restricted application role. Cases cover bilingual matching, source approval, company isolation, exact procedure versions, pricing in English and Khmer, consent refusal, and concurrent lead writes.
- A headless Chrome test passed for English and Khmer replies, the version clarification flow, consent and successful persistence using synthetic contact details, company switching, and a 390 px viewport without horizontal overflow.
- The evaluation command retrieved the expected source for three synthetic queries in English, Khmer, and mixed language, and returned no result on one unrelated synthetic query. This only verifies the evaluation path. No real-business quality score was measured.
- `docker compose config --quiet` passed. The Docker daemon was stopped in this workspace, so a container build and startup were not executed. Native PostgreSQL and the local HTTP paths were exercised.
- Python compilation, JavaScript and shell syntax, dependency consistency, and Git ignore checks passed. No credentials, audit bundles, review decisions, session state, or lead files were staged.

Customer rollout still needs authorized MAQSU reviews, real held-out bilingual evaluation, verified manuals for detailed procedures, and a designated sales operator. Public deployment also needs a protected ingress and retention configuration. The other five companies can add reviewed knowledge using the same importer without mixing their data.

## 2026-11-20 — MAQSU review evidence and retrieval diagnostic

All 24 original review decisions were pending. Prepared a private `review-with-evidence.csv` in the pilot review directory with official MAQSU source pointers for all 24 candidates and ten shorter bilingual drafts for the first batch. The ten cover inventory, POS, accounting, sales, purchasing, the product catalog, languages, deployment options, reporting an issue, and the definition of ERP. The original review sheet remains the audit snapshot. Two support policy rows require confirmation of the currently applicable agreement before review. [MAQSU product catalog](https://maqsu.com/en/products-listing-details) · [MAQSU service agreement](https://maqsu.com/en/sla)

The new sheet passes importer validation with zero publishable decisions. The database still has zero approved MAQSU business answers. An authorized reviewer should check both languages and the suggested citations for `FIRST_BATCH`, then record their name, date, and explicit decisions.

The offline diagnostic compared lexical search with a cached multilingual E5 model on the same 276 candidate question variants. It used seven drafted answerable prompts and two unsupported probes, all evaluated without importing unapproved answers. The lexical gate accepted none of the seven. E5 ranked the expected candidate first in six of seven, with a miss on the Khmer language-support question. The existing ambiguity gate abstained on all seven and on both unsupported probes. This sample is too small to establish live accuracy or justify a lower production threshold. No acceptance threshold was changed. The model ran locally with no draft inputs sent off the Mac. [Multilingual E5 model card](https://huggingface.co/intfloat/multilingual-e5-base)

The diagnostic also revealed that an informational deployment question and a Khmer support reporting question were being treated as requests for technical procedures. Updated routing to search FAQs for those cases while preserving the version requirement for explicit how-to instructions. The rerun found zero procedure misroutes in the seven drafted answerable cases. All 34 repository tests passed, including two new routing regression tests. Reproduction commands are in the README. The review sheet and diagnostic outputs are excluded from Git.

## 2026-11-20 — Verified FAQ picker

Added a bilingual FAQ picker as a second way to get a reliable answer when free-text matching is uncertain. The picker shows up to 24 approved general FAQ entries in the selected company. It uses only separately reviewed customer-facing labels, and it opens after a general fallback when labels are available. Selecting a question fetches the approved answer by ID under the current company's session and rechecks approval, language, and display rules. Versioned procedures stay out of the general picker, and the quote workflow blocks the picker until it is finished or cancelled.

Added optional `public_question_en` and `public_question_km` columns to the review importer and PostgreSQL migration. The ten MAQSU first-batch rows now have draft labels in both languages. All still await review. A pilot import published zero rows and the live MAQSU pilot showed no topics. The synthetic demo provides one selectable topic per company.

Applied the idempotent migration to the local demo, pilot, and verification databases. All **36 tests passed**, including topic selection in Khmer, cross-company session rejection, active quotation protection, and revocation. A Chrome test at a mobile viewport verified that the fallback opens the picker, a Khmer selection returns the source, the quotation flow hides the picker, and the pending pilot shows no choices. Retrieval thresholds were unchanged. Start the demo and select a company to try the flow.
