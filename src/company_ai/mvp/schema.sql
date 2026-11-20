CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE SCHEMA IF NOT EXISTS assistant_mvp;
SET LOCAL search_path TO assistant_mvp, public;

CREATE TABLE IF NOT EXISTS companies (
    id text PRIMARY KEY
);
INSERT INTO companies (id) VALUES
    ('MAQSU'), ('CLOSO'), ('GIANTFOCUS'), ('FALCORA'), ('ClickHR'), ('GIANTBROTHER')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS knowledge (
    company_id text REFERENCES companies NOT NULL,
    id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('faq', 'procedure')),
    product text NOT NULL DEFAULT '',
    version text NOT NULL DEFAULT '',
    answer_en text NOT NULL,
    answer_km text NOT NULL,
    citation text NOT NULL,
    reviewer text NOT NULL,
    reviewed_on date NOT NULL,
    status text NOT NULL CHECK (status IN ('APPROVED', 'REVOKED')),
    CHECK (kind <> 'procedure' OR (product <> '' AND version <> '')),
    PRIMARY KEY (company_id, id)
);

ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS public_question_en text;
ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS public_question_km text;

CREATE TABLE IF NOT EXISTS questions (
    company_id text NOT NULL,
    knowledge_id text NOT NULL,
    wording text NOT NULL,
    embedding_model text,
    embedding vector,
    CHECK ((embedding_model IS NULL) = (embedding IS NULL)),
    FOREIGN KEY (company_id, knowledge_id) REFERENCES knowledge ON DELETE CASCADE,
    PRIMARY KEY (company_id, knowledge_id, wording)
);

CREATE TABLE IF NOT EXISTS conversations (
    company_id text REFERENCES companies NOT NULL,
    token_hash text NOT NULL,
    language text NOT NULL CHECK (language IN ('en', 'km')),
    phase text NOT NULL DEFAULT 'idle' CHECK (phase IN ('idle', 'scope', 'consent', 'contact')),
    business_type text,
    modules text,
    consented_at timestamptz,
    last_answer_id text,
    expires_at timestamptz NOT NULL DEFAULT now() + interval '24 hours',
    PRIMARY KEY (company_id, token_hash)
);

CREATE TABLE IF NOT EXISTS leads (
    company_id text REFERENCES companies NOT NULL,
    id uuid NOT NULL,
    business_type text NOT NULL,
    modules text NOT NULL,
    name text NOT NULL,
    channel text NOT NULL CHECK (channel IN ('phone', 'telegram')),
    contact text NOT NULL,
    consented_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, id)
);

CREATE TABLE IF NOT EXISTS knowledge_gaps (
    company_id text REFERENCES companies NOT NULL,
    id bigint GENERATED ALWAYS AS IDENTITY,
    language text NOT NULL CHECK (language IN ('en', 'km')),
    reason text NOT NULL,
    question text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, id)
);

DO $$
DECLARE tenant_table text;
BEGIN
    FOREACH tenant_table IN ARRAY ARRAY['knowledge','questions','conversations','leads','knowledge_gaps']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tenant_table);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tenant_table);
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies WHERE schemaname = 'assistant_mvp'
                AND tablename = tenant_table AND policyname = 'company_scope'
        ) THEN
            EXECUTE format(
                'CREATE POLICY company_scope ON %I USING (company_id = current_setting(''company_ai.tenant'', true)) WITH CHECK (company_id = current_setting(''company_ai.tenant'', true))',
                tenant_table
            );
        END IF;
    END LOOP;
END
$$;
