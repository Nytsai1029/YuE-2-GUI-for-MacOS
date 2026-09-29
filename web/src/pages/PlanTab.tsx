import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CopyPlus, FileMusic, Minus, Mic2, Music, Pause, Play, Plus, Scissors, Sparkles, Wand2 } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type Issue, type Plan, type PlanAnalysis, type Take } from "../api";
import { IssueList } from "../components/IssueList";
import { SheetMusic } from "../components/SheetMusic";
import { Badge, Button, Card, cx, Empty, fmtTime, GoalMeters, ScoreRing, SectionTitle, Segmented, Spinner } from "../components/ui";
import { lang } from "../i18n";
import { Sketch, type SketchNotes } from "../lib/sketch";

const NOTE = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
const pname = (m: number) => `${NOTE[m % 12]}${Math.floor(m / 12) - 1}`;

function RangeBar({ a }: { a: PlanAnalysis }) {
  const r = a.range;
  if (!r?.available) return null;
  const lo = 36, hi = 90, w = (m: number) => ((m - lo) / (hi - lo)) * 100;
  return (
    <div>
      <div className="relative h-8 rounded-lg bg-bg-2 border border-line overflow-hidden">
        {Array.from({ length: hi - lo }, (_, i) => lo + i).filter((m) => [1, 3, 6, 8, 10].includes(m % 12)).map((m) => (
          <div key={m} className="absolute top-0 h-4 bg-line-2" style={{ left: `${w(m)}%`, width: `${100 / (hi - lo)}%` }} />
        ))}
        <div className="absolute inset-y-0 bg-good/15 border-x border-good/40" style={{ left: `${w(r.comfort[0])}%`, width: `${w(r.comfort[1]) - w(r.comfort[0])}%` }} />
        <motion.div className="absolute top-1/2 -translate-y-1/2 h-2.5 rounded-full grad-bg" initial={false}
          animate={{ left: `${w(r.low)}%`, width: `${Math.max(1, w(r.high) - w(r.low))}%` }} />
      </div>
      <div className="flex justify-between text-[11px] text-ink-3 mt-1"><span>{pname(r.low)}</span><span>comfort {pname(r.comfort[0])}–{pname(r.comfort[1])}</span><span>{pname(r.high)}</span></div>
    </div>
  );
}

function PlanCard({ plan, active, onClick }: { plan: Plan; active: boolean; onClick: () => void }) {
  const { t } = useTranslation();
  const a = plan.analysis;
  return (
    <button onClick={onClick} className={cx("w-full text-left rounded-2xl p-3.5 border transition-all",
      active ? "border-accent/60 bg-accent/8 shadow-[0_0_0_1px_var(--accent)_inset]" : "border-line bg-panel hover:border-line-2")}>
      <div className="flex items-center gap-3">
        <ScoreRing value={plan.score} passed={!!plan.passed} />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium flex items-center gap-2">
            <FileMusic className="size-3.5 text-ink-3" />#{plan.idx + 1}
            {plan.source === "edited" ? <Badge tone="accent">{t("plan.edited")}</Badge> : null}
            {plan.passed ? <Badge tone="good">{t("plan.passed")}</Badge> : a ? <Badge tone="warn">{t("plan.failed")}</Badge> : null}
          </div>
          {a?.ok && <div className="text-[11px] text-ink-3 mt-0.5">{a.key} · {a.bpm} BPM · {fmtTime(a.predicted_seconds)} · {a.harmony.unique} chords</div>}
        </div>
      </div>
      {a?.scorecard && <div className="mt-3"><GoalMeters card={a.scorecard} compact /></div>}
    </button>
  );
}

function RepairPanel({ plan, onApplied }: { plan: Plan; onApplied: (p: Plan) => void }) {
  const { t } = useTranslation();
  const a = plan.analysis!;
  const [level, setLevel] = useState<"color" | "rich" | "jazz">("color");
  const [semis, setSemis] = useState(a.range?.suggest_transpose ?? 0);
  const [bpm, setBpm] = useState(a.bpm);
  const [preview, setPreview] = useState<{ ops: unknown[]; diff: { bar: number; before: string[]; after: string[] }[]; analysis: PlanAnalysis } | null>(null);
  const [pending, setPending] = useState<unknown[] | null>(null);
  useEffect(() => { setSemis(a.range?.suggest_transpose ?? 0); setBpm(a.bpm); setPreview(null); }, [plan.id, a]);
  const run = useMutation({
    mutationFn: ({ ops, apply }: { ops: unknown[]; apply: boolean }) =>
      api.post<{ plan?: Plan; ops: unknown[]; diff: never; analysis: PlanAnalysis }>(`/api/plans/${plan.id}/repair`, { ops, preview: !apply }),
    onSuccess: (r, v) => { if (v.apply && r.plan) { setPreview(null); onApplied(r.plan); } else { setPreview(r); setPending(v.ops); } },
  });
  const Op = ({ icon, title, hint, children }: { icon: React.ReactNode; title: string; hint?: string; children: React.ReactNode }) => (
    <div className="rounded-xl border border-line p-3.5 flex flex-col gap-2.5">
      <div className="flex items-center gap-2 text-[13px] font-medium">{icon}{title}</div>
      {hint && <div className="text-[12px] text-ink-3 -mt-1">{hint}</div>}
      {children}
    </div>
  );
  const go = (ops: unknown[]) => run.mutate({ ops, apply: false });
  return (
    <div className="flex flex-col gap-3">
      <Op icon={<Sparkles className="size-4 text-harmony" />} title={t("style.harmony")} hint={`${a.harmony.unique} chords · ${Math.round(a.harmony.richness * 100)}% richness${a.harmony.whole_song_loop ? " · one loop" : ""}`}>
        <div className="flex items-center gap-2">
          <Segmented value={level} onChange={setLevel} size="sm" options={(["color", "rich", "jazz"] as const).map((l) => ({ value: l, label: t(`style.harmonyLevels.${l}`) }))} />
          <Button size="sm" variant="soft" onClick={() => go([{ op: "reharmonize", level }])} loading={run.isPending}>{t("plan.preview")}</Button>
        </div>
      </Op>
      {a.length?.target ? (
        <Op icon={<Music className="size-4 text-lyrics" />} title={t("plan.fitLength")}
          hint={`${fmtTime(a.predicted_seconds)} → ${fmtTime(a.length.target)} · ${t("plan.fitLengthHint")}`}>
          <Button size="sm" variant="soft" disabled={Math.abs((a.length.ratio ?? 1) - 1) < 0.04}
            onClick={() => go([{ op: "fit_length" }])}>{t("plan.preview")}</Button>
        </Op>
      ) : null}
      <Op icon={<Mic2 className="size-4 text-singing" />} title={t("plan.transpose")}>
        <RangeBar a={a} />
        <div className="flex items-center gap-2">
          <Button size="sm" variant="soft" icon={<Minus className="size-3.5" />} onClick={() => setSemis(semis - 1)} />
          <span className="w-12 text-center tabular-nums text-sm">{semis > 0 ? "+" : ""}{semis}</span>
          <Button size="sm" variant="soft" icon={<Plus className="size-3.5" />} onClick={() => setSemis(semis + 1)} />
          <Button size="sm" variant="soft" disabled={!semis} onClick={() => go([{ op: "transpose", semitones: semis }])}>{t("plan.preview")}</Button>
        </div>
      </Op>
      <Op icon={<Music className="size-4 text-lyrics" />} title={t("plan.tempo")}>
        <div className="flex items-center gap-2">
          <input type="number" value={bpm} onChange={(e) => setBpm(Number(e.target.value))} className="w-20 h-8 rounded-lg bg-panel-2 border border-line px-2 text-sm text-center" />
          <span className="text-[12px] text-ink-3">BPM</span>
          <Button size="sm" variant="soft" disabled={bpm === a.bpm} onClick={() => go([{ op: "tempo", bpm }])}>{t("plan.preview")}</Button>
        </div>
      </Op>
      {a.issues.some((i) => i.rule === "plan.vocal_in_instrumental") && (
        <Op icon={<Music className="size-4 text-warn" />} title={lang() === "zh" ? "改为纯音乐" : "Make instrumental"}
          hint={lang() === "zh" ? "把歌手声部的旋律移到乐器声部，歌手声部改为休止，避免被哼唱出来。"
            : "Move the singer's melody to the instrument line and silence the vocal part so nothing gets hummed."}>
          <Button size="sm" variant="soft" onClick={() => go([{ op: "instrumentalize" }])}>{t("plan.preview")}</Button>
        </Op>
      )}
      <Op icon={<Wand2 className="size-4 text-accent" />} title={t("plan.smooth")} hint={t("plan.smoothHint")}>
        <Button size="sm" variant="soft" onClick={() => go([{ op: "smooth_endings" }])}>{t("plan.preview")}</Button>
      </Op>
      <Op icon={<CopyPlus className="size-4 text-variety" />} title={t("plan.sections")}>
        <ul className="flex flex-col gap-1">
          {a.sections.map((s) => (
            <li key={s.index} className="flex items-center gap-2 text-[12px]">
              <span className="w-24 truncate">{s.tag ?? s.name ?? "—"}</span>
              <span className="text-ink-3">{s.bars} bars · {fmtTime(s.start)}</span>
              {a.alignment.extra_abc.includes(s.index) && <Badge tone="warn">extra</Badge>}
              <span className="ml-auto flex gap-1">
                <button className="text-ink-3 hover:text-ink" title={t("plan.duplicate")} onClick={() => go([{ op: "duplicate_section", section: s.index }])}><CopyPlus className="size-3.5" /></button>
                <button className="text-ink-3 hover:text-bad" title={t("plan.drop")} onClick={() => go([{ op: "drop_section", section: s.index }])}><Scissors className="size-3.5" /></button>
              </span>
            </li>
          ))}
        </ul>
      </Op>
      {run.isError && <div className="text-[12px] text-bad">{(run.error as Error).message}</div>}
      {preview && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="rounded-xl border border-accent/40 bg-accent/6 p-3.5 flex flex-col gap-3">
          <div className="flex items-center gap-3">
            <ScoreRing value={preview.analysis.score} passed={preview.analysis.passed} size={40} />
            <div className="flex-1"><GoalMeters card={preview.analysis.scorecard} compact /></div>
          </div>
          {preview.diff?.length ? (
            <div className="max-h-40 overflow-auto text-[12px] font-mono flex flex-col gap-0.5">
              <div className="text-ink-3 font-sans mb-1">{preview.diff.length} {t("plan.chordChanges")}</div>
              {preview.diff.slice(0, 40).map((d) => (
                <div key={d.bar} className="flex gap-2"><span className="text-ink-3 w-10">m{d.bar + 1}</span>
                  <span className="text-ink-3 line-through">{d.before.join(" ")}</span><ArrowRight className="size-3 mt-0.5 text-ink-3" />
                  <span className="text-harmony">{d.after.join(" ")}</span></div>
              ))}
            </div>
          ) : null}
          <div className="flex gap-2 justify-end">
            <Button size="sm" variant="ghost" onClick={() => setPreview(null)}>{t("common.cancel")}</Button>
            <Button size="sm" variant="primary" onClick={() => pending && run.mutate({ ops: pending, apply: true })} loading={run.isPending}>{t("plan.apply")}</Button>
          </div>
        </motion.div>
      )}
    </div>
  );
}

export function PlanTab({ take, loading, onReview }: { take?: Take; loading: boolean; onReview: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const plans = useMemo(() => take?.plans ?? [], [take]);
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<"sheet" | "findings" | "repair">("sheet");
  const [takesN, setTakesN] = useState(2);
  const best = [...plans].filter((p) => p.analysis).sort((a, b) => (b.passed - a.passed) || ((b.score ?? 0) - (a.score ?? 0)))[0];
  const plan = plans.find((p) => p.id === selected) ?? plans.find((p) => p.id === take?.chosen_plan) ?? best ?? plans[plans.length - 1];
  const display = useQuery({ queryKey: ["display", plan?.id], enabled: !!plan?.abc, queryFn: () => api.get<{ abc: string; bpm: number }>(`/api/plans/${plan!.id}/display`) });
  const notes = useQuery({ queryKey: ["notes", plan?.id], enabled: !!plan?.abc, queryFn: () => api.get<SketchNotes>(`/api/plans/${plan!.id}/notes`) });
  const sketch = useRef<Sketch>(new Sketch());
  const [playhead, setPlayhead] = useState<number | null>(null);
  useEffect(() => { const s = sketch.current; s.onTime = setPlayhead; s.onEnd = () => setPlayhead(null); return () => s.stop(); }, []);
  useEffect(() => { sketch.current.stop(); setPlayhead(null); }, [plan?.id]);
  const render = useMutation({ mutationFn: () => api.post(`/api/plans/${plan!.id}/render`, { n: takesN }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["take", take?.id] }); onReview(); } });

  if (loading) return <div className="h-full grid place-items-center"><Spinner className="size-6" /></div>;
  if (!take || !plans.length) {
    return <div className="p-10"><Card><Empty icon={<FileMusic className="size-6" />} title={t("plan.plans")} hint={t("plan.noPlans")} /></Card></div>;
  }
  const a = plan?.analysis;
  const L = lang();
  const issues: Issue[] = a?.issues ?? [];
  return (
    <div className="h-full grid grid-cols-[260px_minmax(0,1fr)] gap-6 px-8 py-6 max-w-[1600px] mx-auto">
      <div className="flex flex-col gap-3 min-h-0 overflow-auto pb-24">
        <SectionTitle>{t("plan.plans")}</SectionTitle>
        {plans.map((p) => <PlanCard key={p.id} plan={p} active={p.id === plan?.id} onClick={() => setSelected(p.id)} />)}
      </div>

      <Card className="min-h-0 flex flex-col overflow-hidden mb-20">
        {a?.ok && (
          <div className="flex items-center gap-5 px-5 py-4 border-b border-line">
            <ScoreRing value={plan!.score} passed={!!plan!.passed} size={52} />
            <div className="min-w-0">
              <div className="font-display text-2xl leading-none">#{plan!.idx + 1}{plan!.source === "edited" ? <span className="text-[12px] font-sans ml-2 text-accent">{t("plan.edited")}</span> : null}</div>
              <div className="text-[12px] text-ink-3 mt-1">{a.key} · {a.bpm} BPM · {a.bars} bars · {fmtTime(a.predicted_seconds)} · {a.harmony.unique} chords</div>
            </div>
            <div className="w-72 shrink-0"><GoalMeters card={a.scorecard} compact /></div>
            <div className="flex flex-wrap gap-1.5 justify-end flex-1">
              {Object.entries(a.gates).map(([g, ok]) => <Badge key={g} tone={ok ? "good" : "bad"}>{g.replaceAll("_", " ")}</Badge>)}
            </div>
          </div>
        )}
        <div className="flex items-center gap-3 px-5 py-3 border-b border-line">
          <Segmented value={view} onChange={setView} size="sm" options={[
            { value: "sheet", label: t("plan.sheet") },
            { value: "findings", label: <span>{t("plan.issues")} {issues.length ? <span className="text-ink-3">{issues.length}</span> : null}</span> },
            { value: "repair", label: t("plan.repair") }]} />
          <div className="ml-auto flex items-center gap-2">
            <Button size="sm" variant="soft" disabled={!notes.data} icon={playhead != null ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
              onClick={() => { if (playhead != null) { sketch.current.stop(); setPlayhead(null); } else if (notes.data) sketch.current.play(notes.data); }}>
              {playhead != null ? `${t("plan.stop")} · ${fmtTime(playhead)}` : t("plan.sketch")}
            </Button>
            <select value={takesN} onChange={(e) => setTakesN(Number(e.target.value))} className="h-8 rounded-lg bg-panel-2 border border-line px-2 text-[12px]">
              {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}×</option>)}
            </select>
            <Button size="sm" variant="primary" icon={<Mic2 className="size-3.5" />} onClick={() => render.mutate()} loading={render.isPending}
              disabled={!a?.ok || take.status === "running" || take.status === "queued"}>{t("plan.renderThis")}</Button>
          </div>
        </div>
        <div className="flex-1 min-h-0 overflow-auto p-6">
          {!a ? <div className="grid place-items-center h-full"><Spinner className="size-6" /></div> : view === "sheet" ? (
            display.data?.abc ? <SheetMusic abc={display.data.abc} bpm={display.data.bpm} playhead={playhead} /> : <Spinner />
          ) : view === "repair" ? (
            a.ok ? <div className="max-w-2xl"><RepairPanel plan={plan!} onApplied={(p) => { qc.invalidateQueries({ queryKey: ["take", take.id] }); setSelected(p.id); setView("sheet"); }} /></div> : null
          ) : (
            <div className="flex flex-col gap-6 max-w-3xl">
              <IssueList issues={issues} />
              {a?.alignment?.lines?.length ? (
                <div>
                  <SectionTitle>Syllables → notes</SectionTitle>
                  <div className="grid grid-cols-[repeat(auto-fill,minmax(140px,1fr))] gap-2">
                    {a.alignment.lines.map((l, i) => {
                      const bad = l.ratio < 0.8 ? "bad" : l.ratio > 1.8 ? "warn" : "good";
                      return (
                        <div key={i} className="rounded-lg border border-line px-2.5 py-1.5 text-[12px] flex items-center gap-2">
                          <span className="text-ink-3">L{l.line + 1}</span><span className="tabular-nums">{l.syllables}→{l.notes}</span>
                          <span className={cx("ml-auto size-2 rounded-full", bad === "bad" ? "bg-bad" : bad === "warn" ? "bg-warn" : "bg-good")} />
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : null}
              <div className="text-[11px] text-ink-3">{a.harmony.vocabulary.slice(0, 16).join(" · ")}</div>
            </div>
          )}
        </div>
      </Card>
      <span className="hidden">{L}</span>
    </div>
  );
}
