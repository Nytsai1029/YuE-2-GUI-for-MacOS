import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, Download, FileAudio, FileJson, FileMusic, FileText, Flag, Gem, Repeat, Shuffle, Sparkles, Trash2, XCircle } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api, type Candidate, type Take } from "../api";
import { SECTION_COLORS } from "../components/LyricsEditor";
import { Badge, Button, Card, cx, Empty, fmtTime, GoalMeters, Modal, ScoreRing, SectionTitle, Spinner } from "../components/ui";
import { Waveform, type Band, type Marker, type WaveHandle } from "../components/Waveform";
import { lang } from "../i18n";

const ISSUE_TAGS = [
  ["A1", "Lyrics skipped"], ["A2", "Lyrics jumbled"], ["A6", "Crammed / rushed"], ["A8", "Strained range"], ["A10", "Mispronounced"],
  ["A11", "Vocals in instrumental"], ["A12", "Voice changed"], ["A13", "Gibberish words"], ["A15", "Shouted line ending"],
  ["A16", "Humming instead of words"], ["A17", "Section repeated"], ["B1", "Too repetitive"], ["B3", "Chords too simple"],
  ["B6", "Style ignored"], ["B7", "Abrupt ending"], ["C1", "Clipping / artefacts"], ["other", "Other"],
];

function TakeRow({ c, active, onClick, letter }: { c: Candidate; active: boolean; onClick: () => void; letter: string }) {
  const { t } = useTranslation();
  const passed = c.gates && Object.values(c.gates).every(Boolean);
  return (
    <button onClick={onClick} disabled={c.stage === "rejected" || c.stage === "semantic"}
      className={cx("w-full text-left rounded-2xl p-3 border flex items-center gap-3 transition-all",
        active ? "border-accent/60 bg-accent/8" : "border-line bg-panel hover:border-line-2", c.stage === "rejected" && "opacity-60")}>
      <div className={cx("size-9 rounded-xl grid place-items-center font-display text-xl", active ? "grad-bg text-white" : "bg-panel-2 text-ink-2")}>{letter}</div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 text-[13px]">
          {c.stage === "final" ? <Badge tone="good"><Gem className="size-3" />{t("review.final")}</Badge>
            : c.stage === "rejected" ? <Badge tone="bad"><XCircle className="size-3" />{t("review.rejected")}</Badge>
              : c.stage === "semantic" ? <Badge tone="accent">…</Badge> : <Badge>{t("review.audition")}</Badge>}
          {c.stage !== "rejected" && !passed && <Badge tone="warn">gates</Badge>}
        </div>
        <div className="text-[11px] text-ink-3 mt-1 truncate">
          {c.stage === "rejected" ? (c.reject_reason === "loop" ? "stuck loop detected — stopped early" : c.reject_reason) :
            `${fmtTime(c.metrics?.length?.seconds)} · ${c.metrics?.audio?.lufs?.toFixed?.(1) ?? "–"} LUFS`}
        </div>
      </div>
      {c.stage !== "rejected" && <ScoreRing value={c.score} size={38} passed={passed} />}
    </button>
  );
}

export function ReviewTab({ take, songTitle }: { take?: Take; songTitle: string }) {
  const { t } = useTranslation();
  const L = lang();
  const nav = useNavigate();
  const qc = useQueryClient();
  const wave = useRef<WaveHandle>(null);
  const cands = useMemo(() => (take?.candidates ?? []).slice().sort((a, b) => a.created - b.created), [take]);
  const [sel, setSel] = useState<string | null>(null);
  const [mark, setMark] = useState<{ start: number; end: number } | null>(null);
  const [tag, setTag] = useState("A15");
  const [note, setNote] = useState("");
  const [exportOpen, setExportOpen] = useState(false);
  const [pos, setPos] = useState(0);
  const cand = cands.find((c) => c.id === sel) ?? cands.find((c) => c.id === take?.chosen_candidate) ?? cands.filter((c) => c.stage !== "rejected").slice(-1)[0];
  const plan = take?.plans?.find((p) => p.id === cand?.plan_id);
  const feedback = useQuery({ queryKey: ["feedback", cand?.id], enabled: !!cand, queryFn: () => api.get<{ id: string; data: { start: number; end: number; tag: string; note: string } }[]>(`/api/candidates/${cand!.id}/feedback`) });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["take", take?.id] });
  const finalize = useMutation({ mutationFn: (noise?: number) => api.post(`/api/candidates/${cand!.id}/finalize`, { noise_seed: noise }), onSuccess: invalidate });
  const performance = useMutation({ mutationFn: () => api.post(`/api/plans/${cand!.plan_id}/render`, { n: 1 }), onSuccess: invalidate });
  const composition = useMutation({ mutationFn: () => api.post<{ take: Take }>(`/api/songs/${take!.song_id}/takes`, { draft_id: take!.draft_id, preset: take!.preset, allow_errors: true }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["song", take!.song_id] }); nav(`/song/${take!.song_id}/plan?take=${r.take.id}`); } });
  const saveMark = useMutation({
    mutationFn: () => api.post(`/api/candidates/${cand!.id}/feedback`, { kind: "issue", data: { ...mark, tag, note } }),
    onSuccess: () => { setMark(null); setNote(""); qc.invalidateQueries({ queryKey: ["feedback", cand?.id] }); },
  });
  const delMark = useMutation({ mutationFn: (id: string) => api.del(`/api/feedback/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["feedback", cand?.id] }) });

  const bands: Band[] = useMemo(() => (plan?.analysis?.sections ?? []).map((s) => ({
    start: s.start, end: s.end, label: s.tag ?? s.name, color: SECTION_COLORS[s.tag ?? ""] ?? "#94a3b8" })), [plan]);
  const markers: Marker[] = useMemo(() => {
    const out: Marker[] = [];
    for (const e of cand?.metrics?.events?.a15 ?? []) out.push({ start: e.start, end: e.end, label: `A15 shouted ending (${e.signals.join(", ")})`, color: "var(--color-singing)" });
    for (const e of cand?.metrics?.events?.a16 ?? []) out.push({ start: e.start, end: e.end, label: "A16 humming instead of words", color: "var(--color-warn)" });
    for (const r of cand?.asr?.repeated ?? []) out.push({ start: r.start, end: r.end, label: "A17 repeated lyrics", color: "var(--color-variety)" });
    for (const f of feedback.data ?? []) out.push({ start: f.data.start, end: f.data.end, label: `${f.data.tag} ${f.data.note ?? ""}`, color: "var(--color-bad)" });
    return out;
  }, [cand, feedback.data]);
  const lines = (take?.draft?.lyrics ?? "").split("\n");

  if (!take) return <div className="h-full grid place-items-center"><Spinner className="size-6" /></div>;
  if (!cands.length) return <div className="p-10"><Card><Empty icon={<AudioLines className="size-6" />} title={t("review.takes")} hint={t("review.noTakes")} /></Card></div>;
  const audio = cand?.files?.master ?? cand?.files?.final ?? cand?.files?.audition;
  const busy = take.status === "running" || take.status === "queued";
  const letters = "ABCDEFGHIJKLMNOP";

  return (
    <div className="h-full grid grid-cols-[260px_minmax(0,1fr)] gap-6 px-8 py-6 max-w-[1600px] mx-auto">
      <div className="flex flex-col gap-2.5 min-h-0 overflow-auto pb-24">
        <SectionTitle>{t("review.takes")}</SectionTitle>
        {cands.map((c, i) => <TakeRow key={c.id} c={c} letter={letters[i] ?? "?"} active={c.id === cand?.id} onClick={() => setSel(c.id)} />)}
      </div>

      <div className="flex flex-col gap-5 min-h-0 overflow-auto pb-24">
        {cand && audio ? (
          <Card className="p-6">
            <div className="flex items-center justify-between mb-5">
              <div>
                <div className="font-display text-3xl leading-none">{songTitle || t("library.untitled")}</div>
                <div className="text-[12px] text-ink-3 mt-1.5 flex gap-2">
                  <span>{cand.stage === "final" ? (cand.files.master ? "mastered" : "full quality") : "preview quality (8 steps)"}</span>
                  {cand.metrics?.master ? <span>· {cand.metrics.master.output_lufs.toFixed(1)} LUFS · {cand.metrics.master.true_peak_db.toFixed(1)} dBTP</span>
                    : cand.metrics?.audio && <span>· {cand.metrics.audio.lufs?.toFixed(1)} LUFS (raw)</span>}
                  {cand.metrics?.audio?.abrupt_ending && <Badge tone="warn">abrupt ending</Badge>}
                </div>
              </div>
              <div className="flex gap-2">
                {cand.stage !== "final" && (
                  <Button variant="primary" icon={<Gem className="size-4" />} onClick={() => finalize.mutate(undefined)} loading={finalize.isPending} disabled={busy}>{t("review.finalize")}</Button>
                )}
                {cand.stage === "final" && <Button variant="primary" icon={<Download className="size-4" />} onClick={() => setExportOpen(true)}>{t("review.export")}</Button>}
              </div>
            </div>
            <Waveform key={audio} ref={wave} url={audio} bands={bands} markers={markers} startAt={pos} onTime={setPos} onSelect={(s, e) => setMark({ start: s, end: e })} />
            <div className="mt-3 text-[11px] text-ink-3 flex items-center gap-2"><Flag className="size-3" />{t("review.markHint")} · Space = play/pause</div>
            <div className="mt-5 flex flex-wrap gap-2">
              <Button size="sm" variant="soft" icon={<Shuffle className="size-3.5" />} onClick={() => composition.mutate()} disabled={busy}>{t("review.rerollComposition")}</Button>
              <Button size="sm" variant="soft" icon={<Repeat className="size-3.5" />} onClick={() => performance.mutate()} disabled={busy}>{t("review.rerollPerformance")}</Button>
              <Button size="sm" variant="soft" icon={<Sparkles className="size-3.5" />} onClick={() => finalize.mutate(Math.floor(Math.random() * 2 ** 31))} disabled={busy}>{t("review.rerollTexture")}</Button>
            </div>
          </Card>
        ) : <Card className="p-6"><Spinner /></Card>}

        <div className="grid grid-cols-[minmax(0,1fr)_320px] gap-5">
        <Card className="p-5">
          <SectionTitle>{t("review.coverage")}</SectionTitle>
          {cand?.asr?.available ? (
            <ul className="flex flex-col gap-1">
              {cand.asr.lines.map((l) => (
                <li key={l.occurrence} className="flex items-center gap-3 text-[13px] rounded-lg px-2 py-1 hover:bg-panel-2 cursor-pointer"
                  onClick={() => l.start != null && wave.current?.seek(l.start)}>
                  <span className={cx("size-2 rounded-full shrink-0", l.coverage >= .8 ? "bg-good" : l.coverage >= .5 ? "bg-warn" : "bg-bad")} />
                  <span className="flex-1 truncate">{lines[l.line] ?? ""}</span>
                  <span className="text-[11px] tabular-nums text-ink-3 w-10 text-right">{Math.round(l.coverage * 100)}%</span>
                </li>
              ))}
            </ul>
          ) : <div className="text-[13px] text-ink-3">{t("review.noAsr")}</div>}
        </Card>
      <div className="flex flex-col gap-4">
        {cand && (
          <Card className="p-4">
            <div className="flex items-center gap-4 mb-4">
              <ScoreRing value={cand.score} size={56} passed={Object.values(cand.gates ?? {}).every(Boolean)} />
              <div className="text-[12px] text-ink-3">{t("review.score")}<div className="text-ink text-sm">{plan ? `score #${plan.idx + 1}` : ""}</div></div>
            </div>
            <GoalMeters card={cand.metrics?.card} />
            <div className="flex flex-wrap gap-1.5 mt-4">
              {Object.entries(cand.gates ?? {}).map(([g, ok]) => <Badge key={g} tone={ok ? "good" : "bad"}>{g.replaceAll("_", " ")}</Badge>)}
            </div>
          </Card>
        )}
        <Card className="p-4">
          <SectionTitle>{t("review.events")}</SectionTitle>
          {markers.length ? (
            <ul className="flex flex-col gap-1.5">
              {markers.map((m, i) => (
                <li key={i} className="flex items-center gap-2 text-[12px] rounded-lg px-2 py-1.5 border border-line hover:border-line-2 cursor-pointer" onClick={() => wave.current?.seek(m.start)}>
                  <span className="size-2 rounded-full shrink-0" style={{ background: m.color }} />
                  <span className="flex-1">{m.label}</span><span className="text-ink-3 tabular-nums">{fmtTime(m.start)}</span>
                  {feedback.data?.find((f) => f.data.start === m.start) && (
                    <button onClick={(e) => { e.stopPropagation(); delMark.mutate(feedback.data!.find((f) => f.data.start === m.start)!.id); }} className="text-ink-3 hover:text-bad"><Trash2 className="size-3.5" /></button>
                  )}
                </li>
              ))}
            </ul>
          ) : <div className="text-[13px] text-good">No problem moments detected.</div>}
        </Card>
      </div>
      </div>
      </div>

      <Modal open={!!mark} onOpenChange={(o) => !o && setMark(null)} title={`${t("review.mark")} · ${fmtTime(mark?.start)}–${fmtTime(mark?.end)}`}>
        <div className="grid grid-cols-2 gap-1.5 mb-4">
          {ISSUE_TAGS.map(([id, label]) => (
            <button key={id} onClick={() => setTag(id)} className={cx("text-left rounded-lg px-3 py-2 text-[13px] border transition",
              tag === id ? "border-accent/60 bg-accent/10" : "border-line hover:border-line-2")}>
              <span className="font-mono text-[11px] text-ink-3 mr-2">{id === "other" ? "" : id}</span>{id === "other" ? t("review.other") : label}
            </button>
          ))}
        </div>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("review.note")}
          className="w-full h-10 rounded-lg bg-panel-2 border border-line px-3 text-sm outline-none focus:border-accent/60 mb-4" />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setMark(null)}>{t("common.cancel")}</Button>
          <Button variant="primary" onClick={() => saveMark.mutate()} loading={saveMark.isPending}>{t("review.save")}</Button>
        </div>
      </Modal>

      <Modal open={exportOpen} onOpenChange={setExportOpen} title={t("review.export")}>
        <div className="grid grid-cols-2 gap-2">
          {cand && ([["master", "Master FLAC (24-bit)", FileAudio], ["mp3", "MP3 320k", FileAudio], ["final", "Raw render FLAC", FileAudio],
            ["lrc", "Synced lyrics (LRC)", FileText], ["abc", "Score (ABC)", FileMusic], ["midi", "MIDI", FileMusic], ["recipe", "Recipe (exact replay)", FileJson]] as const)
            .filter(([k]) => cand.files[k]).map(([k, label, Icon]) => (
              <a key={k} href={`${cand.files[k]}?download=1`} className="flex items-center gap-3 rounded-xl border border-line px-3 py-3 hover:border-accent/50 hover:bg-accent/5 transition">
                <Icon className="size-5 text-accent" /><span className="text-sm">{label}</span><Download className="size-4 ml-auto text-ink-3" />
              </a>
            ))}
        </div>
        <p className="text-[11px] text-ink-3 mt-4">{L === "zh" ? "导出文件已写入 AI 生成声明元数据。" : "Exports carry AI-generation disclosure metadata."}</p>
      </Modal>
    </div>
  );
}
