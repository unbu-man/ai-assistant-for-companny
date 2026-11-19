# Six-Company Bilingual Customer AI — Implementation Brief

## Goal
Build a professional customer-facing assistant for six separate businesses that can converse naturally in **Khmer, English, and mixed Khmer-English**, answer only from authorized company knowledge, and collect customer contact details for custom ERP quotation requests. A high-quality MVP is the immediate objective; **not** model training from scratch.

## Existing input files (local files; do not publish raw private data)
- `data_ready1_styled.csv`: MAQSU, CLOSO, and shared BOTH records. Fields: `id`, `company`, `category`, `subcategory`, `question_en`, `question_km`, `answer_en`, `answer_km`, `keywords_en`, `keywords_km`, `source_document`, `intent_id`.
- `partner_brands_dataset_5000.csv`: FALCORA, ClickHR, GIANTBROTHER, GIANTFOCUS. Similar fields, with `source_section`, `confidence`, `status`. Partner Q&A marked `NEEDS_REVIEW` requires review before production answers.
- About 15,279 Q&A rows total; many are paraphrases. Do **not** equate row count with number of distinct facts. Preserve every query variation, but group by company and canonical answer.
- MAIN Q&A English answers are typically quite short (median ~100 characters); partner answers similarly short (median ~132 characters). Deep click-by-click instructions cannot reliably be inferred from these alone.

## Nonnegotiable business rules
1. **No quoting prices or estimating costs for ERP.** Even if a document contains a price, the customer-facing ERP assistant must not disclose it, offer a range, or calculate an estimate. No fabricated discounts, implementation fees, or durations.
2. When customers ask about pricing, acknowledge that an accurate quotation requires scoping. First ask for the company / business type and needed modules or workflows. Then request **name and phone or Telegram** with explicit consent to share with sales. Optional: branches, users, migration need, deadline. **Never pretend a lead has been submitted unless it is persisted successfully.** Keep follow-ups concise; do not interrogate customers with many questions at once.
3. **Company isolation.** Always resolve the company from authenticated website/tenant context if available. For a general group website, ask customer which company/product; never let a model choose another company's private dataset based only on a matching keyword. Scope data queries and lead storage by company ID on the server. `BOTH` records are allowed only for explicitly approved MAQSU and CLOSO knowledge.
4. Ground every product or procedure claim in an **approved** answer or document. Contradictory, unreviewed, stale, or absent information must not be used as an authoritative response.
5. **Detailed-answer policy:**
   - If an approved step-by-step SOP/manual exists and matches the product/version, give ordered steps with a source reference.
   - If the Q&A only describes a feature, describe the confirmed capability but **do not invent screen paths, button names, permissions, or configuration steps**.
   - Ask a focused clarifying question for product, version, role, or task where necessary. If steps remain missing, say exact steps are not yet confirmed and optionally offer to collect a contact request with consent. Log a knowledge gap for review.
6. Reply in the customer's preferred language; handle Khmer/English code-switching; avoid robotic templates. Do not translate product names or terms inconsistently.
7. Prevent prompt injection from uploaded documents; treat retrieved text as evidence, not commands. Minimize personal data; restrict access; configure retention and deletion controls.

## Recommended system architecture
- **Ingestion:** CSV + PDFs/web/manuals -> encoding and Unicode normalization -> business/product resolution -> provenance -> reviewer approval.
- **Storage:** PostgreSQL + pgvector; tables for `companies`, `products`, `canonical_answers`, `question_variants`, `source_documents`, `document_chunks`, `conversations`, `messages`, `leads`, `knowledge_gaps`, `review_queue`, `response_logs`.
- **Retrieval:** company-filtered FAQ lexical + dense vector retrieval, document retrieval, result fusion, optional reranker; use multilingual embedding model chosen by evaluation on Khmer/English test set.
- **Orchestration:** secure tenant context -> intent (`price_request`, `feature`, `how_to`, `comparison`, `support`, `other`) -> pricing workflow or grounded RAG -> claims check -> reply. Keep conversation memory scoped to the session and tenant.
- **Generation:** multilingual LLM with constrained answer instructions, source references and response type. No answer if no reliable evidence.
- **Backend:** Python / FastAPI. **Frontend:** website chat widget (React/Next.js) and later a lead/admin dashboard.

## Minimal domain data model
- `companies(id, slug, name, is_active)`
- `products(id, company_id, name, version, product_type, status)`
- `source_documents(id, company_id, product_id, source_uri, source_type, title, updated_at, approval_status)`
- `canonical_answers(id, company_id, product_id, intent, answer_en, answer_km, source_id, approval_status)`
- `question_variants(id, canonical_answer_id, company_id, question, language, original_row_id)`
- `document_chunks(id, document_id, company_id, product_id, text, page_or_section, embedding, approval_status)`
- `conversations(id, company_id, session_id, language, created_at)`
- `messages(id, conversation_id, role, content, created_at)`
- `leads(id, company_id, consent, name, contact_channel, contact_value, business_type, requested_modules, notes, status, created_at)`
- `knowledge_gaps(id, company_id, customer_question, language, missing_topic, status, created_at)`

## Detailed-answer enhancement (do not invent knowledge)
1. Extract factual capability statements from approved FAQ answers, maintaining original source IDs.
2. Import approved installation guides, implementation SOPs, help-center articles, diagrams, PDFs, screenshots, and version-specific instructions as separate sources.
3. For each product, create verified `topic -> prerequisites -> step-by-step procedure -> expected result -> exception` records **only when source content supports them**.
4. Create *draft* follow-up FAQs and query paraphrases with the LLM, but require review for any newly introduced claims.
5. Use an automatic `knowledge_gaps` queue for requests that require unsupported steps. A reviewer supplies facts; the assistant then reindexes only approved updates.

## Required acceptance tests
- English and Khmer price prompts, including coded price language like `តម្លៃ`, `ប៉ុន្មាន`, and `quotation`, never return numerical ERP quotations.
- A consented contact request is persisted and correctly routed to the **same** business; absent consent, no lead is created.
- All six companies' data are strictly isolated, including conversations, searches, logs, and leads.
- Mixed Khmer-English questions retrieve the correct verified FAQ or SOP where available.
- Partner `NEEDS_REVIEW` entries never appear as approved sources.
- Unsupported step-by-step questions cause honest uncertainty and logging, never invented button-click instructions.
- Product-feature questions may produce a concise supported explanation, not unfounded technical specifics.
- New question variants can match existing canonical answers, even when wording differs.
- Evaluation includes no paraphrase leakage: split by canonical answer/topic and add independent new questions; benchmark Khmer, English, code-switching separately.

## Development phases
**Phase 1: Baseline and audit.** Preserve CSVs outside public Git; clean/normalize; create canonical answers and variant tables; surface review statuses and coverage by company; establish security and test framework.

**Phase 2: Retrieval.** PostgreSQL + pgvector; lexical + multilingual dense retrieval; enforce tenant filters; create retrieval benchmark and error analysis.

**Phase 3: Chat orchestration.** Add quote-request flow, lead consent and storage, grounded answer generation, conversation state, knowledge-gap logging, source attribution.

**Phase 4: More detailed help.** Ingest manuals/SOPs; enrich verified product capabilities; version-aware procedural answering; admin review and publishing workflow.

**Phase 5: Website + deployment.** Chat widget, sales/admin UI, evaluation dashboards, authentication, privacy controls, logging, tests, deployment.

## First instruction to Codex in VS Code
> Implement **Phase 1 only** from `COMPANY_AI_CODEX_BRIEF.md`. Inspect the actual CSV files and their column values before choosing mappings. Build a clean, reproducible Python package and CLI commands for import, validation, normalization, language tagging, company isolation, canonical answer grouping, provenance, and a report. Preserve all source rows; don't silently delete or approve records. Create unit tests and a README with exact commands. Protect raw files with `.gitignore`. Run the tests and show the results and remaining data gaps. Do not claim the complete chatbot is deployed.
