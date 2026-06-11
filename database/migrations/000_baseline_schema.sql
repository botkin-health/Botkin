-- ============================================================================
-- Baseline-схема прод-БД Botkin (снята pg_dump --schema-only 11.06.2026).
--
-- Зачем: 5 из 15 прод-таблиц (blood_pressure_logs, audit_log и др.) создавались
-- ad-hoc и не имели DDL в репозитории — проект был невоспроизводим с нуля
-- (находка аудита 2026-06). Этот файл — полный снимок структуры: таблицы,
-- индексы, constraint'ы, RLS-политики.
--
-- Восстановление с нуля: psql -U healthvault -d healthvault -f этот_файл,
-- затем накатить миграции из database/migrations/ новее даты снимка.
-- Данные — из GFS-бэкапов (FamilyHealth/_backups_db, см. docs/BACKUP_GUIDE.md).
-- ============================================================================

--
-- PostgreSQL database dump
--

\restrict WoGnjAXNeWoEehOiX6XxUK4Ma7Q8VamgbdhTlZS6QgTAaX8aUjaQL8UJVdrlIDC

-- Dumped from database version 15.17 (Debian 15.17-1.pgdg13+1)
-- Dumped by pg_dump version 15.17 (Debian 15.17-1.pgdg13+1)

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
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS '';


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: audit_admin_access(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.audit_admin_access() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
BEGIN
  IF current_user = 'healthvault' THEN
    INSERT INTO audit_log(db_user, query_type, table_name, query_excerpt)
    VALUES (
      current_user,
      TG_OP,
      TG_TABLE_NAME,
      LEFT(current_query(), 500)
    );
  END IF;
  RETURN COALESCE(NEW, OLD);
END;
$$;


--
-- Name: update_last_active(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_last_active() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE users SET last_active = NOW() WHERE telegram_id = NEW.user_id;
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: activity_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activity_log (
    id integer NOT NULL,
    user_id bigint,
    date date NOT NULL,
    steps integer,
    active_calories double precision,
    total_calories double precision,
    bmr_calories double precision,
    distance_km double precision,
    sleep_hours double precision,
    heart_rate_avg integer,
    hrv integer,
    stress_level integer,
    source character varying(50) DEFAULT 'apple_health'::character varying,
    raw_data jsonb,
    synced_at timestamp with time zone DEFAULT now()
);


--
-- Name: activity_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.activity_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: activity_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.activity_log_id_seq OWNED BY public.activity_log.id;


--
-- Name: agent_conversations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_conversations (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    role text NOT NULL,
    content jsonb NOT NULL,
    tool_use_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    source text,
    CONSTRAINT agent_conversations_role_check CHECK ((role = ANY (ARRAY['user'::text, 'assistant'::text, 'tool_use'::text, 'tool_result'::text])))
);


--
-- Name: agent_conversations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_conversations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_conversations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_conversations_id_seq OWNED BY public.agent_conversations.id;


--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_log (
    id bigint NOT NULL,
    ts timestamp with time zone DEFAULT now() NOT NULL,
    db_user text NOT NULL,
    query_type text NOT NULL,
    table_name text,
    query_excerpt text
);


--
-- Name: audit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_log_id_seq OWNED BY public.audit_log.id;


--
-- Name: blood_pressure_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.blood_pressure_logs (
    id integer NOT NULL,
    user_id bigint NOT NULL,
    measured_at timestamp with time zone NOT NULL,
    systolic integer NOT NULL,
    diastolic integer NOT NULL,
    heart_rate integer,
    source character varying(100),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: blood_pressure_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.blood_pressure_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: blood_pressure_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.blood_pressure_logs_id_seq OWNED BY public.blood_pressure_logs.id;


--
-- Name: blood_tests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.blood_tests (
    id integer NOT NULL,
    user_id bigint,
    test_date date NOT NULL,
    test_type character varying(100),
    "values" jsonb NOT NULL,
    file_path text,
    status character varying(50) DEFAULT 'current'::character varying,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: blood_tests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.blood_tests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: blood_tests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.blood_tests_id_seq OWNED BY public.blood_tests.id;


--
-- Name: body_measurements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.body_measurements (
    id integer NOT NULL,
    user_id bigint,
    measured_at timestamp with time zone DEFAULT now(),
    date date NOT NULL,
    waist_cm double precision,
    neck_cm double precision,
    hips_cm double precision,
    chest_cm double precision,
    thigh_cm double precision,
    biceps_cm double precision,
    notes text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: body_measurements_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.body_measurements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: body_measurements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.body_measurements_id_seq OWNED BY public.body_measurements.id;


--
-- Name: daily_summaries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.daily_summaries (
    id integer NOT NULL,
    user_id bigint NOT NULL,
    date date NOT NULL,
    total_calories integer,
    total_protein numeric(6,2),
    total_fats numeric(6,2),
    total_carbs numeric(6,2),
    had_workout boolean,
    sleep_hours numeric(4,2),
    weight numeric(5,2),
    bp_systolic integer,
    bp_diastolic integer,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: daily_summaries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.daily_summaries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: daily_summaries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.daily_summaries_id_seq OWNED BY public.daily_summaries.id;


--
-- Name: llm_usage_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.llm_usage_log (
    id bigint NOT NULL,
    user_id bigint,
    purpose text NOT NULL,
    model text NOT NULL,
    input_tokens integer DEFAULT 0 NOT NULL,
    output_tokens integer DEFAULT 0 NOT NULL,
    cache_creation_tokens integer DEFAULT 0 NOT NULL,
    cache_read_tokens integer DEFAULT 0 NOT NULL,
    cost_usd numeric(10,6) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: llm_usage_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.llm_usage_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: llm_usage_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.llm_usage_log_id_seq OWNED BY public.llm_usage_log.id;


--
-- Name: nutrition_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.nutrition_log (
    id integer NOT NULL,
    user_id bigint,
    date date NOT NULL,
    meal_time time without time zone,
    meal_name character varying(255),
    items jsonb NOT NULL,
    totals jsonb NOT NULL,
    photo_paths text[],
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: nutrition_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.nutrition_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: nutrition_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.nutrition_log_id_seq OWNED BY public.nutrition_log.id;


--
-- Name: sleep_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sleep_records (
    id integer NOT NULL,
    user_id bigint NOT NULL,
    date date NOT NULL,
    sleep_start timestamp with time zone NOT NULL,
    sleep_end timestamp with time zone NOT NULL,
    duration_hours numeric(4,2),
    quality_score integer,
    deep_sleep_minutes integer,
    rem_sleep_minutes integer,
    light_sleep_minutes integer,
    awake_minutes integer,
    source character varying(100),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: sleep_records_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sleep_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sleep_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sleep_records_id_seq OWNED BY public.sleep_records.id;


--
-- Name: supplements_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.supplements_log (
    id integer NOT NULL,
    user_id bigint,
    date date NOT NULL,
    "time" time without time zone,
    supplement_name character varying(255) NOT NULL,
    dosage character varying(100),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: supplements_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.supplements_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: supplements_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.supplements_log_id_seq OWNED BY public.supplements_log.id;


--
-- Name: user_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_settings (
    user_id bigint NOT NULL,
    show_calorie_budget_bar boolean DEFAULT true NOT NULL,
    bmr_override integer,
    target_weight_kg double precision,
    target_weight_date date,
    supplement_reminders_enabled boolean DEFAULT false NOT NULL,
    supplement_reminder_time time without time zone DEFAULT '08:00:00'::time without time zone NOT NULL,
    supplements jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    calorie_goal_pct integer DEFAULT '-15'::integer NOT NULL,
    bmr_source character varying(10) DEFAULT 'auto'::character varying NOT NULL,
    activity_level character varying(20),
    activity_avg_override integer
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    telegram_id bigint NOT NULL,
    username character varying(255),
    first_name character varying(255),
    last_name character varying(255),
    email character varying(255),
    phone character varying(50),
    is_active boolean DEFAULT true,
    role character varying(50) DEFAULT 'user'::character varying,
    registered_at timestamp with time zone DEFAULT now(),
    last_active timestamp with time zone,
    timezone character varying(50) DEFAULT 'Europe/Moscow'::character varying,
    health_token character varying(255),
    garmin_email character varying(255),
    garmin_password character varying(255),
    bmr double precision,
    avg_active_calories double precision,
    target_weight_kg double precision,
    share_token character varying(64),
    birth_date date,
    height_cm smallint,
    sex character varying(10) DEFAULT 'male'::character varying,
    cohort character varying(20) DEFAULT 'external'::character varying NOT NULL,
    container_id character varying(50),
    container_port integer,
    pack_name character varying(50) DEFAULT 'generic'::character varying NOT NULL,
    jwt_secret character varying(64),
    encrypted_openai_key text,
    encrypted_anthropic_key text,
    onboarding_step character varying(30) DEFAULT 'done'::character varying,
    onboarding_data jsonb DEFAULT '{}'::jsonb,
    smoking_status character varying(20) DEFAULT NULL::character varying,
    kb_status character varying(20),
    agent_system_prompt text,
    agent_review_consent boolean DEFAULT true NOT NULL,
    CONSTRAINT ck_kb_status CHECK (((kb_status IS NULL) OR ((kb_status)::text = ANY ((ARRAY['shared'::character varying, 'private'::character varying, 'none'::character varying])::text[])))),
    CONSTRAINT users_cohort_check CHECK (((cohort)::text = ANY ((ARRAY['owner'::character varying, 'family'::character varying, 'early_user'::character varying, 'external'::character varying])::text[]))),
    CONSTRAINT users_pack_name_check CHECK (((pack_name)::text = ANY ((ARRAY['generic'::character varying, 'cardiac'::character varying, 'bariatric'::character varying, 'female-cycle'::character varying, 'respiratory_allergic'::character varying])::text[])))
);


--
-- Name: weights; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.weights (
    id integer NOT NULL,
    user_id bigint,
    measured_at timestamp with time zone NOT NULL,
    weight double precision NOT NULL,
    body_fat double precision,
    muscle_mass double precision,
    water double precision,
    bmi double precision,
    visceral_fat integer,
    bone_mass double precision,
    source character varying(50)
);


--
-- Name: weights_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.weights_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: weights_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.weights_id_seq OWNED BY public.weights.id;


--
-- Name: workouts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workouts (
    id integer NOT NULL,
    user_id bigint NOT NULL,
    date date NOT NULL,
    workout_type character varying(100),
    duration_minutes integer,
    start_time timestamp with time zone,
    end_time timestamp with time zone,
    calories_burned integer,
    source character varying(100),
    created_at timestamp with time zone DEFAULT now(),
    distance_km numeric(8,3)
);


--
-- Name: workouts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.workouts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: workouts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.workouts_id_seq OWNED BY public.workouts.id;


--
-- Name: activity_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_log ALTER COLUMN id SET DEFAULT nextval('public.activity_log_id_seq'::regclass);


--
-- Name: agent_conversations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_conversations ALTER COLUMN id SET DEFAULT nextval('public.agent_conversations_id_seq'::regclass);


--
-- Name: audit_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log ALTER COLUMN id SET DEFAULT nextval('public.audit_log_id_seq'::regclass);


--
-- Name: blood_pressure_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blood_pressure_logs ALTER COLUMN id SET DEFAULT nextval('public.blood_pressure_logs_id_seq'::regclass);


--
-- Name: blood_tests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blood_tests ALTER COLUMN id SET DEFAULT nextval('public.blood_tests_id_seq'::regclass);


--
-- Name: body_measurements id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.body_measurements ALTER COLUMN id SET DEFAULT nextval('public.body_measurements_id_seq'::regclass);


--
-- Name: daily_summaries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_summaries ALTER COLUMN id SET DEFAULT nextval('public.daily_summaries_id_seq'::regclass);


--
-- Name: llm_usage_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_usage_log ALTER COLUMN id SET DEFAULT nextval('public.llm_usage_log_id_seq'::regclass);


--
-- Name: nutrition_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nutrition_log ALTER COLUMN id SET DEFAULT nextval('public.nutrition_log_id_seq'::regclass);


--
-- Name: sleep_records id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sleep_records ALTER COLUMN id SET DEFAULT nextval('public.sleep_records_id_seq'::regclass);


--
-- Name: supplements_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supplements_log ALTER COLUMN id SET DEFAULT nextval('public.supplements_log_id_seq'::regclass);


--
-- Name: weights id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.weights ALTER COLUMN id SET DEFAULT nextval('public.weights_id_seq'::regclass);


--
-- Name: workouts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workouts ALTER COLUMN id SET DEFAULT nextval('public.workouts_id_seq'::regclass);


--
-- Name: activity_log activity_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_log
    ADD CONSTRAINT activity_log_pkey PRIMARY KEY (id);


--
-- Name: activity_log activity_log_user_id_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_log
    ADD CONSTRAINT activity_log_user_id_date_key UNIQUE (user_id, date);


--
-- Name: agent_conversations agent_conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_conversations
    ADD CONSTRAINT agent_conversations_pkey PRIMARY KEY (id);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);


--
-- Name: blood_pressure_logs blood_pressure_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blood_pressure_logs
    ADD CONSTRAINT blood_pressure_logs_pkey PRIMARY KEY (id);


--
-- Name: blood_pressure_logs blood_pressure_logs_user_id_measured_at_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blood_pressure_logs
    ADD CONSTRAINT blood_pressure_logs_user_id_measured_at_key UNIQUE (user_id, measured_at);


--
-- Name: blood_tests blood_tests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blood_tests
    ADD CONSTRAINT blood_tests_pkey PRIMARY KEY (id);


--
-- Name: body_measurements body_measurements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.body_measurements
    ADD CONSTRAINT body_measurements_pkey PRIMARY KEY (id);


--
-- Name: daily_summaries daily_summaries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_summaries
    ADD CONSTRAINT daily_summaries_pkey PRIMARY KEY (id);


--
-- Name: daily_summaries daily_summaries_user_id_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_summaries
    ADD CONSTRAINT daily_summaries_user_id_date_key UNIQUE (user_id, date);


--
-- Name: llm_usage_log llm_usage_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_usage_log
    ADD CONSTRAINT llm_usage_log_pkey PRIMARY KEY (id);


--
-- Name: nutrition_log nutrition_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nutrition_log
    ADD CONSTRAINT nutrition_log_pkey PRIMARY KEY (id);


--
-- Name: nutrition_log nutrition_log_user_id_date_meal_time_meal_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nutrition_log
    ADD CONSTRAINT nutrition_log_user_id_date_meal_time_meal_name_key UNIQUE (user_id, date, meal_time, meal_name);


--
-- Name: sleep_records sleep_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sleep_records
    ADD CONSTRAINT sleep_records_pkey PRIMARY KEY (id);


--
-- Name: supplements_log supplements_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supplements_log
    ADD CONSTRAINT supplements_log_pkey PRIMARY KEY (id);


--
-- Name: user_settings user_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_settings
    ADD CONSTRAINT user_settings_pkey PRIMARY KEY (user_id);


--
-- Name: users users_health_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_health_token_key UNIQUE (health_token);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (telegram_id);


--
-- Name: users users_share_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_share_token_key UNIQUE (share_token);


--
-- Name: weights weights_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.weights
    ADD CONSTRAINT weights_pkey PRIMARY KEY (id);


--
-- Name: weights weights_user_id_measured_at_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.weights
    ADD CONSTRAINT weights_user_id_measured_at_key UNIQUE (user_id, measured_at);


--
-- Name: workouts workouts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workouts
    ADD CONSTRAINT workouts_pkey PRIMARY KEY (id);


--
-- Name: blood_tests_user_date_type_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX blood_tests_user_date_type_unique ON public.blood_tests USING btree (user_id, test_date, test_type);


--
-- Name: idx_activity_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_activity_user_date ON public.activity_log USING btree (user_id, date);


--
-- Name: idx_agent_conv_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_conv_source ON public.agent_conversations USING btree (source) WHERE (source IS NOT NULL);


--
-- Name: idx_agent_conv_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_conv_user_created ON public.agent_conversations USING btree (user_id, created_at DESC);


--
-- Name: idx_audit_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_ts ON public.audit_log USING btree (ts DESC);


--
-- Name: idx_audit_user_table; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_user_table ON public.audit_log USING btree (db_user, table_name);


--
-- Name: idx_blood_tests_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_blood_tests_user_date ON public.blood_tests USING btree (user_id, test_date);


--
-- Name: idx_bp_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bp_user_date ON public.blood_pressure_logs USING btree (user_id, measured_at DESC);


--
-- Name: idx_llm_usage_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_llm_usage_created ON public.llm_usage_log USING btree (created_at DESC);


--
-- Name: idx_llm_usage_purpose; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_llm_usage_purpose ON public.llm_usage_log USING btree (purpose, created_at DESC);


--
-- Name: idx_llm_usage_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_llm_usage_user ON public.llm_usage_log USING btree (user_id, created_at DESC);


--
-- Name: idx_measurements_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_measurements_user_date ON public.body_measurements USING btree (user_id, measured_at);


--
-- Name: idx_nutrition_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nutrition_user_date ON public.nutrition_log USING btree (user_id, date);


--
-- Name: idx_sleep_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sleep_user_date ON public.sleep_records USING btree (user_id, date DESC);


--
-- Name: idx_summaries_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_summaries_user_date ON public.daily_summaries USING btree (user_id, date DESC);


--
-- Name: idx_supplements_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_supplements_user_date ON public.supplements_log USING btree (user_id, date);


--
-- Name: idx_weights_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_weights_user_date ON public.weights USING btree (user_id, measured_at);


--
-- Name: idx_workouts_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workouts_user_date ON public.workouts USING btree (user_id, date DESC);


--
-- Name: activity_log audit_admin; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_admin AFTER INSERT OR DELETE OR UPDATE ON public.activity_log FOR EACH ROW EXECUTE FUNCTION public.audit_admin_access();


--
-- Name: blood_pressure_logs audit_admin; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_admin AFTER INSERT OR DELETE OR UPDATE ON public.blood_pressure_logs FOR EACH ROW EXECUTE FUNCTION public.audit_admin_access();


--
-- Name: nutrition_log audit_admin; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_admin AFTER INSERT OR DELETE OR UPDATE ON public.nutrition_log FOR EACH ROW EXECUTE FUNCTION public.audit_admin_access();


--
-- Name: supplements_log audit_admin; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_admin AFTER INSERT OR DELETE OR UPDATE ON public.supplements_log FOR EACH ROW EXECUTE FUNCTION public.audit_admin_access();


--
-- Name: user_settings audit_admin; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_admin AFTER INSERT OR DELETE OR UPDATE ON public.user_settings FOR EACH ROW EXECUTE FUNCTION public.audit_admin_access();


--
-- Name: users audit_admin; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_admin AFTER INSERT OR DELETE OR UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.audit_admin_access();


--
-- Name: weights audit_admin; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_admin AFTER INSERT OR DELETE OR UPDATE ON public.weights FOR EACH ROW EXECUTE FUNCTION public.audit_admin_access();


--
-- Name: activity_log activity_log_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_log
    ADD CONSTRAINT activity_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(telegram_id) ON DELETE CASCADE;


--
-- Name: blood_pressure_logs blood_pressure_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blood_pressure_logs
    ADD CONSTRAINT blood_pressure_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(telegram_id) ON DELETE CASCADE;


--
-- Name: blood_tests blood_tests_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blood_tests
    ADD CONSTRAINT blood_tests_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(telegram_id) ON DELETE CASCADE;


--
-- Name: body_measurements body_measurements_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.body_measurements
    ADD CONSTRAINT body_measurements_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(telegram_id) ON DELETE CASCADE;


--
-- Name: daily_summaries daily_summaries_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_summaries
    ADD CONSTRAINT daily_summaries_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(telegram_id) ON DELETE CASCADE;


--
-- Name: nutrition_log nutrition_log_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nutrition_log
    ADD CONSTRAINT nutrition_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(telegram_id) ON DELETE CASCADE;


--
-- Name: sleep_records sleep_records_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sleep_records
    ADD CONSTRAINT sleep_records_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(telegram_id) ON DELETE CASCADE;


--
-- Name: supplements_log supplements_log_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supplements_log
    ADD CONSTRAINT supplements_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(telegram_id) ON DELETE CASCADE;


--
-- Name: user_settings user_settings_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_settings
    ADD CONSTRAINT user_settings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(telegram_id) ON DELETE CASCADE;


--
-- Name: weights weights_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.weights
    ADD CONSTRAINT weights_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(telegram_id) ON DELETE CASCADE;


--
-- Name: workouts workouts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workouts
    ADD CONSTRAINT workouts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(telegram_id) ON DELETE CASCADE;


--
-- Name: activity_log; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.activity_log ENABLE ROW LEVEL SECURITY;

--
-- Name: agent_conversations; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.agent_conversations ENABLE ROW LEVEL SECURITY;

--
-- Name: agent_conversations agent_conversations_self; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY agent_conversations_self ON public.agent_conversations USING (((current_setting('app.user_id'::text, true) = ''::text) OR ((current_setting('app.user_id'::text, true))::bigint = user_id)));


--
-- Name: audit_log audit_admin_only; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY audit_admin_only ON public.audit_log TO hv_app USING (false);


--
-- Name: audit_log; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;

--
-- Name: blood_pressure_logs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.blood_pressure_logs ENABLE ROW LEVEL SECURITY;

--
-- Name: nutrition_log; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.nutrition_log ENABLE ROW LEVEL SECURITY;

--
-- Name: supplements_log; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.supplements_log ENABLE ROW LEVEL SECURITY;

--
-- Name: activity_log user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.activity_log TO hv_app USING ((user_id = (NULLIF(current_setting('app.user_id'::text, true), ''::text))::bigint));


--
-- Name: blood_pressure_logs user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.blood_pressure_logs TO hv_app USING ((user_id = (NULLIF(current_setting('app.user_id'::text, true), ''::text))::bigint));


--
-- Name: nutrition_log user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.nutrition_log TO hv_app USING ((user_id = (NULLIF(current_setting('app.user_id'::text, true), ''::text))::bigint));


--
-- Name: supplements_log user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.supplements_log TO hv_app USING ((user_id = (NULLIF(current_setting('app.user_id'::text, true), ''::text))::bigint));


--
-- Name: user_settings user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.user_settings TO hv_app USING ((user_id = (NULLIF(current_setting('app.user_id'::text, true), ''::text))::bigint));


--
-- Name: weights user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.weights TO hv_app USING ((user_id = (NULLIF(current_setting('app.user_id'::text, true), ''::text))::bigint));


--
-- Name: user_settings; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.user_settings ENABLE ROW LEVEL SECURITY;

--
-- Name: weights; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.weights ENABLE ROW LEVEL SECURITY;

--
-- PostgreSQL database dump complete
--

\unrestrict WoGnjAXNeWoEehOiX6XxUK4Ma7Q8VamgbdhTlZS6QgTAaX8aUjaQL8UJVdrlIDC
