export type Severity = "error" | "warn" | "hint";
export type Goal = "lyrics" | "variety" | "harmony" | "singing" | "audio" | "workflow";
export type Bi = { en: string; zh: string };

export interface Fix { label: Bi; lines?: Record<string, string | null>; doc?: string }
export interface Issue {
  rule: string; catalog: string; severity: Severity; goal: Goal; message: Bi;
  line?: number; start?: number; end?: number; section?: number; time?: [number, number];
  fix?: Fix; data?: Record<string, unknown>;
}
export interface StyleFields {
  language: string; genres: string[]; moods: string[]; gender: string; timbre: string[]; delivery: string;
  instruments: string[]; production: string[]; harmony: string; phrasing: string[]; bpm: number | null;
  key: string | null; extra: string; override: string | null;
}
export interface CheckResult {
  issues: Issue[]; style_issues: Issue[]; sung: string; style: string; language: string; blocking: number;
  bpm: number; vocal_bpm: number; genre: { edm: boolean; half_time: boolean; genres: string[] };
  estimate: { seconds: number; bars: number; semantic_tokens: number; sections: { tag: string; seconds: number }[] };
  counts: Record<string, number>;
  sections: { tag: string | null; raw_tag: string | null; tag_line: number | null; lines: number[]; syllables: number[] }[];
  mapping: { display_index: number; sung: string; display: string; changes: string[] }[];
  fields: StyleFields; instrumental?: boolean;
}
export interface VocabItem { en: string; zh: string; cat?: string; bpm?: number; half_time?: boolean }
export interface Vocab {
  genres: VocabItem[]; moods: VocabItem[]; timbres: VocabItem[]; instruments: VocabItem[]; production: VocabItem[];
  phrasing: VocabItem[]; deliveries: { id: string; en: string; zh: string }[]; keys: string[];
  presets: { id: string; name: Bi; fields: Partial<StyleFields>; instrumental?: boolean }[];
  templates: { id: string; name: Bi; sections: string[]; notes?: Record<string, Bi>; instrumental?: boolean; preset?: string }[];
  genre_categories: { id: string; en: string; zh: string }[];
}
export interface Scorecard { lyrics: number; variety: number; harmony: number; singing: number }
export interface PlanAnalysis {
  ok: boolean; error?: string; bpm: number; key: string; predicted_seconds: number; lyric_seconds: number; bars: number;
  sections: { index: number; name: string; tag: string | null; bars: number; start: number; end: number; vocal_notes: number }[];
  scorecard: Scorecard; gates: Record<string, boolean>; passed: boolean; score: number; issues: Issue[];
  harmony: { unique: number; vocabulary: string[]; richness: number; whole_song_loop: boolean; extension_ratio: number };
  range: { available: boolean; low: number; high: number; comfort: [number, number]; suggest_transpose: number; center: number };
  alignment: { lines: { line: number; syllables: number; notes: number; ratio: number; start: number; end: number }[];
               missing_lyric: number[]; extra_abc: number[] };
  line_risks: { line: number; a15: boolean; a16: boolean; start: number; end: number }[];
}
export interface Plan {
  id: string; take_id: string; parent_id: string | null; idx: number; source: string; seed: number; abc: string;
  dir: string | null; truncated: number; n_tokens: number; analysis: PlanAnalysis | null; score: number | null;
  passed: number; edit_ops: unknown[]; created: number;
}
export interface Candidate {
  id: string; take_id: string; plan_id: string; idx: number; sem_seed: number; noise_seed: number; n_tokens: number;
  stage: "semantic" | "rejected" | "audition" | "final"; gates: Record<string, boolean>; score: number | null;
  reject_reason: string | null; files: Record<string, string>;
  metrics: { length?: { seconds: number; predicted: number; ratio: number; verdict: string }; loop?: { start_s: number; length_s: number } | null;
             audio?: Record<string, unknown> & { lufs: number; abrupt_ending: boolean; seconds: number };
             events?: { a15: { line: number; start: number; end: number; signals: string[] }[]; a16: { line: number; start: number; end: number }[] };
             card?: Scorecard; master?: { input_lufs: number; output_lufs: number; true_peak_db: number } };
  asr: null | { available: boolean; coverage: number; lines: { occurrence: number; line: number; coverage: number; start: number | null; end: number | null }[];
                skipped: number[]; repeated: { line: number; start: number; end: number }[] };
  created: number;
}
export interface Draft {
  id: string; song_id: string; lyrics: string; style_fields: StyleFields; style: string; sung: string; bpm: number;
  vocal_bpm: number; language: string; gender: string; created: number;
  mapping: CheckResult["mapping"];
  lint: { issues: Issue[]; style_issues: Issue[]; blocking: number; estimate: CheckResult["estimate"] };
}
export interface Take {
  id: string; song_id: string; draft_id: string; preset: string; status: string; stage: string; created: number;
  finished: number | null; chosen_plan: string | null; chosen_candidate: string | null;
  error: { message: string; type: string; code?: string } | null;
  progress: { stage: string; detail: string; done: number | null; total: number | null; eta: number | null; rate?: number };
  summary: { exports?: Record<string, unknown>; candidate_id?: string };
  plans?: Plan[]; candidates?: Candidate[]; draft?: Draft; jobs?: Job[];
}
export interface Job { id: string; take_id: string; kind: string; state: string; created: number; error?: { message: string } | null }
export interface Song {
  id: string; title: string; created: number; updated: number; archived: number; cover_seed: number;
  draft?: Draft | null; takes?: Take[];
  last_take?: Take | null;
}
export interface EngineInfo {
  status: string; detail: string; loaded: boolean; alive: boolean; restarts: number;
  caps: { fake?: boolean; versions?: Record<string, string | null> } & Record<string, unknown>;
  profile: Record<string, unknown> | null; heartbeat: { rss?: number };
}
export interface Settings {
  engine: { mode: string; mlx_yue_dir: string; python: string; model_dir: string; vae_dir: string; converted_dir: string;
            precision: string; memory_budget_gib: number | null };
  asr: { enabled: boolean; provider: string; model: string; passes: number };
  quality: { preset: string; audition_steps: number; final_steps: number };
  mastering: { enabled: boolean; lufs: number; true_peak: number };
  ui: { language: string; theme: string };
  server: { lan: boolean; token: string };
  calibration: Record<string, number | null>;
}

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === "string" ? detail : (detail as { message?: string })?.message ?? `HTTP ${status}`);
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method, headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try { detail = (await res.json()).detail; } catch { /* not json */ }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(url: string) => request<T>("GET", url),
  post: <T>(url: string, body: unknown = {}) => request<T>("POST", url, body),
  put: <T>(url: string, body: unknown) => request<T>("PUT", url, body),
  patch: <T>(url: string, body: unknown) => request<T>("PATCH", url, body),
  del: <T>(url: string) => request<T>("DELETE", url),
};
