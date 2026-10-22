// Mirrors apps/api/app/serializers.py and the dict responses in apps/api/app/routers/*.py.

export type Category = "brief" | "thinking" | "room" | "playbook" | "decisions" | "deep_dive";
export type Region = "global" | "us" | "eu" | "uk" | "india" | "mena" | "apac" | "africa" | "latam";
export type Stage = "research" | "write" | "edit" | "seo" | "qa";
export type Role = "owner" | "editor" | "reviewer";
export type PublishTarget = "export" | "ten_static" | "wordpress" | "webhook";
export type SourceKind = "rss" | "gdelt" | "edgar" | "ir" | "hn" | "reddit" | "manual";
export type ArticleState =
  | "queued"
  | "researching"
  | "drafting"
  | "editing"
  | "seo"
  | "qa"
  | "in_review"
  | "approved"
  | "scheduled"
  | "publishing"
  | "published"
  | "archived"
  | "needs_sources"
  | "failed";
export type JobStatus = "queued" | "running" | "done" | "failed" | "dead";
export type HealthStatus = "ok" | "degraded" | "down" | "stale" | "unknown";

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
}

export interface TenantInfo {
  id: string;
  slug: string;
  name: string;
  domain: string | null;
  timezone: string;
  site_url: string | null;
}

export interface Me {
  user: User;
  tenant: TenantInfo;
  csrf_token: string | null;
  provider: string;
}

export interface Job {
  id: string;
  type: string;
  status: JobStatus;
  article_id: string | null;
  priority: number;
  attempts: number;
  max_attempts: number;
  available_at: string | null;
  locked_at: string | null;
  locked_by: string | null;
  last_error: string | null;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  article_title?: string | null;
}

export interface JobEvent {
  id: number;
  job_id: string | null;
  article_id: string | null;
  level: "info" | "warn" | "error" | string;
  message: string;
  data: Record<string, unknown> | null;
  created_at: string | null;
}

export interface Source {
  id: string;
  kind: SourceKind;
  name: string;
  url: string;
  weight: number;
  region: Region | null;
  active: boolean;
  last_fetched_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  last_item_count: number | null;
  last_latency_ms: number | null;
  items_7d: number | null;
  created_at: string | null;
}

export interface Entity {
  name: string;
  type: "company" | "person" | "country" | "sector" | string;
  prominence?: number;
  watchlist?: boolean;
}

export interface FeedItem {
  id: string;
  title: string;
  url: string;
  canonical_url: string;
  publisher: string | null;
  summary: string | null;
  published_at: string | null;
  fetched_at: string | null;
  source: { id: string; name: string; kind: SourceKind } | null;
  lang: string | null;
  entities: Entity[];
  region: Region | null;
  score: number;
  score_breakdown: Record<string, number | string[]>;
  suggested_category: Category | null;
  category_reason: string | null;
  why_it_matters: string | null;
  dedupe_cluster_id: string | null;
  is_cluster_head: boolean;
  cluster_size: number | null;
  status: "new" | "triaged" | "promoted" | "ignored" | "duplicate";
  ignored_reason: string | null;
  topic_id: string | null;
  article_id: string | null;
  similarity?: number;
}

export interface FeedList extends Paginated<FeedItem> {
  last_fetched_at: string | null;
  stale: boolean;
}

export interface FeedDetail {
  item: FeedItem;
  cluster: FeedItem[];
  similar: FeedItem[];
  topic: Topic | null;
  article_id: string | null;
}

export interface Topic {
  id: string;
  feed_item_id: string | null;
  category: Category;
  title: string;
  angle: string | null;
  region: Region | null;
  notes: string | null;
  links: string[];
  status: string;
  created_at: string | null;
}

export interface ArticleSummary {
  id: string;
  title: string;
  category: Category;
  category_label: string;
  state: ArticleState;
  slug: string | null;
  quality_score: number | null;
  revision_count: number;
  last_error: string | null;
  published_url: string | null;
  topic: { id: string; title: string; angle: string | null; region: Region | null; feed_item_id: string | null } | null;
  active_job: { id: string; type: string; status: JobStatus } | null;
  created_at: string | null;
  updated_at: string | null;
  qa_verdict?: "pass" | "revise" | "block" | null;
  qa_overall?: number | null;
}

export interface Section {
  key: string;
  heading: string;
  paragraphs: string[];
  bullets: string[];
  pull_quote?: string | null;
  facts_used?: number[];
}

export interface ArticleBody {
  title: string;
  dek: string;
  category: Category;
  sections: Section[];
  takeaway: string;
  sources_used: string[];
  word_count?: number;
}

export interface Readability {
  flesch: number;
  grade: number;
  avg_sentence_len: number;
  max_sentence_len: number;
  sentences: number;
  words: number;
}

export interface Stats {
  word_count: number;
  target_min: number;
  target_max: number;
  band_min: number;
  band_max: number;
  in_band: boolean;
  readability: Readability;
  banned_hits: { phrase: string; count: number }[];
  sections_present: string[];
  sections_missing: string[];
}

export interface QaIssue {
  severity: "critical" | "major" | "minor";
  code: string;
  message: string;
  location: string;
}

export interface QaGate {
  gate: string;
  passed: boolean;
  blocking: boolean;
  detail: string;
}

export interface QaReport {
  verdict: "pass" | "revise" | "block";
  block_reason: string | null;
  scores: Record<"factuality" | "structure" | "executive_value" | "originality" | "voice" | "readability", number>;
  overall: number;
  gates: QaGate[];
  issues: QaIssue[];
  exec_questions_answered: string[];
  exec_questions: Record<string, string>;
  summary: string;
  revise_stage: Stage | null;
  revision_instruction: string | null;
  rubric_source: "model" | "deterministic";
  created_at: string;
  stale_seo?: boolean;
}

export interface InternalLink {
  url: string;
  title: string | null;
  anchor: string;
  similarity?: number;
  valid: boolean;
  status_code: number | null;
}

export interface SeoIssue {
  field: string;
  severity: "critical" | "major" | "minor";
  message: string;
}

export interface SeoPayload {
  title_tag: string;
  meta_description: string;
  slug: string;
  canonical_url: string;
  h1: string;
  primary_keyword: string;
  secondary_keywords: string[];
  keyword_candidates?: string[];
  autosuggest?: string[];
  search_intent: string;
  internal_links: InternalLink[];
  external_links: { url: string; title: string | null; publisher: string | null }[];
  og: Record<string, string>;
  twitter: Record<string, string>;
  json_ld: unknown;
  readability?: Readability;
  generated_at?: string;
  overrides?: string[];
  inventory_size?: number;
  issues: SeoIssue[];
  score: number;
  fields_complete: number;
  fields_total: number;
}

export interface EditorReport {
  change_log: string[];
  format_report: {
    violations: { code: string; message: string }[];
    warnings: { code: string; message: string }[];
    h1_count: number;
    sections: number;
    required_sections: number;
    missing_sections: string[];
    structural_ok: boolean;
    new_numbers?: string[];
    model_sections_rejected?: number;
  };
}

export interface VersionPayload {
  article?: ArticleBody;
  seo?: SeoPayload | null;
  qa?: QaReport | null;
  editor?: EditorReport | null;
  stats?: Stats | null;
  sources_meta?: { url: string; title: string | null; publisher: string | null }[];
}

export interface Version {
  id: string;
  stage: string;
  prompt_version: string | null;
  model_run_id: string | null;
  note: string | null;
  created_by: string | null;
  created_at: string | null;
  word_count: number | null;
  payload?: VersionPayload;
}

export interface KeyFact {
  id: number;
  claim: string;
  source_index: number;
  source_url: string;
  source_name: string | null;
  published_at: string | null;
  confidence: "high" | "medium" | "low" | "needs_verification";
}

export interface ResearchSource {
  index: number;
  url: string;
  title: string | null;
  publisher: string | null;
  published_at: string | null;
  fetched_at: string | null;
  word_count: number;
  injection_flags: string[];
  origin?: string | null;
}

export interface ResearchPack {
  id: string;
  status: "ok" | "insufficient_evidence";
  source_count: number;
  created_at: string | null;
  payload: {
    summary: string;
    key_facts: KeyFact[];
    numbers: { value: string; unit: string; context: string; source_index: number; source_url: string; verified: boolean }[];
    context?: string;
    counterpoints?: string[];
    open_questions?: string[];
    sources: ResearchSource[];
    skipped?: { url: string; reason: string }[];
    coverage: { source_count: number; independent_publishers: number; has_primary_source: boolean };
    warnings?: string[];
    status: string;
    reason?: string;
  };
}

export interface Publication {
  id: string;
  article_id: string;
  article: { id: string; title: string; category: Category; slug: string | null; state: ArticleState } | null;
  version_id: string | null;
  target: PublishTarget;
  status: "scheduled" | "publishing" | "published" | "failed" | "cancelled" | "rolled_back";
  scheduled_at: string | null;
  published_at: string | null;
  remote_id: string | null;
  live_url: string | null;
  idempotency_key: string;
  content_hash: string | null;
  last_error: string | null;
  has_artifact: boolean;
  warnings: string[];
  late: boolean;
  created_at: string | null;
  reason?: string;
  idempotent?: boolean;
}

export interface SocialPost {
  id: string;
  article_id: string;
  article: { id: string; title: string; category: Category; published_url: string | null; state: ArticleState } | null;
  platform: string;
  text: string;
  hook: string | null;
  cta: string | null;
  link: string | null;
  hashtags: string[];
  image_url: string | null;
  image_spec: { width?: number; height?: number; title?: string; kicker?: string; brand?: string } | null;
  status: "draft" | "draft_ready" | "approved" | "publishing" | "published" | "failed";
  remote_urn: string | null;
  published_at: string | null;
  last_error: string | null;
  char_count: number;
  issues: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface ReviewActionOut {
  id: string;
  action: "approve" | "reject" | "request_revision" | "force_review";
  reason: string | null;
  user: User | null;
  created_at: string | null;
}

export interface PlaybookSection {
  key: string;
  heading: string;
  show_heading: boolean;
}

export interface Playbook {
  key: Category;
  label: string;
  route: string;
  purpose: string;
  min_words: number;
  max_words: number;
  target_words: number;
  sections: PlaybookSection[];
  primary_sources: string;
  color: string;
}

export interface AllowedActions {
  run_stages: Stage[];
  can_run_auto: boolean;
  can_edit: boolean;
  can_approve: boolean;
  can_reject: boolean;
  can_request_revision: boolean;
  can_force_review: boolean;
  can_schedule: boolean;
  can_restore: boolean;
  busy_reason: string | null;
}

export interface ArticleDetail extends ArticleSummary {
  current_version: Version | null;
  research_pack: ResearchPack | null;
  seo: SeoPayload | null;
  qa: QaReport | null;
  editor: EditorReport | null;
  stats: Stats | null;
  playbook: Playbook;
  jobs: Job[];
  publications: Publication[];
  social_posts: SocialPost[];
  review_actions: ReviewActionOut[];
  allowed_actions: AllowedActions;
  job?: Job;
}

export interface AuditEntry {
  id: number;
  actor_type: "user" | "agent" | "system";
  actor_id: string | null;
  actor_label: string | null;
  action: string;
  entity: string;
  entity_id: string | null;
  detail: Record<string, unknown> | null;
  created_at: string | null;
  entity_label?: string | null;
}

export interface ModelHealth {
  status: HealthStatus;
  provider: string;
  base_url: string | null;
  models: string[];
  configured: string[];
  missing: string[];
  latency_ms: number | null;
  detail: string | null;
  is_mock: boolean;
}

export interface WorkerHealth {
  status: HealthStatus;
  last_seen: string | null;
  age_s?: number;
  workers: number;
  running?: Record<string, string>;
  detail?: string;
}

export interface Health {
  status: HealthStatus;
  checks: {
    database: { status: HealthStatus; latency_ms?: number; backend?: string; detail?: string };
    model?: ModelHealth;
    worker?: WorkerHealth;
    disk?: { status: HealthStatus; total_gb: number; free_gb: number; used_pct: number };
    discovery?: { status: HealthStatus; last_run_at: string | null; age_h: number | null; last_new_items: number | null; sources_ok: number | null };
  };
  version: string;
  time: string;
}

export interface QueueStats {
  queued: number;
  running: number;
  done: number;
  failed: number;
  dead: number;
  retrying: number;
  failed_24h: number;
  oldest_queued_age_s: number | null;
}

export interface AgentHealthRow {
  code: string;
  agent: string;
  label: string;
  jobs_24h: number;
  model_calls_24h: number;
  errors_24h: number;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  avg_job_ms: number | null;
  last_run_at: string | null;
  last_error: string | null;
}

export interface DashboardSummary {
  cards: {
    candidates_today: number;
    drafts_in_progress: number;
    awaiting_review: number;
    scheduled: number;
    published_7d: number;
    failed_jobs: number;
  };
  states: Record<string, number>;
  funnel: { stage: string; label: string; count: number }[];
  daily: { date: string; discovered: number; drafted: number; published: number }[];
  queue: QueueStats;
  agents: AgentHealthRow[];
  model: ModelHealth;
  worker: WorkerHealth;
  generated_at: string;
}

export interface SitePage {
  id: string;
  site: string;
  url: string;
  status_code: number | null;
  title: string | null;
  h1: string | null;
  headline: string | null;
  meta_description: string | null;
  canonical: string | null;
  og_count: number;
  has_jsonld: boolean;
  word_count: number | null;
  headings: string[];
  fetched_at: string | null;
}

export interface AuditFinding {
  id: string;
  title: string;
  severity: "critical" | "major" | "minor" | "info";
  evidence: string;
  impact: string;
  affected_count: number;
  affected_urls: string[];
  fix: string;
  source: "baseline" | "live";
}

export interface FixRow {
  url: string;
  category: Category;
  current_title: string | null;
  proposed_title: string;
  current_description: string | null;
  proposed_description: string;
  proposed_canonical: string;
  proposed_slug: string | null;
  issues: string[];
}

export interface SiteAudit {
  findings: AuditFinding[];
  summary: { pages: number; article_pages: number; with_issues: number | null };
  crawled_at: string | null;
  source: "baseline" | "live";
  note?: string;
  fix_list: FixRow[];
  fix_count: number;
}

export interface Competitor {
  key: string;
  name: string;
  site: string;
  sitemap: string | null;
  max_pages: number | null;
  last_crawled_at: string | null;
  pages: number;
  avg_word_count: number | null;
  jsonld_share: number | null;
  top_terms: { term: string; pages: number }[];
  gaps: string[];
  sample: { url: string; title: string | null; word_count: number | null }[];
}

export interface DryRun {
  target: PublishTarget;
  html: string;
  issues: string[];
  files: string[];
  live_url: string | null;
  content_hash: string;
  idempotency_key: string;
  will_update: boolean;
  existing_live_url: string | null;
  unchanged: boolean;
  preview: Record<string, unknown> | null;
}

export interface CalendarConflict {
  date: string;
  kind: "per_day" | "category";
  message: string;
  ids: string[];
}

export interface Cadence {
  per_day: number;
  slots: string[];
  weekdays_only: boolean;
  max_per_category_per_day: number;
}

export interface SocialConnection {
  configured: boolean;
  connected: boolean;
  author_urn: string | null;
  author_type: string | null;
  expires_at: string | null;
  reason: string | null;
}

export interface TenantSettings {
  brand: Record<string, string>;
  spelling: "en-US" | "en-GB";
  cadence: Cadence;
  scoring: Record<"recency" | "entity" | "signal" | "source" | "novelty", number>;
  watchlist: { companies: string[]; people: string[]; sectors: string[]; regions: string[] };
  avoid: { companies: string[]; topics: string[] };
  discovery: {
    lookback_hours: number;
    max_items: number;
    llm_enrich: boolean;
    enrich_top_k: number;
    auto_disable_after_failures: number;
    interval_minutes?: number;
    embeddings?: boolean;
  };
  research: { max_fetches: number; min_sources: number; max_facts: number };
  quality: Record<string, number>;
  models: { agents: Record<string, AgentModel> };
  publishing: { default_target: PublishTarget };
  social: { emoji: boolean; link_in_post: boolean; author_type: string };
}

export interface AgentModel {
  model?: string;
  temperature?: number;
  num_ctx?: number;
  max_tokens?: number;
}

export interface PromptListItem {
  key: string;
  version: string;
  source: "file" | "db" | "missing";
  chars: number;
}

export interface PromptVersionRow {
  id: string;
  version: string;
  body: string;
  note: string | null;
  source: "file" | "db";
  active: boolean;
  created_at: string | null;
  created_by: string | null;
}

export interface PromptDetail {
  key: string;
  active: { version: string; body: string; source: string; id: string };
  versions: PromptVersionRow[];
}

export interface PersonaView {
  persona: { key: string; version: string; body: string; source: string };
  structure: { version: string; body: string };
  lexicon: { version: string; body: string };
  banned_phrases: string[];
  style_profile: Record<string, unknown> | null;
}

export interface ModelsView {
  provider: string;
  base_url: string | null;
  reachable: boolean;
  available: string[];
  defaults: { writer: string; fast: string; embed: string; num_ctx: number; timeout_s: number; concurrency: number };
  agents: Record<string, AgentModel>;
  detail: string | null;
}

export interface ModelTest {
  ok: boolean;
  model: string;
  models: string[];
  latency_ms: number | null;
  sample: string | null;
  completion_tokens?: number | null;
  error: string | null;
}

export interface IntegrationsView {
  default_target: PublishTarget;
  targets: {
    export: { configured: boolean; label: string; always_available: boolean };
    ten_static: {
      configured: boolean;
      mode: "local" | "sftp";
      site_url: string | null;
      public_root: string | null;
      sftp_host: string | null;
      sftp_port: number | null;
      sftp_user: string | null;
      sftp_key_path: string | null;
      password_configured: boolean;
      note: string | null;
    };
    wordpress: { configured: boolean; url: string | null; user: string | null; password_configured: boolean };
    webhook: { configured: boolean; url: string | null; secret_configured: boolean };
  };
  linkedin: {
    client_id: string | null;
    client_id_set: boolean;
    client_secret_set: boolean;
    redirect_uri: string | null;
    org_urn: string | null;
    author_type: string | null;
    connected: boolean;
    author_urn: string | null;
    expires_at: string | null;
    last_refresh_error: string | null;
  };
}

export interface EvalCaseRow {
  id: string;
  category: Category;
  label: "good" | "edge" | "adversarial" | string;
  description: string;
  expected: string | null;
}

export interface EvalRun {
  id: string;
  agent: string;
  model: string;
  scores: Record<string, number | null>;
  passed: number;
  total: number;
  created_at: string | null;
  details?: Record<string, unknown>[];
}

export interface UserRow extends User {
  active: boolean;
  last_login_at: string | null;
}

export interface SearchResults {
  articles: ArticleSummary[];
  feed: FeedItem[];
  sources: Source[];
}
