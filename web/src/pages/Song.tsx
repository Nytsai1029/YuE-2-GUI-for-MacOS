import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, AudioLines, ChevronDown, FileMusic, PenLine, Play, Square } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError, type CheckResult, type Song, type StyleFields, type Take, type Vocab } from "../api";
import { CoverArt } from "../components/CoverArt";
import { DEFAULT_FIELDS } from "../components/StyleBuilder";
import { Button, cx, fmtEta, Modal, Segmented, Spinner } from "../components/ui";
import { lang } from "../i18n";
import { useLive } from "../store";
import { PlanTab } from "./PlanTab";
import { ReviewTab } from "./ReviewTab";
import { WriteTab } from "./WriteTab";

type Tab = "write" | "plan" | "review";
const ACTIVE = new Set(["queued", "running"]);

function templateText(v: Vocab | undefined, id: string | null) {
  const tpl = v?.templates.find((x) => x.id === id);
  if (!tpl) return "";
  return tpl.sections.map((s) => `[${s}]\n${["Intro", "Interlude", "Outro"].includes(s) ? "" : "\n"}`).join("\n").replace(/\n{3,}/g, "\n\n");
}

function useDebounced<T>(value: T, ms: number) {
  const [v, setV] = useState(value);
  useEffect(() => { const id = setTimeout(() => setV(value), ms); return () => clearTimeout(id); }, [value, ms]);
  return v;
}

export function useWork(song: Song | undefined, vocab: Vocab | undefined) {
  const key = song ? `ys.work.${song.id}` : "";
  const [state, setState] = useState<{ lyrics: string; fields: StyleFields; ready: boolean }>({ lyrics: "", fields: DEFAULT_FIELDS, ready: false });
  useEffect(() => {
    if (!song || state.ready || !vocab) return;
    let saved: { lyrics: string; fields: StyleFields; t: number } | null = null;
    try { saved = JSON.parse(localStorage.getItem(key) || "null"); } catch { saved = null; }
    const draftT = song.draft?.created ?? 0;
    if (saved && saved.t / 1000 >= draftT) setState({ lyrics: saved.lyrics, fields: { ...DEFAULT_FIELDS, ...saved.fields }, ready: true });
    else if (song.draft) setState({ lyrics: song.draft.lyrics, fields: { ...DEFAULT_FIELDS, ...song.draft.style_fields }, ready: true });
    else {
      let preset: Partial<StyleFields> = {};
      try { preset = JSON.parse(sessionStorage.getItem(`ys.fields.${song.id}`) || "{}"); } catch { preset = {}; }
      setState({ lyrics: templateText(vocab, sessionStorage.getItem(`ys.template.${song.id}`)), fields: { ...DEFAULT_FIELDS, ...preset }, ready: true });
    }
  }, [song, vocab, key, state.ready]);
  useEffect(() => {
    if (!state.ready || !key) return;
    const id = setTimeout(() => { try { localStorage.setItem(key, JSON.stringify({ lyrics: state.lyrics, fields: state.fields, t: Date.now() })); } catch { /* full */ } }, 400);
    return () => clearTimeout(id);
  }, [state, key]);
  return {
    ...state,
    setLyrics: (lyrics: string) => setState((s) => ({ ...s, lyrics })),
    setFields: (fields: StyleFields) => setState((s) => ({ ...s, fields })),
  };
}

export function ProgressStrip({ take, onCancel }: { take: Take; onCancel: () => void }) {
  const { t } = useTranslation();
  const live = useLive((s) => s.takes[take.id]);
  const p = live ?? { ...take.progress, stage: take.stage };
  const stage = p?.stage ?? take.stage;
  const pct = p?.total ? Math.min(100, ((p.done ?? 0) / p.total) * 100) : null;
  const steps = ["plan", "semantic", "render", "check", "finalize", "export"];
  const at = steps.indexOf(stage);
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }}
      className="glass rounded-2xl px-5 py-3.5 flex items-center gap-5 shadow-[0_20px_60px_-20px_rgba(0,0,0,.7)]">
      <div className="flex items-center gap-1.5">
        {steps.map((s, i) => (
          <div key={s} className={cx("h-1.5 rounded-full transition-all", i < at ? "w-6 bg-accent/70" : i === at ? "w-10 grad-bg" : "w-6 bg-line-2")} />
        ))}
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium truncate">{p?.detail || t(`render.stages.${stage}`, stage)}</div>
        <div className="text-[11px] text-ink-3 flex gap-3">
          <span>{t(`render.stages.${stage}`, stage)}</span>
          {p?.eta ? <span>{t("render.eta", { t: fmtEta(p.eta) })}</span> : null}
          {p?.rate ? <span>{t("render.tokens", { n: Math.round(p.rate) })}</span> : null}
        </div>
        {pct != null && (
          <div className="mt-1.5 h-1 rounded-full bg-line overflow-hidden">
            <motion.div className="h-full grad-bg" animate={{ width: `${pct}%` }} transition={{ ease: "linear" }} />
          </div>
        )}
      </div>
      <Button size="sm" variant="ghost" icon={<Square className="size-3.5" />} onClick={onCancel}>{t("render.cancel")}</Button>
    </motion.div>
  );
}

export function SongPage() {
  const { id = "", tab = "write" } = useParams();
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const { t } = useTranslation();
  const L = lang();
  const qc = useQueryClient();
  const song = useQuery({ queryKey: ["song", id], queryFn: () => api.get<Song>(`/api/songs/${id}`) });
  const vocab = useQuery({ queryKey: ["vocab"], queryFn: () => api.get<Vocab>("/api/vocab"), staleTime: Infinity });
  const work = useWork(song.data, vocab.data);
  const [title, setTitle] = useState("");
  const [preset, setPreset] = useState<"draft" | "standard" | "best">(() => (localStorage.getItem("ys.preset") as "standard") || "standard");
  const [blocked, setBlocked] = useState<string | null>(null);
  useEffect(() => { if (song.data) setTitle(song.data.title); }, [song.data]);

  const dLyrics = useDebounced(work.lyrics, 280);
  const dFields = useDebounced(work.fields, 280);
  const check = useQuery({
    queryKey: ["check", dLyrics, dFields], enabled: work.ready,
    queryFn: () => api.post<CheckResult>("/api/check", { lyrics: dLyrics, fields: dFields }), placeholderData: (prev) => prev,
  });

  const takes = song.data?.takes ?? [];
  const takeId = params.get("take") ?? takes[0]?.id ?? null;
  const take = useQuery({ queryKey: ["take", takeId], enabled: !!takeId, queryFn: () => api.get<Take>(`/api/takes/${takeId}`),
    refetchInterval: (q) => (q.state.data && ACTIVE.has(q.state.data.status) ? 4000 : false) });
  const live = useLive((s) => (takeId ? s.takes[takeId] : undefined));
  const liveDone = !!live && ["done", "failed", "cancelled", "interrupted"].includes(live.stage);
  const running = !!take.data && ACTIVE.has(take.data.status) && !liveDone;

  const rename = useMutation({ mutationFn: (v: string) => api.patch(`/api/songs/${id}`, { title: v }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["songs"] }) });
  const generate = useMutation({
    mutationFn: (allowErrors: boolean) => api.post<{ take: Take }>(`/api/songs/${id}/takes`, {
      lyrics: work.lyrics, fields: work.fields, preset, allow_errors: allowErrors }),
    onSuccess: (r) => {
      setBlocked(null);
      qc.invalidateQueries({ queryKey: ["song", id] });
      setParams({ take: r.take.id });
      nav(`/song/${id}/plan?take=${r.take.id}`);
    },
    onError: (e) => { if (e instanceof ApiError && e.status === 422) setBlocked((e.detail as { message?: string })?.message ?? t("song.blocked")); },
  });
  const cancel = useMutation({
    mutationFn: async () => {
      const job = take.data?.jobs?.find((j) => ["queued", "running"].includes(j.state));
      if (job) await api.post(`/api/jobs/${job.id}/cancel`);
    },
  });

  useEffect(() => { try { localStorage.setItem("ys.preset", preset); } catch { /* ignore */ } }, [preset]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); if (!running) generate.mutate(false); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [generate, running]);

  const tabs = useMemo(() => [
    { id: "write" as Tab, icon: PenLine, label: t("song.write") },
    { id: "plan" as Tab, icon: FileMusic, label: t("song.plan"), badge: take.data?.plans?.length },
    { id: "review" as Tab, icon: AudioLines, label: t("song.review"), badge: take.data?.candidates?.filter((c) => c.stage !== "rejected").length },
  ], [t, take.data]);

  if (song.isLoading || !work.ready) return <div className="h-full grid place-items-center"><Spinner className="size-6" /></div>;
  if (!song.data) return <div className="p-10">Not found</div>;
  const errors = (check.data?.blocking ?? 0);

  return (
    <div className="h-full flex flex-col">
      <header className="px-8 pt-6 pb-4 flex items-center gap-5 border-b border-line bg-bg/40 backdrop-blur-xl sticky top-0 z-20">
        <Link to="/" className="text-ink-3 hover:text-ink"><ArrowLeft className="size-5" /></Link>
        <div className="size-12 rounded-xl overflow-hidden shrink-0 shadow-lg"><CoverArt seed={song.data.cover_seed || 1} className="w-full h-full" /></div>
        <input value={title} onChange={(e) => setTitle(e.target.value)} onBlur={() => title !== song.data!.title && rename.mutate(title)}
          placeholder={t("library.untitled")}
          className="font-display text-[34px] leading-none bg-transparent outline-none min-w-0 flex-1 placeholder:text-ink-3" />
        <nav className="flex items-center gap-1 rounded-xl bg-panel-2 border border-line p-1">
          {tabs.map((x) => (
            <button key={x.id} onClick={() => nav(`/song/${id}/${x.id}${takeId ? `?take=${takeId}` : ""}`)}
              className={cx("relative h-9 px-4 rounded-lg text-[13px] flex items-center gap-2 transition-colors", tab === x.id ? "text-ink" : "text-ink-3 hover:text-ink-2")}>
              {tab === x.id && <motion.span layoutId="songtab" className="absolute inset-0 rounded-lg bg-bg-2 border border-line-2 -z-0" transition={{ type: "spring", stiffness: 500, damping: 40 }} />}
              <x.icon className="size-4 relative" /><span className="relative">{x.label}</span>
              {x.badge ? <span className="relative text-[10px] rounded-full bg-line-2 px-1.5">{x.badge}</span> : null}
            </button>
          ))}
        </nav>
        <div className="flex items-center gap-3">
          <Segmented value={preset} onChange={setPreset} size="sm" options={(["draft", "standard", "best"] as const).map((p) => ({
            value: p, label: t(`song.preset.${p}`), hint: t(`song.presetHint.${p}`) }))} />
          <Button variant="primary" size="md" icon={running ? <Spinner className="text-white" /> : <Play className="size-4 fill-current" />}
            onClick={() => generate.mutate(false)} disabled={running} loading={generate.isPending}>
            {running ? t("song.generating") : t("song.generate")}
            {errors > 0 && !running ? <span className="ml-1 rounded-full bg-white/25 px-1.5 text-[11px]">{errors}</span> : null}
          </Button>
        </div>
      </header>

      {takes.length > 1 && tab !== "write" && (
        <div className="px-8 pt-3 flex items-center gap-2 text-[12px] text-ink-3">
          <ChevronDown className="size-3.5" />
          <select value={takeId ?? ""} onChange={(e) => setParams({ take: e.target.value })}
            className="bg-transparent outline-none text-ink-2 hover:text-ink">
            {takes.map((tk, i) => (
              <option key={tk.id} value={tk.id}>
                #{takes.length - i} · {t(`song.preset.${tk.preset}`, tk.preset)} · {new Date(tk.created * 1000).toLocaleString()} · {t(`render.stages.${tk.status}`, tk.status)}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="flex-1 min-h-0">
        {tab === "write" && <WriteTab work={work} check={check.data} vocab={vocab.data} checking={check.isFetching} />}
        {tab === "plan" && <PlanTab take={take.data} loading={take.isLoading} onReview={() => nav(`/song/${id}/review?take=${takeId}`)} />}
        {tab === "review" && <ReviewTab take={take.data} songTitle={song.data.title} />}
      </div>

      <div className="fixed bottom-6 left-[calc(232px+2rem)] right-8 z-30 pointer-events-none flex justify-center">
        <AnimatePresence>
          {running && take.data && (
            <div className="pointer-events-auto w-full max-w-3xl"><ProgressStrip take={take.data} onCancel={() => cancel.mutate()} /></div>
          )}
        </AnimatePresence>
      </div>

      <Modal open={!!blocked} onOpenChange={(o) => !o && setBlocked(null)} title={t("song.blocked")}>
        <p className="text-sm text-ink-2 mb-5">{blocked}</p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => { setBlocked(null); nav(`/song/${id}/write`); }}>{t("common.close")}</Button>
          <Button variant="danger" onClick={() => generate.mutate(true)}>{t("song.allowErrors")}</Button>
        </div>
      </Modal>
      <span className="hidden">{L}</span>
    </div>
  );
}
