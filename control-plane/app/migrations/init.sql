-- Bob Manager — Database Bootstrap
--
-- Initializes the entire schema on first boot of the Postgres container.
-- Postgres runs every .sql in /docker-entrypoint-initdb.d on empty data
-- dirs, so this file only executes once per fresh deployment. Subsequent
-- schema changes happen as edits to this file (no separate migrations
-- runner; see git history for incremental change context).



SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: access_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.access_tokens (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    token character varying(255) NOT NULL,
    label character varying(255) DEFAULT ''::character varying NOT NULL,
    email character varying(255) DEFAULT ''::character varying NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ai_agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_agents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    description text DEFAULT ''::text,
    system_prompt text NOT NULL,
    model_id uuid,
    temperature numeric(3,2) DEFAULT 0.70,
    max_tokens integer DEFAULT 4096,
    tools jsonb DEFAULT '[]'::jsonb,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: ai_models; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_models (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    provider_id uuid NOT NULL,
    model_identifier character varying(255) NOT NULL,
    capabilities jsonb DEFAULT '{}'::jsonb,
    parameters jsonb DEFAULT '{}'::jsonb,
    is_available boolean DEFAULT true,
    last_seen_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: ai_providers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_providers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    provider_type character varying(50) NOT NULL,
    base_url character varying(500) NOT NULL,
    api_key character varying(500),
    server_id uuid,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: blog_posts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.blog_posts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    title character varying(500) NOT NULL,
    slug character varying(200) NOT NULL,
    content text DEFAULT ''::text NOT NULL,
    summary character varying(1000) DEFAULT ''::character varying NOT NULL,
    identity character varying(255) DEFAULT 'admin'::character varying NOT NULL,
    tags jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: blog_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.blog_tokens (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    token character varying(255) NOT NULL,
    label character varying(255) DEFAULT ''::character varying NOT NULL,
    revoked boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: command_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.command_history (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    server_id uuid NOT NULL,
    command text NOT NULL,
    exit_code integer,
    stdout text DEFAULT ''::text,
    stderr text DEFAULT ''::text,
    executed_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone
);


--
-- Name: consumer_apps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consumer_apps (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    app_id character varying(64) NOT NULL,
    name character varying(255) DEFAULT ''::character varying NOT NULL,
    secret text NOT NULL,
    notes text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    revoked_at timestamp with time zone,
    last_used_at timestamp with time zone
);


--
-- Name: conversations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    title character varying(500) DEFAULT 'New Conversation'::character varying,
    status character varying(50) DEFAULT 'active'::character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    acl jsonb DEFAULT '{"owner": "admin", "editors": [], "viewers": []}'::jsonb NOT NULL,
    agent_id uuid,
    tools jsonb DEFAULT '[]'::jsonb
);


--
-- Name: cron_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cron_jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    description text DEFAULT ''::text,
    expression character varying(100) NOT NULL,
    method character varying(30) DEFAULT 'orchestrator_inject'::character varying,
    instruction text DEFAULT ''::text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: execution_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.execution_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    execution_id uuid NOT NULL,
    step_id uuid NOT NULL,
    status character varying(50) DEFAULT 'pending'::character varying,
    exit_code integer,
    stdout text DEFAULT ''::text,
    stderr text DEFAULT ''::text,
    started_at timestamp with time zone,
    completed_at timestamp with time zone
);


--
-- Name: gpu_locks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gpu_locks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    server_id uuid NOT NULL,
    gpu_index integer NOT NULL,
    task_id uuid NOT NULL,
    locked_at timestamp with time zone DEFAULT now()
);


--
-- Name: lab_agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lab_agents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    lab_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    role text DEFAULT ''::text NOT NULL,
    system_prompt text DEFAULT ''::text NOT NULL,
    model_id uuid,
    temperature numeric(3,2) DEFAULT 0.70,
    max_tokens integer DEFAULT 4096,
    tools jsonb DEFAULT '[]'::jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    share_memory boolean DEFAULT false NOT NULL,
    tool_set_id uuid,
    callable_agents jsonb DEFAULT '[]'::jsonb NOT NULL,
    cron_expression character varying(100),
    cron_instruction text DEFAULT ''::text NOT NULL,
    prompt_template_id uuid,
    tool_set_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    library_agent_id uuid,
    anti_loop_enabled boolean DEFAULT false NOT NULL
);


--
-- Name: lab_loop_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lab_loop_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    lab_id uuid NOT NULL,
    severity text NOT NULL,
    score integer NOT NULL,
    signals jsonb DEFAULT '[]'::jsonb NOT NULL,
    removed_message_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    removed_count integer DEFAULT 0 NOT NULL,
    recovered boolean DEFAULT false NOT NULL,
    detected_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: lab_memories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lab_memories (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    lab_id uuid NOT NULL,
    agent_id uuid,
    scope character varying(20) DEFAULT 'lab'::character varying NOT NULL,
    key character varying(255) NOT NULL,
    content text NOT NULL,
    memory_type character varying(20) DEFAULT 'fact'::character varying NOT NULL,
    importance integer DEFAULT 5 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone,
    is_hidden boolean DEFAULT false NOT NULL
);


--
-- Name: lab_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lab_messages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    lab_id uuid NOT NULL,
    iteration integer DEFAULT 0 NOT NULL,
    sender_type character varying(20) NOT NULL,
    sender_agent_id uuid,
    sender_name character varying(255),
    target_agent_id uuid,
    target_name character varying(255),
    content text NOT NULL,
    message_type character varying(20) DEFAULT 'message'::character varying NOT NULL,
    model_used character varying(255),
    provider_used character varying(255),
    tokens_in integer,
    tokens_out integer,
    duration_ms integer,
    tool_name character varying(100),
    tool_input jsonb,
    tool_output jsonb,
    extra jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: lab_rag_access; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lab_rag_access (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    lab_id uuid NOT NULL,
    collection_id uuid NOT NULL,
    can_read boolean DEFAULT true NOT NULL,
    can_write boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: lab_resources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lab_resources (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    lab_id uuid NOT NULL,
    filename character varying(500) NOT NULL,
    original_name character varying(500) NOT NULL,
    content_type character varying(255) DEFAULT 'application/octet-stream'::character varying NOT NULL,
    size_bytes bigint DEFAULT 0 NOT NULL,
    resource_type character varying(50) DEFAULT 'file'::character varying NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: lab_schedule_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lab_schedule_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    lab_id uuid NOT NULL,
    triggered_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    status character varying(20) DEFAULT 'running'::character varying NOT NULL,
    iterations_run integer DEFAULT 0 NOT NULL,
    error text
);


--
-- Name: lab_server_access; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lab_server_access (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    lab_id uuid NOT NULL,
    server_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: lab_tools; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lab_tools (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    lab_id uuid NOT NULL,
    name character varying(100) NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    tool_type character varying(50) DEFAULT 'builtin'::character varying NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    execution_side character varying(10) DEFAULT 'server'::character varying NOT NULL,
    is_enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: lab_web3_access; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lab_web3_access (
    id uuid NOT NULL,
    lab_id uuid NOT NULL,
    wallet_id uuid NOT NULL,
    can_read boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: labs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.labs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    status character varying(20) DEFAULT 'created'::character varying NOT NULL,
    loop_type character varying(50) DEFAULT 'plan_execute'::character varying NOT NULL,
    loop_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    orchestrator_model_id uuid,
    orchestrator_prompt text DEFAULT ''::text NOT NULL,
    orchestrator_temperature numeric(3,2) DEFAULT 0.70,
    orchestrator_max_tokens integer DEFAULT 4096,
    max_iterations integer,
    max_duration_sec integer,
    current_iteration integer DEFAULT 0 NOT NULL,
    cron_expression character varying(100),
    next_run_at timestamp with time zone,
    context_files jsonb DEFAULT '[]'::jsonb NOT NULL,
    started_at timestamp with time zone,
    paused_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    share_memory_override boolean,
    tool_max_calls integer DEFAULT 10,
    tool_timeout_sec integer DEFAULT 30,
    tool_max_output_kb integer DEFAULT 256,
    tool_container_memory_mb integer DEFAULT 512,
    orchestrator_tools jsonb DEFAULT '[]'::jsonb NOT NULL,
    orchestrator_tool_set_id uuid,
    orchestrator_prompt_template_id uuid,
    auto_sweep_memory boolean DEFAULT false NOT NULL,
    strategy_prompt_override text,
    orchestrator_tool_set_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    failure_reason text,
    cron_job_ids jsonb DEFAULT '[]'::jsonb,
    acl jsonb DEFAULT '{"owner": "admin", "editors": [], "viewers": []}'::jsonb NOT NULL,
    anti_loop_enabled boolean DEFAULT false NOT NULL,
    is_public boolean DEFAULT false NOT NULL
);


--
-- Name: library_agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.library_agents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    role text DEFAULT ''::text NOT NULL,
    system_prompt text DEFAULT ''::text NOT NULL,
    prompt_template_id uuid,
    model_id uuid,
    temperature numeric(3,2) DEFAULT 0.70 NOT NULL,
    max_tokens integer DEFAULT 4096 NOT NULL,
    tools jsonb DEFAULT '[]'::jsonb NOT NULL,
    tool_set_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    share_memory boolean DEFAULT false NOT NULL,
    callable_agents jsonb DEFAULT '[]'::jsonb NOT NULL,
    cron_expression character varying(100),
    cron_instruction text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    anti_loop_enabled boolean DEFAULT false NOT NULL,
    is_public boolean DEFAULT false NOT NULL
);


--
-- Name: llm_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.llm_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    event_type character varying(20) NOT NULL,
    model_identifier character varying(255) NOT NULL,
    provider_name character varying(255),
    server_name character varying(255),
    caller_type character varying(30) NOT NULL,
    caller_name character varying(255),
    lab_id uuid,
    conversation_id uuid,
    tokens_in integer,
    tokens_out integer,
    duration_ms integer,
    attempt integer,
    max_attempts integer,
    error text,
    created_at timestamp with time zone DEFAULT now(),
    request_id uuid,
    input_messages jsonb,
    output_content text
);


--
-- Name: messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.messages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    conversation_id uuid NOT NULL,
    role character varying(50) NOT NULL,
    content text DEFAULT ''::text NOT NULL,
    agent_id uuid,
    agent_name character varying(255),
    model_used character varying(255),
    provider_used character varying(255),
    tokens_in integer,
    tokens_out integer,
    duration_ms integer,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: module_steps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.module_steps (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    module_id uuid NOT NULL,
    step_order integer NOT NULL,
    name character varying(255) NOT NULL,
    description text DEFAULT ''::text,
    status character varying(20) DEFAULT 'not-started'::character varying,
    included_task_ids jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: module_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.module_tasks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    module_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    description text DEFAULT ''::text,
    status character varying(20) DEFAULT 'not-started'::character varying,
    deadline timestamp with time zone,
    dependencies jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: orchestrator_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.orchestrator_settings (
    id integer DEFAULT 1 NOT NULL,
    orchestrator_model character varying(255),
    orchestrator_provider character varying(50) DEFAULT 'ollama'::character varying,
    orchestrator_server_id uuid,
    max_concurrent_tasks integer DEFAULT 4,
    artifact_storage_path character varying(500) DEFAULT '/data/artifacts'::character varying,
    log_retention_days integer DEFAULT 365,
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT orchestrator_settings_id_check CHECK ((id = 1))
);


--
-- Name: orchestrator_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.orchestrator_tasks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    conversation_id uuid NOT NULL,
    parent_task_id uuid,
    agent_id uuid,
    task_type character varying(100) DEFAULT 'inference'::character varying NOT NULL,
    priority integer DEFAULT 1,
    status character varying(50) DEFAULT 'queued'::character varying,
    input_data jsonb DEFAULT '{}'::jsonb,
    output_data jsonb,
    server_id uuid,
    gpu_index integer,
    error text,
    queued_at timestamp with time zone DEFAULT now(),
    started_at timestamp with time zone,
    completed_at timestamp with time zone
);


--
-- Name: platform_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.platform_settings (
    key character varying(100) NOT NULL,
    value jsonb DEFAULT '{}'::jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: portfolio_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.portfolio_snapshots (
    ts timestamp with time zone DEFAULT now() NOT NULL,
    wallet_id uuid,
    wallet_address character varying(42) NOT NULL,
    wallet_label character varying(255) DEFAULT ''::character varying,
    total_value_usd numeric(20,2) DEFAULT 0 NOT NULL,
    breakdown jsonb DEFAULT '{}'::jsonb
);


--
-- Name: project_modules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_modules (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    description text DEFAULT ''::text,
    "position" integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: project_workflows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_workflows (
    project_id uuid NOT NULL,
    workflow_id uuid NOT NULL
);


--
-- Name: projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.projects (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    description text DEFAULT ''::text,
    github_url character varying(500) DEFAULT ''::character varying,
    useful_commands jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    links jsonb DEFAULT '[]'::jsonb,
    themes jsonb DEFAULT '[]'::jsonb,
    notes jsonb DEFAULT '[]'::jsonb,
    acl jsonb DEFAULT '{"owner": "admin", "editors": [], "viewers": []}'::jsonb NOT NULL
);


--
-- Name: prompt_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.prompt_templates (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    content text NOT NULL,
    target character varying(20) DEFAULT 'agent'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: quote_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quote_requests (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    email character varying(255) NOT NULL,
    company character varying(255) DEFAULT ''::character varying,
    phone character varying(100) DEFAULT ''::character varying,
    plan character varying(100) DEFAULT ''::character varying,
    description text DEFAULT ''::text,
    status character varying(50) DEFAULT 'pending'::character varying,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: rag_collections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rag_collections (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    display_name character varying(255) NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    embedding_model character varying(255) DEFAULT 'all-MiniLM-L6-v2'::character varying NOT NULL,
    embedding_dim integer DEFAULT 384 NOT NULL,
    distance_metric character varying(20) DEFAULT 'cosine'::character varying NOT NULL,
    default_chunk_size integer DEFAULT 512 NOT NULL,
    default_chunk_overlap integer DEFAULT 64 NOT NULL,
    default_splitter character varying(50) DEFAULT 'recursive'::character varying NOT NULL,
    document_count integer DEFAULT 0 NOT NULL,
    chunk_count integer DEFAULT 0 NOT NULL,
    total_size_bytes bigint DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    acl jsonb DEFAULT '{"owner": "admin", "editors": [], "viewers": []}'::jsonb NOT NULL,
    rag_mode character varying(20) DEFAULT 'vector'::character varying NOT NULL,
    lightrag_model_id uuid,
    lightrag_search_mode character varying(10) DEFAULT 'hybrid'::character varying NOT NULL,
    CONSTRAINT ck_rag_collections_lightrag_search_mode CHECK (((lightrag_search_mode)::text = ANY ((ARRAY['local'::character varying, 'global'::character varying, 'hybrid'::character varying])::text[]))),
    CONSTRAINT ck_rag_collections_rag_mode CHECK (((rag_mode)::text = ANY ((ARRAY['vector'::character varying, 'lightrag'::character varying])::text[])))
);


--
-- Name: rag_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rag_documents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    collection_id uuid NOT NULL,
    filename character varying(500) NOT NULL,
    content_type character varying(255) DEFAULT 'text/plain'::character varying NOT NULL,
    size_bytes bigint DEFAULT 0 NOT NULL,
    chunk_size integer NOT NULL,
    chunk_overlap integer NOT NULL,
    splitter character varying(50) NOT NULL,
    chunk_count integer DEFAULT 0 NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    error_message text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    ingested_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: request_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.request_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    ip text,
    method text NOT NULL,
    path text NOT NULL,
    query text,
    status integer NOT NULL,
    duration_ms integer DEFAULT 0 NOT NULL,
    user_email text,
    user_role text,
    user_agent text,
    referer text,
    module text DEFAULT 'other'::text NOT NULL,
    severity text DEFAULT 'info'::text NOT NULL,
    error_msg text
);


--
-- Name: resource_projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.resource_projects (
    resource_id uuid NOT NULL,
    project_id uuid NOT NULL
);


--
-- Name: resources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.resources (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    description text DEFAULT ''::text,
    links jsonb DEFAULT '[]'::jsonb,
    themes jsonb DEFAULT '[]'::jsonb,
    notes jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    acl jsonb DEFAULT '{"owner": "admin", "editors": [], "viewers": []}'::jsonb NOT NULL
);


--
-- Name: servers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.servers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    host character varying(255) NOT NULL,
    port integer DEFAULT 9100,
    agent_token character varying(255),
    status character varying(50) DEFAULT 'offline'::character varying,
    os_info jsonb DEFAULT '{}'::jsonb,
    gpu_info jsonb DEFAULT '{}'::jsonb,
    last_heartbeat timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: theme_colors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.theme_colors (
    name character varying(100) NOT NULL,
    color character varying(7) DEFAULT '#a855f7'::character varying
);


--
-- Name: tool_configs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tool_configs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tool_type character varying(50) NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: tool_sets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tool_sets (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    tools jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: trade_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_history (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    wallet_address character varying(42) NOT NULL,
    chain character varying(20) NOT NULL,
    tx_hash character varying(66) NOT NULL,
    tx_type character varying(20) NOT NULL,
    from_token character varying(42),
    from_token_symbol character varying(20),
    from_amount character varying(78),
    to_token character varying(42),
    to_token_symbol character varying(20),
    to_amount character varying(78),
    gas_used integer,
    gas_price_gwei double precision,
    value_usd double precision,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    position_id uuid,
    lab_id uuid
);


--
-- Name: trading_positions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trading_positions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    wallet_address character varying(42) NOT NULL,
    chain character varying(20) NOT NULL,
    token_address character varying(42) NOT NULL,
    token_symbol character varying(20) DEFAULT '???'::character varying NOT NULL,
    amount double precision DEFAULT 0.0 NOT NULL,
    entry_price_usd double precision,
    entry_tx_hash character varying(66),
    entry_at timestamp with time zone DEFAULT now() NOT NULL,
    exit_price_usd double precision,
    exit_tx_hash character varying(66),
    exit_at timestamp with time zone,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    stop_loss_usd double precision,
    take_profit_usd double precision,
    notes text,
    lab_id uuid
);


--
-- Name: trial_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trial_requests (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    email character varying(255) NOT NULL,
    enterprise character varying(255) DEFAULT ''::character varying NOT NULL,
    role character varying(255) DEFAULT ''::character varying NOT NULL,
    purpose text DEFAULT ''::text NOT NULL,
    status character varying(50) DEFAULT 'pending'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: wallets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wallets (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    address character varying(42) NOT NULL,
    label character varying(255) DEFAULT ''::character varying,
    created_at timestamp with time zone DEFAULT now(),
    acl jsonb DEFAULT '{"owner": "admin", "editors": [], "viewers": []}'::jsonb NOT NULL
);


--
-- Name: web3_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.web3_settings (
    id integer DEFAULT 1 NOT NULL,
    refresh_interval integer DEFAULT 300 NOT NULL,
    retention_full_hours integer DEFAULT 168 NOT NULL,
    retention_step_hours integer DEFAULT 1 NOT NULL,
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT web3_settings_id_check CHECK ((id = 1))
);


--
-- Name: workflow_executions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_executions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workflow_id uuid NOT NULL,
    server_id uuid NOT NULL,
    status character varying(50) DEFAULT 'pending'::character varying,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: workflow_steps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_steps (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workflow_id uuid NOT NULL,
    step_order integer NOT NULL,
    name character varying(255) NOT NULL,
    command text NOT NULL,
    timeout_seconds integer DEFAULT 300,
    continue_on_error boolean DEFAULT false
);


--
-- Name: workflows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflows (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    description text DEFAULT ''::text,
    definition jsonb DEFAULT '{}'::jsonb NOT NULL,
    project_id uuid,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: access_tokens access_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_tokens
    ADD CONSTRAINT access_tokens_pkey PRIMARY KEY (id);


--
-- Name: access_tokens access_tokens_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_tokens
    ADD CONSTRAINT access_tokens_token_key UNIQUE (token);


--
-- Name: ai_agents ai_agents_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_agents
    ADD CONSTRAINT ai_agents_name_key UNIQUE (name);


--
-- Name: ai_agents ai_agents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_agents
    ADD CONSTRAINT ai_agents_pkey PRIMARY KEY (id);


--
-- Name: ai_models ai_models_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_models
    ADD CONSTRAINT ai_models_pkey PRIMARY KEY (id);


--
-- Name: ai_models ai_models_provider_id_model_identifier_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_models
    ADD CONSTRAINT ai_models_provider_id_model_identifier_key UNIQUE (provider_id, model_identifier);


--
-- Name: ai_providers ai_providers_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_providers
    ADD CONSTRAINT ai_providers_name_key UNIQUE (name);


--
-- Name: ai_providers ai_providers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_providers
    ADD CONSTRAINT ai_providers_pkey PRIMARY KEY (id);


--
-- Name: blog_posts blog_posts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blog_posts
    ADD CONSTRAINT blog_posts_pkey PRIMARY KEY (id);


--
-- Name: blog_tokens blog_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blog_tokens
    ADD CONSTRAINT blog_tokens_pkey PRIMARY KEY (id);


--
-- Name: blog_tokens blog_tokens_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blog_tokens
    ADD CONSTRAINT blog_tokens_token_key UNIQUE (token);


--
-- Name: command_history command_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.command_history
    ADD CONSTRAINT command_history_pkey PRIMARY KEY (id);


--
-- Name: consumer_apps consumer_apps_app_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consumer_apps
    ADD CONSTRAINT consumer_apps_app_id_key UNIQUE (app_id);


--
-- Name: consumer_apps consumer_apps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consumer_apps
    ADD CONSTRAINT consumer_apps_pkey PRIMARY KEY (id);


--
-- Name: conversations conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_pkey PRIMARY KEY (id);


--
-- Name: cron_jobs cron_jobs_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cron_jobs
    ADD CONSTRAINT cron_jobs_name_key UNIQUE (name);


--
-- Name: cron_jobs cron_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cron_jobs
    ADD CONSTRAINT cron_jobs_pkey PRIMARY KEY (id);


--
-- Name: execution_logs execution_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.execution_logs
    ADD CONSTRAINT execution_logs_pkey PRIMARY KEY (id);


--
-- Name: gpu_locks gpu_locks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gpu_locks
    ADD CONSTRAINT gpu_locks_pkey PRIMARY KEY (id);


--
-- Name: gpu_locks gpu_locks_server_id_gpu_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gpu_locks
    ADD CONSTRAINT gpu_locks_server_id_gpu_index_key UNIQUE (server_id, gpu_index);


--
-- Name: lab_agents lab_agents_lab_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_agents
    ADD CONSTRAINT lab_agents_lab_id_name_key UNIQUE (lab_id, name);


--
-- Name: lab_agents lab_agents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_agents
    ADD CONSTRAINT lab_agents_pkey PRIMARY KEY (id);


--
-- Name: lab_loop_events lab_loop_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_loop_events
    ADD CONSTRAINT lab_loop_events_pkey PRIMARY KEY (id);


--
-- Name: lab_memories lab_memories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_memories
    ADD CONSTRAINT lab_memories_pkey PRIMARY KEY (id);


--
-- Name: lab_messages lab_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_messages
    ADD CONSTRAINT lab_messages_pkey PRIMARY KEY (id);


--
-- Name: lab_rag_access lab_rag_access_lab_id_collection_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_rag_access
    ADD CONSTRAINT lab_rag_access_lab_id_collection_id_key UNIQUE (lab_id, collection_id);


--
-- Name: lab_rag_access lab_rag_access_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_rag_access
    ADD CONSTRAINT lab_rag_access_pkey PRIMARY KEY (id);


--
-- Name: lab_resources lab_resources_lab_id_filename_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_resources
    ADD CONSTRAINT lab_resources_lab_id_filename_key UNIQUE (lab_id, filename);


--
-- Name: lab_resources lab_resources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_resources
    ADD CONSTRAINT lab_resources_pkey PRIMARY KEY (id);


--
-- Name: lab_schedule_log lab_schedule_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_schedule_log
    ADD CONSTRAINT lab_schedule_log_pkey PRIMARY KEY (id);


--
-- Name: lab_server_access lab_server_access_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_server_access
    ADD CONSTRAINT lab_server_access_pkey PRIMARY KEY (id);


--
-- Name: lab_tools lab_tools_lab_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_tools
    ADD CONSTRAINT lab_tools_lab_id_name_key UNIQUE (lab_id, name);


--
-- Name: lab_tools lab_tools_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_tools
    ADD CONSTRAINT lab_tools_pkey PRIMARY KEY (id);


--
-- Name: lab_web3_access lab_web3_access_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_web3_access
    ADD CONSTRAINT lab_web3_access_pkey PRIMARY KEY (id);


--
-- Name: labs labs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.labs
    ADD CONSTRAINT labs_pkey PRIMARY KEY (id);


--
-- Name: library_agents library_agents_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.library_agents
    ADD CONSTRAINT library_agents_name_key UNIQUE (name);


--
-- Name: library_agents library_agents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.library_agents
    ADD CONSTRAINT library_agents_pkey PRIMARY KEY (id);


--
-- Name: llm_events llm_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_events
    ADD CONSTRAINT llm_events_pkey PRIMARY KEY (id);


--
-- Name: messages messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_pkey PRIMARY KEY (id);


--
-- Name: module_steps module_steps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.module_steps
    ADD CONSTRAINT module_steps_pkey PRIMARY KEY (id);


--
-- Name: module_tasks module_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.module_tasks
    ADD CONSTRAINT module_tasks_pkey PRIMARY KEY (id);


--
-- Name: orchestrator_settings orchestrator_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orchestrator_settings
    ADD CONSTRAINT orchestrator_settings_pkey PRIMARY KEY (id);


--
-- Name: orchestrator_tasks orchestrator_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orchestrator_tasks
    ADD CONSTRAINT orchestrator_tasks_pkey PRIMARY KEY (id);


--
-- Name: platform_settings platform_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.platform_settings
    ADD CONSTRAINT platform_settings_pkey PRIMARY KEY (key);


--
-- Name: project_modules project_modules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_modules
    ADD CONSTRAINT project_modules_pkey PRIMARY KEY (id);


--
-- Name: project_workflows project_workflows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_workflows
    ADD CONSTRAINT project_workflows_pkey PRIMARY KEY (project_id, workflow_id);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);


--
-- Name: prompt_templates prompt_templates_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prompt_templates
    ADD CONSTRAINT prompt_templates_name_key UNIQUE (name);


--
-- Name: prompt_templates prompt_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prompt_templates
    ADD CONSTRAINT prompt_templates_pkey PRIMARY KEY (id);


--
-- Name: quote_requests quote_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quote_requests
    ADD CONSTRAINT quote_requests_pkey PRIMARY KEY (id);


--
-- Name: rag_collections rag_collections_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_collections
    ADD CONSTRAINT rag_collections_name_key UNIQUE (name);


--
-- Name: rag_collections rag_collections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_collections
    ADD CONSTRAINT rag_collections_pkey PRIMARY KEY (id);


--
-- Name: rag_documents rag_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_documents
    ADD CONSTRAINT rag_documents_pkey PRIMARY KEY (id);


--
-- Name: request_log request_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.request_log
    ADD CONSTRAINT request_log_pkey PRIMARY KEY (id);


--
-- Name: resource_projects resource_projects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_projects
    ADD CONSTRAINT resource_projects_pkey PRIMARY KEY (resource_id, project_id);


--
-- Name: resources resources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resources
    ADD CONSTRAINT resources_pkey PRIMARY KEY (id);


--
-- Name: servers servers_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.servers
    ADD CONSTRAINT servers_name_key UNIQUE (name);


--
-- Name: servers servers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.servers
    ADD CONSTRAINT servers_pkey PRIMARY KEY (id);


--
-- Name: theme_colors theme_colors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.theme_colors
    ADD CONSTRAINT theme_colors_pkey PRIMARY KEY (name);


--
-- Name: tool_configs tool_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_configs
    ADD CONSTRAINT tool_configs_pkey PRIMARY KEY (id);


--
-- Name: tool_configs tool_configs_tool_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_configs
    ADD CONSTRAINT tool_configs_tool_type_key UNIQUE (tool_type);


--
-- Name: tool_sets tool_sets_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_sets
    ADD CONSTRAINT tool_sets_name_key UNIQUE (name);


--
-- Name: tool_sets tool_sets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_sets
    ADD CONSTRAINT tool_sets_pkey PRIMARY KEY (id);


--
-- Name: trade_history trade_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_history
    ADD CONSTRAINT trade_history_pkey PRIMARY KEY (id);


--
-- Name: trading_positions trading_positions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trading_positions
    ADD CONSTRAINT trading_positions_pkey PRIMARY KEY (id);


--
-- Name: trial_requests trial_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trial_requests
    ADD CONSTRAINT trial_requests_pkey PRIMARY KEY (id);


--
-- Name: lab_server_access uq_lab_server_access; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_server_access
    ADD CONSTRAINT uq_lab_server_access UNIQUE (lab_id, server_id);


--
-- Name: lab_web3_access uq_lab_web3_access; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_web3_access
    ADD CONSTRAINT uq_lab_web3_access UNIQUE (lab_id, wallet_id);


--
-- Name: wallets wallets_address_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wallets
    ADD CONSTRAINT wallets_address_key UNIQUE (address);


--
-- Name: wallets wallets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wallets
    ADD CONSTRAINT wallets_pkey PRIMARY KEY (id);


--
-- Name: web3_settings web3_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.web3_settings
    ADD CONSTRAINT web3_settings_pkey PRIMARY KEY (id);


--
-- Name: workflow_executions workflow_executions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_executions
    ADD CONSTRAINT workflow_executions_pkey PRIMARY KEY (id);


--
-- Name: workflow_steps workflow_steps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_steps
    ADD CONSTRAINT workflow_steps_pkey PRIMARY KEY (id);


--
-- Name: workflows workflows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflows
    ADD CONSTRAINT workflows_pkey PRIMARY KEY (id);


--
-- Name: idx_access_tokens_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_access_tokens_token ON public.access_tokens USING btree (token);


--
-- Name: idx_ai_models_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ai_models_provider ON public.ai_models USING btree (provider_id);


--
-- Name: idx_blog_posts_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_blog_posts_created ON public.blog_posts USING btree (created_at DESC);


CREATE UNIQUE INDEX idx_blog_posts_slug ON public.blog_posts USING btree (slug);


--
-- Name: idx_blog_tokens_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_blog_tokens_token ON public.blog_tokens USING btree (token);


--
-- Name: idx_command_history_server; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_command_history_server ON public.command_history USING btree (server_id);


--
-- Name: idx_consumer_apps_app_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_consumer_apps_app_id ON public.consumer_apps USING btree (app_id);


--
-- Name: idx_conversations_acl; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversations_acl ON public.conversations USING gin (acl);


--
-- Name: idx_conversations_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversations_updated ON public.conversations USING btree (updated_at DESC);


--
-- Name: idx_execution_logs_execution; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_execution_logs_execution ON public.execution_logs USING btree (execution_id);


--
-- Name: idx_lab_loop_events_lab; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lab_loop_events_lab ON public.lab_loop_events USING btree (lab_id, detected_at DESC);


--
-- Name: idx_lab_memories_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lab_memories_agent ON public.lab_memories USING btree (agent_id);


--
-- Name: idx_lab_memories_lab; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lab_memories_lab ON public.lab_memories USING btree (lab_id, scope);


--
-- Name: idx_lab_messages_iteration; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lab_messages_iteration ON public.lab_messages USING btree (lab_id, iteration);


--
-- Name: idx_lab_messages_lab; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lab_messages_lab ON public.lab_messages USING btree (lab_id, created_at);


--
-- Name: idx_lab_rag_access_collection; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lab_rag_access_collection ON public.lab_rag_access USING btree (collection_id);


--
-- Name: idx_lab_rag_access_lab; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lab_rag_access_lab ON public.lab_rag_access USING btree (lab_id);


--
-- Name: idx_lab_resources_lab; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lab_resources_lab ON public.lab_resources USING btree (lab_id);


--
-- Name: idx_lab_server_access_lab; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lab_server_access_lab ON public.lab_server_access USING btree (lab_id);


--
-- Name: idx_lab_server_access_server; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lab_server_access_server ON public.lab_server_access USING btree (server_id);


--
-- Name: idx_lab_web3_access_lab; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lab_web3_access_lab ON public.lab_web3_access USING btree (lab_id);


--
-- Name: idx_lab_web3_access_wallet; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lab_web3_access_wallet ON public.lab_web3_access USING btree (wallet_id);


--
-- Name: idx_labs_acl; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_labs_acl ON public.labs USING gin (acl);


--
-- Name: idx_llm_events_conv; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_llm_events_conv ON public.llm_events USING btree (conversation_id);


--
-- Name: idx_llm_events_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_llm_events_created ON public.llm_events USING btree (created_at DESC);


--
-- Name: idx_llm_events_lab; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_llm_events_lab ON public.llm_events USING btree (lab_id);


--
-- Name: idx_llm_events_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_llm_events_model ON public.llm_events USING btree (model_identifier);


--
-- Name: idx_llm_events_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_llm_events_request_id ON public.llm_events USING btree (request_id);


--
-- Name: idx_llm_events_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_llm_events_type ON public.llm_events USING btree (event_type);


--
-- Name: idx_messages_conversation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_messages_conversation ON public.messages USING btree (conversation_id, created_at);


--
-- Name: idx_module_steps_module; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_module_steps_module ON public.module_steps USING btree (module_id);


--
-- Name: idx_module_tasks_module; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_module_tasks_module ON public.module_tasks USING btree (module_id);


--
-- Name: idx_portfolio_snapshots_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolio_snapshots_ts ON public.portfolio_snapshots USING btree (ts DESC);


--
-- Name: idx_portfolio_snapshots_wallet; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolio_snapshots_wallet ON public.portfolio_snapshots USING btree (wallet_id, ts DESC);


--
-- Name: idx_project_modules_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_project_modules_project ON public.project_modules USING btree (project_id);


--
-- Name: idx_projects_acl; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_projects_acl ON public.projects USING gin (acl);


--
-- Name: idx_rag_collections_acl; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rag_collections_acl ON public.rag_collections USING gin (acl);


--
-- Name: idx_rag_documents_collection; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rag_documents_collection ON public.rag_documents USING btree (collection_id, created_at DESC);


--
-- Name: idx_request_log_ip; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_request_log_ip ON public.request_log USING btree (ip, "timestamp" DESC);


--
-- Name: idx_request_log_module; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_request_log_module ON public.request_log USING btree (module, "timestamp" DESC);


--
-- Name: idx_request_log_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_request_log_severity ON public.request_log USING btree (severity, "timestamp" DESC);


--
-- Name: idx_request_log_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_request_log_status ON public.request_log USING btree (status, "timestamp" DESC);


--
-- Name: idx_request_log_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_request_log_timestamp ON public.request_log USING btree ("timestamp" DESC);


--
-- Name: idx_request_log_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_request_log_user ON public.request_log USING btree (user_email, "timestamp" DESC);


--
-- Name: idx_resources_acl; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_resources_acl ON public.resources USING gin (acl);


--
-- Name: idx_servers_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_servers_status ON public.servers USING btree (status);


--
-- Name: idx_tasks_conversation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_conversation ON public.orchestrator_tasks USING btree (conversation_id);


--
-- Name: idx_tasks_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_status ON public.orchestrator_tasks USING btree (status, priority DESC, queued_at);


--
-- Name: idx_trade_history_lab; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_history_lab ON public.trade_history USING btree (lab_id);


--
-- Name: idx_trade_history_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_history_ts ON public.trade_history USING btree ("timestamp" DESC);


--
-- Name: idx_trade_history_wallet; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_history_wallet ON public.trade_history USING btree (wallet_address);


--
-- Name: idx_trading_positions_chain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_positions_chain ON public.trading_positions USING btree (chain);


--
-- Name: idx_trading_positions_lab; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_positions_lab ON public.trading_positions USING btree (lab_id);


--
-- Name: idx_trading_positions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_positions_status ON public.trading_positions USING btree (status);


--
-- Name: idx_trading_positions_wallet; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_positions_wallet ON public.trading_positions USING btree (wallet_address);


--
-- Name: idx_trial_requests_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trial_requests_status ON public.trial_requests USING btree (status);


--
-- Name: idx_wallets_acl; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wallets_acl ON public.wallets USING gin (acl);


--
-- Name: idx_workflow_executions_server; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflow_executions_server ON public.workflow_executions USING btree (server_id);


--
-- Name: idx_workflow_executions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflow_executions_status ON public.workflow_executions USING btree (status);


--
-- Name: ix_llm_events_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_events_request_id ON public.llm_events USING btree (request_id);


--
-- Name: ai_agents ai_agents_model_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_agents
    ADD CONSTRAINT ai_agents_model_id_fkey FOREIGN KEY (model_id) REFERENCES public.ai_models(id) ON DELETE SET NULL;


--
-- Name: ai_models ai_models_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_models
    ADD CONSTRAINT ai_models_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.ai_providers(id) ON DELETE CASCADE;


--
-- Name: ai_providers ai_providers_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_providers
    ADD CONSTRAINT ai_providers_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE SET NULL;


--
-- Name: command_history command_history_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.command_history
    ADD CONSTRAINT command_history_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id);


--
-- Name: conversations conversations_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.ai_agents(id) ON DELETE SET NULL;


--
-- Name: execution_logs execution_logs_execution_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.execution_logs
    ADD CONSTRAINT execution_logs_execution_id_fkey FOREIGN KEY (execution_id) REFERENCES public.workflow_executions(id) ON DELETE CASCADE;


--
-- Name: execution_logs execution_logs_step_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.execution_logs
    ADD CONSTRAINT execution_logs_step_id_fkey FOREIGN KEY (step_id) REFERENCES public.workflow_steps(id);


--
-- Name: gpu_locks gpu_locks_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gpu_locks
    ADD CONSTRAINT gpu_locks_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- Name: gpu_locks gpu_locks_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gpu_locks
    ADD CONSTRAINT gpu_locks_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.orchestrator_tasks(id) ON DELETE CASCADE;


--
-- Name: lab_agents lab_agents_lab_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_agents
    ADD CONSTRAINT lab_agents_lab_id_fkey FOREIGN KEY (lab_id) REFERENCES public.labs(id) ON DELETE CASCADE;


--
-- Name: lab_agents lab_agents_library_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_agents
    ADD CONSTRAINT lab_agents_library_agent_id_fkey FOREIGN KEY (library_agent_id) REFERENCES public.library_agents(id) ON DELETE SET NULL;


--
-- Name: lab_agents lab_agents_model_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_agents
    ADD CONSTRAINT lab_agents_model_id_fkey FOREIGN KEY (model_id) REFERENCES public.ai_models(id) ON DELETE SET NULL;


--
-- Name: lab_agents lab_agents_prompt_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_agents
    ADD CONSTRAINT lab_agents_prompt_template_id_fkey FOREIGN KEY (prompt_template_id) REFERENCES public.prompt_templates(id) ON DELETE SET NULL;


--
-- Name: lab_agents lab_agents_tool_set_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_agents
    ADD CONSTRAINT lab_agents_tool_set_id_fkey FOREIGN KEY (tool_set_id) REFERENCES public.tool_sets(id) ON DELETE SET NULL;


--
-- Name: lab_loop_events lab_loop_events_lab_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_loop_events
    ADD CONSTRAINT lab_loop_events_lab_id_fkey FOREIGN KEY (lab_id) REFERENCES public.labs(id) ON DELETE CASCADE;


--
-- Name: lab_memories lab_memories_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_memories
    ADD CONSTRAINT lab_memories_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.lab_agents(id) ON DELETE CASCADE;


--
-- Name: lab_memories lab_memories_lab_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_memories
    ADD CONSTRAINT lab_memories_lab_id_fkey FOREIGN KEY (lab_id) REFERENCES public.labs(id) ON DELETE CASCADE;


--
-- Name: lab_messages lab_messages_lab_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_messages
    ADD CONSTRAINT lab_messages_lab_id_fkey FOREIGN KEY (lab_id) REFERENCES public.labs(id) ON DELETE CASCADE;


--
-- Name: lab_messages lab_messages_sender_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_messages
    ADD CONSTRAINT lab_messages_sender_agent_id_fkey FOREIGN KEY (sender_agent_id) REFERENCES public.lab_agents(id) ON DELETE SET NULL;


--
-- Name: lab_messages lab_messages_target_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_messages
    ADD CONSTRAINT lab_messages_target_agent_id_fkey FOREIGN KEY (target_agent_id) REFERENCES public.lab_agents(id) ON DELETE SET NULL;


--
-- Name: lab_rag_access lab_rag_access_collection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_rag_access
    ADD CONSTRAINT lab_rag_access_collection_id_fkey FOREIGN KEY (collection_id) REFERENCES public.rag_collections(id) ON DELETE CASCADE;


--
-- Name: lab_rag_access lab_rag_access_lab_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_rag_access
    ADD CONSTRAINT lab_rag_access_lab_id_fkey FOREIGN KEY (lab_id) REFERENCES public.labs(id) ON DELETE CASCADE;


--
-- Name: lab_resources lab_resources_lab_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_resources
    ADD CONSTRAINT lab_resources_lab_id_fkey FOREIGN KEY (lab_id) REFERENCES public.labs(id) ON DELETE CASCADE;


--
-- Name: lab_schedule_log lab_schedule_log_lab_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_schedule_log
    ADD CONSTRAINT lab_schedule_log_lab_id_fkey FOREIGN KEY (lab_id) REFERENCES public.labs(id) ON DELETE CASCADE;


--
-- Name: lab_server_access lab_server_access_lab_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_server_access
    ADD CONSTRAINT lab_server_access_lab_id_fkey FOREIGN KEY (lab_id) REFERENCES public.labs(id) ON DELETE CASCADE;


--
-- Name: lab_server_access lab_server_access_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_server_access
    ADD CONSTRAINT lab_server_access_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- Name: lab_tools lab_tools_lab_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_tools
    ADD CONSTRAINT lab_tools_lab_id_fkey FOREIGN KEY (lab_id) REFERENCES public.labs(id) ON DELETE CASCADE;


--
-- Name: lab_web3_access lab_web3_access_lab_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_web3_access
    ADD CONSTRAINT lab_web3_access_lab_id_fkey FOREIGN KEY (lab_id) REFERENCES public.labs(id) ON DELETE CASCADE;


--
-- Name: lab_web3_access lab_web3_access_wallet_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lab_web3_access
    ADD CONSTRAINT lab_web3_access_wallet_id_fkey FOREIGN KEY (wallet_id) REFERENCES public.wallets(id) ON DELETE CASCADE;


--
-- Name: labs labs_orchestrator_model_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.labs
    ADD CONSTRAINT labs_orchestrator_model_id_fkey FOREIGN KEY (orchestrator_model_id) REFERENCES public.ai_models(id) ON DELETE SET NULL;


--
-- Name: labs labs_orchestrator_prompt_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.labs
    ADD CONSTRAINT labs_orchestrator_prompt_template_id_fkey FOREIGN KEY (orchestrator_prompt_template_id) REFERENCES public.prompt_templates(id) ON DELETE SET NULL;


--
-- Name: labs labs_orchestrator_tool_set_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.labs
    ADD CONSTRAINT labs_orchestrator_tool_set_id_fkey FOREIGN KEY (orchestrator_tool_set_id) REFERENCES public.tool_sets(id) ON DELETE SET NULL;


--
-- Name: library_agents library_agents_model_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.library_agents
    ADD CONSTRAINT library_agents_model_id_fkey FOREIGN KEY (model_id) REFERENCES public.ai_models(id) ON DELETE SET NULL;


--
-- Name: library_agents library_agents_prompt_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.library_agents
    ADD CONSTRAINT library_agents_prompt_template_id_fkey FOREIGN KEY (prompt_template_id) REFERENCES public.prompt_templates(id) ON DELETE SET NULL;


--
-- Name: messages messages_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.ai_agents(id) ON DELETE SET NULL;


--
-- Name: messages messages_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id) ON DELETE CASCADE;


--
-- Name: module_steps module_steps_module_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.module_steps
    ADD CONSTRAINT module_steps_module_id_fkey FOREIGN KEY (module_id) REFERENCES public.project_modules(id) ON DELETE CASCADE;


--
-- Name: module_tasks module_tasks_module_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.module_tasks
    ADD CONSTRAINT module_tasks_module_id_fkey FOREIGN KEY (module_id) REFERENCES public.project_modules(id) ON DELETE CASCADE;


--
-- Name: orchestrator_settings orchestrator_settings_orchestrator_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orchestrator_settings
    ADD CONSTRAINT orchestrator_settings_orchestrator_server_id_fkey FOREIGN KEY (orchestrator_server_id) REFERENCES public.servers(id) ON DELETE SET NULL;


--
-- Name: orchestrator_tasks orchestrator_tasks_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orchestrator_tasks
    ADD CONSTRAINT orchestrator_tasks_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.ai_agents(id) ON DELETE SET NULL;


--
-- Name: orchestrator_tasks orchestrator_tasks_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orchestrator_tasks
    ADD CONSTRAINT orchestrator_tasks_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id) ON DELETE CASCADE;


--
-- Name: orchestrator_tasks orchestrator_tasks_parent_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orchestrator_tasks
    ADD CONSTRAINT orchestrator_tasks_parent_task_id_fkey FOREIGN KEY (parent_task_id) REFERENCES public.orchestrator_tasks(id) ON DELETE SET NULL;


--
-- Name: orchestrator_tasks orchestrator_tasks_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orchestrator_tasks
    ADD CONSTRAINT orchestrator_tasks_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE SET NULL;


--
-- Name: portfolio_snapshots portfolio_snapshots_wallet_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_snapshots
    ADD CONSTRAINT portfolio_snapshots_wallet_id_fkey FOREIGN KEY (wallet_id) REFERENCES public.wallets(id) ON DELETE CASCADE;


--
-- Name: project_modules project_modules_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_modules
    ADD CONSTRAINT project_modules_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: project_workflows project_workflows_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_workflows
    ADD CONSTRAINT project_workflows_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: project_workflows project_workflows_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_workflows
    ADD CONSTRAINT project_workflows_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: rag_collections rag_collections_lightrag_model_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_collections
    ADD CONSTRAINT rag_collections_lightrag_model_id_fkey FOREIGN KEY (lightrag_model_id) REFERENCES public.ai_models(id) ON DELETE SET NULL;


--
-- Name: rag_documents rag_documents_collection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_documents
    ADD CONSTRAINT rag_documents_collection_id_fkey FOREIGN KEY (collection_id) REFERENCES public.rag_collections(id) ON DELETE CASCADE;


--
-- Name: resource_projects resource_projects_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_projects
    ADD CONSTRAINT resource_projects_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: resource_projects resource_projects_resource_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_projects
    ADD CONSTRAINT resource_projects_resource_id_fkey FOREIGN KEY (resource_id) REFERENCES public.resources(id) ON DELETE CASCADE;


--
-- Name: workflow_executions workflow_executions_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_executions
    ADD CONSTRAINT workflow_executions_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id);


--
-- Name: workflow_executions workflow_executions_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_executions
    ADD CONSTRAINT workflow_executions_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id);


--
-- Name: workflow_steps workflow_steps_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_steps
    ADD CONSTRAINT workflow_steps_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: workflows workflows_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflows
    ADD CONSTRAINT workflows_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


--
--



-- ══════════════════════════════════════════════════
-- TimescaleDB conversion (optional)
-- ══════════════════════════════════════════════════
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
    PERFORM create_hypertable('public.portfolio_snapshots', 'ts', if_not_exists => TRUE);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'TimescaleDB not available — portfolio_snapshots will be a regular table';
END
$$;

-- ══════════════════════════════════════════════════
-- Singleton settings rows
-- ══════════════════════════════════════════════════
INSERT INTO public.orchestrator_settings (id) VALUES (1) ON CONFLICT DO NOTHING;
INSERT INTO public.web3_settings (id) VALUES (1) ON CONFLICT DO NOTHING;
INSERT INTO public.platform_settings (key, value)
    VALUES ('infra_access', '{"emails": []}')
    ON CONFLICT (key) DO NOTHING;
