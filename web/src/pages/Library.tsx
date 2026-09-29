import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, Music4, Plus, Search, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api, type Song, type Vocab } from "../api";
import { CoverArt } from "../components/CoverArt";
import { Badge, Button, Empty, Spinner } from "../components/ui";
import { lang } from "../i18n";
import { useLive } from "../store";

function StatusBadge({ song }: { song: Song }) {
  const { t } = useTranslation();
  const take = song.last_take;
  const live = useLive((s) => (take ? s.takes[take.id] : undefined));
  if (!take) return null;
  const status = live?.stage && !["done", "failed", "cancelled"].includes(live.stage) && take.status !== "done" ? "running" : take.status;
  if (status === "done") return <Badge tone="good">{t("render.stages.done")}</Badge>;
  if (status === "failed") return <Badge tone="bad">{t("render.stages.failed")}</Badge>;
  if (status === "running" || status === "queued") return <Badge tone="accent"><span className="size-1.5 rounded-full bg-accent animate-pulse-soft" />{t(`render.stages.${live?.stage ?? "queued"}`, live?.stage ?? "")}</Badge>;
  return <Badge>{t(`render.stages.${status}`, status)}</Badge>;
}

export function Library() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const songs = useQuery({ queryKey: ["songs"], queryFn: () => api.get<Song[]>("/api/songs") });
  const vocab = useQuery({ queryKey: ["vocab"], queryFn: () => api.get<Vocab>("/api/vocab"), staleTime: Infinity });
  const create = useMutation({
    mutationFn: async (template?: string) => {
      const s = await api.post<Song>("/api/songs", { title: "" });
      if (template) sessionStorage.setItem(`ys.template.${s.id}`, template);
      const preset = vocab.data?.presets.find((p) => p.id === vocab.data?.templates.find((x) => x.id === template)?.preset);
      if (preset) sessionStorage.setItem(`ys.fields.${s.id}`, JSON.stringify(preset.fields));
      return s;
    },
    onSuccess: (s) => { qc.invalidateQueries({ queryKey: ["songs"] }); nav(`/song/${s.id}`); },
  });
  const list = useMemo(() => (songs.data ?? []).filter((s) => !q || s.title.toLowerCase().includes(q.toLowerCase())), [songs.data, q]);
  const L = lang();
  return (
    <div className="max-w-[1320px] mx-auto px-10 py-10">
      <header className="flex items-end justify-between gap-6 mb-10">
        <div>
          <h1 className="font-display text-[56px] leading-none tracking-tight">{t("library.title")}</h1>
          <p className="text-ink-2 mt-3 max-w-xl">{t("library.subtitle")}</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="relative">
            <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("library.search")}
              className="h-10 w-60 rounded-xl bg-panel-2 border border-line pl-9 pr-3 text-sm outline-none focus:border-accent/60" />
          </label>
          <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => create.mutate(undefined)} loading={create.isPending}>
            {t("library.newSong")}
          </Button>
        </div>
      </header>

      {songs.isLoading ? <div className="grid place-items-center py-20"><Spinner className="size-6" /></div> : list.length === 0 && !q ? (
        <div className="glass rounded-3xl p-10">
          <Empty icon={<Sparkles className="size-6" />} title={t("library.empty")} hint={t("library.emptyHint")} />
          <div className="flex flex-wrap justify-center gap-3 -mt-4">
            <Button variant="outline" onClick={() => create.mutate(undefined)}>{t("library.blank")}</Button>
            {vocab.data?.templates.map((tp) => (
              <Button key={tp.id} variant="soft" onClick={() => create.mutate(tp.id)}>{tp.name[L]}</Button>
            ))}
          </div>
        </div>
      ) : (
        <>
        <div className="flex flex-wrap items-center gap-2 mb-6">
          <span className="text-[11px] uppercase tracking-[.14em] text-ink-3 mr-1">{L === "zh" ? "从模板开始" : "Start from"}</span>
          {vocab.data?.templates.map((tp) => (
            <button key={tp.id} onClick={() => create.mutate(tp.id)}
              className={`h-8 px-3 rounded-full text-[13px] border transition ${tp.instrumental ? "border-accent/40 text-accent bg-accent/10 hover:bg-accent/20" : "border-line text-ink-2 hover:text-ink hover:border-line-2"}`}>
              {tp.name[L]}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-6">
          {list.map((s, i) => (
            <motion.button key={s.id} onClick={() => nav(`/song/${s.id}`)} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(i * 0.03, 0.3) }}
              className="group text-left rounded-2xl overflow-hidden glass hover:border-line-2 transition-all hover:-translate-y-0.5 hover:shadow-[0_20px_50px_-20px_rgba(0,0,0,.6)]">
              <div className="aspect-square relative overflow-hidden">
                <CoverArt seed={s.cover_seed || 1} title={s.title} className="w-full h-full transition-transform duration-700 group-hover:scale-[1.04]" />
                <div className="absolute inset-x-0 bottom-0 p-4 bg-gradient-to-t from-black/70 via-black/20 to-transparent">
                  <div className="font-display text-[26px] leading-tight text-white drop-shadow line-clamp-2">{s.title || t("library.untitled")}</div>
                </div>
                <div className="absolute top-3 right-3"><StatusBadge song={s} /></div>
              </div>
              <div className="p-4 flex flex-col gap-2">
                <div className="text-[12px] text-ink-2 line-clamp-2 min-h-8">{s.draft?.style ?? "—"}</div>
                <div className="flex items-center gap-3 text-[11px] text-ink-3">
                  <span className="flex items-center gap-1"><Clock className="size-3" />{new Date(s.updated * 1000).toLocaleDateString()}</span>
                  {s.draft?.bpm ? <span className="flex items-center gap-1"><Music4 className="size-3" />{Math.round(s.draft.bpm)} BPM</span> : null}
                </div>
              </div>
            </motion.button>
          ))}
        </div>
        </>
      )}
    </div>
  );
}
