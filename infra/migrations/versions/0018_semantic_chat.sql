-- Stage 4 (ADR-0071, ADR-0072, ADR-0070): the semantic corpus with one 768-dimension vector
-- column, server-side chat conversations scoped to a client identifier, and the LLM call ledger
-- that the daily spend and token caps are summed from. Additive; no earlier object changes.
-- The query login reads semantic documents; the application login writes all four tables.

CREATE TABLE app.semantic_document (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_type text NOT NULL CHECK (doc_type IN (
    'parameter','qc_policy','aggregation_unit','operation','presentation','limit',
    'region','region_alias','example','help')),
  key text NOT NULL CHECK (length(key) BETWEEN 1 AND 256),
  title text NOT NULL CHECK (length(title) BETWEEN 1 AND 512),
  text text NOT NULL CHECK (length(text) BETWEEN 1 AND 8192),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  embedding_model text NOT NULL CHECK (length(embedding_model) BETWEEN 1 AND 128),
  embedding_version text NOT NULL CHECK (length(embedding_version) BETWEEN 1 AND 128),
  embedding_dimensions integer NOT NULL CHECK (embedding_dimensions = 768),
  embedding vector(768) NOT NULL,
  valid_from timestamptz NOT NULL DEFAULT clock_timestamp(),
  valid_to timestamptz,
  access_scope text NOT NULL DEFAULT 'public' CHECK (access_scope IN ('public')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (valid_to IS NULL OR valid_to > valid_from),
  UNIQUE (doc_type, key, embedding_model)
);
CREATE INDEX semantic_document_model ON app.semantic_document(embedding_model, doc_type);

CREATE TABLE app.chat_conversation (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id text NOT NULL CHECK (client_id ~ '^[A-Za-z0-9._:-]{1,64}$'),
  title text NOT NULL DEFAULT '' CHECK (length(title) <= 200),
  message_count integer NOT NULL DEFAULT 0 CHECK (message_count >= 0),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX chat_conversation_client ON app.chat_conversation(client_id, updated_at DESC);

CREATE TABLE app.chat_message (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL REFERENCES app.chat_conversation(id) ON DELETE CASCADE,
  seq integer NOT NULL CHECK (seq >= 1),
  role text NOT NULL CHECK (role IN ('user','assistant')),
  kind text NOT NULL CHECK (kind IN (
    'user','answer','clarification','greeting','help','unsupported','error')),
  text text NOT NULL CHECK (length(text) <= 8192),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  correlation_id text CHECK (correlation_id ~ '^[A-Za-z0-9._:-]{1,64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (conversation_id, seq)
);

CREATE TABLE app.llm_call (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  day date NOT NULL DEFAULT (clock_timestamp() AT TIME ZONE 'UTC')::date,
  feature text NOT NULL CHECK (feature IN ('plan','narrate','embed','eval')),
  provider text NOT NULL CHECK (length(provider) BETWEEN 1 AND 64),
  model text NOT NULL CHECK (length(model) BETWEEN 1 AND 128),
  model_version text,
  prompt_version text NOT NULL CHECK (length(prompt_version) BETWEEN 1 AND 64),
  input_tokens integer NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
  output_tokens integer NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
  thinking_tokens integer NOT NULL DEFAULT 0 CHECK (thinking_tokens >= 0),
  estimated_usd numeric(12,6) NOT NULL DEFAULT 0 CHECK (estimated_usd >= 0),
  pricing_version text NOT NULL,
  priced_as_default boolean NOT NULL DEFAULT false,
  latency_ms double precision NOT NULL CHECK (latency_ms >= 0),
  status text NOT NULL CHECK (status IN ('ok','error')),
  error_code text,
  conversation_id uuid,
  message_id uuid,
  correlation_id text
);
CREATE INDEX llm_call_day ON app.llm_call(day, provider);

REVOKE ALL ON app.semantic_document, app.chat_conversation, app.chat_message, app.llm_call
  FROM PUBLIC;
GRANT SELECT ON app.semantic_document TO floatchat_query;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'floatchat_app') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.semantic_document, app.chat_conversation,
      app.chat_message, app.llm_call TO floatchat_app;
  END IF;
END $$;
