import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookA, Clock3, Eye, EyeOff, Languages, LayoutTemplate, Plus, Sparkles, Trash2, Wand2 } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type CheckResult, type Fix, type Issue, type StyleFields, type Vocab } from "../api";
import { IssueList } from "../components/IssueList";
import { applyFix, LyricsEditor, SECTION_COLORS, type LyricsEditorHandle } from "../components/LyricsEditor";
import { StyleBuilder } from "../components/StyleBuilder";
import { Badge, Button, Card, cx, fmtTime, Modal, SectionTitle, Spinner } from "../components/ui";
import { lang } from "../i18n";

const TAGS = ["Intro", "Verse", "Pre-Chorus", "Chorus", "Bridge", "Interlude", "Outro"];
/** Mechanical, meaning-preserving fixes only; structural suggestions stay one-by-one. */
const SAFE_FIX = (rule: string) => !["lyrics.structure.empty_vocal", "lyrics.tag.unknown", "lyrics.line_length",
  "lyrics.structure.no_outro", "lyrics.backing", "lyrics.url"].includes(rule);

function Lexicon() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [term, setTerm] = useState("");
  const [sung, setSung] = useState("");
  const list = useQuery({ queryKey: ["lexicon"], queryFn: () => api.get<{ term: string; sung: string }[]>("/api/lexicon") });
  const add = useMutation({ mutationFn: () => api.post("/api/lexicon", { term, sung }),
    onSuccess: () => { setTerm(""); setSung(""); qc.invalidateQueries({ queryKey: ["lexicon"] }); qc.invalidateQueries({ queryKey: ["check"] }); } });
  const del = useMutation({ mutationFn: (x: string) => api.del(`/api/lexicon/${encodeURIComponent(x)}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["lexicon"] }); qc.invalidateQueries({ queryKey: ["check"] }); } });
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-ink-2">{t("write.lexiconHint")}</p>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (term && sung) add.mutate(); }}>
        <input value={term} onChange={(e) => setTerm(e.target.value)} placeholder="GPT / 重庆"
          className="flex-1 h-9 rounded-lg bg-panel-2 border border-line px-3 text-sm outline-none focus:border-accent/60" />
        <input value={sung} onChange={(e) => setSung(e.target.value)} placeholder="G P T / 崇庆"
          className="flex-1 h-9 rounded-lg bg-panel-2 border border-line px-3 text-sm outline-none focus:border-accent/60" />
        <Button type="submit" variant="primary" size="sm" icon={<Plus className="size-4" />} disabled={!term || !sung} />
      </form>
      <ul className="flex flex-col gap-1 max-h-72 overflow-auto">
        {list.data?.map((x) => (
          <li key={x.term} className="flex items-center gap-3 rounded-lg px-3 py-2 bg-panel-2/60 border border-line text-sm">
            <span className="font-medium">{x.term}</span><span className="text-ink-3">→</span><span className="text-ink-2">{x.sung}</span>
            <button className="ml-auto text-ink-3 hover:text-bad" onClick={() => del.mutate(x.term)}><Trash2 className="size-4" /></button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function WriteTab({ work, check, vocab, checking }: {
  work: { lyrics: string; fields: StyleFields; setLyrics: (v: string) => void; setFields: (f: StyleFields) => void };
  check?: CheckResult; vocab?: Vocab; checking: boolean;
}) {
  const { t } = useTranslation();
  const L = lang();
  const editor = useRef<LyricsEditorHandle>(null);
  const [showSung, setShowSung] = useState(false);
  const [lexOpen, setLexOpen] = useState(false);
  const [side, setSide] = useState<"coach" | "style">("coach");
  const lyricIssues = check?.issues ?? [];
  const styleIssues = check?.style_issues ?? [];
  const all = useMemo(() => [...lyricIssues, ...styleIssues], [lyricIssues, styleIssues]);
  const counts = { error: all.filter((i) => i.severity === "error").length, warn: all.filter((i) => i.severity === "warn").length,
    hint: all.filter((i) => i.severity === "hint").length };
  const fix = (f: Fix) => work.setLyrics(applyFix(work.lyrics, f));
  const fixAll = () => {
    // one fix per line (first wins), applied together so line indices stay valid
    const merged: Record<string, string | null> = {};
    for (const is of lyricIssues) {
      if (!is.fix?.lines || is.severity === "hint" || !SAFE_FIX(is.rule)) continue;
      for (const [k, v] of Object.entries(is.fix.lines)) if (!(k in merged)) merged[k] = v;
    }
    if (Object.keys(merged).length) work.setLyrics(applyFix(work.lyrics, { label: { en: "", zh: "" }, lines: merged }));
  };
  const jump = (is: Issue) => { if (is.line != null) editor.current?.focusLine(is.line); };
  const maxSyl = (check?.language ?? "zh") === "zh" ? 14 : 14;
  const est = check?.estimate;
  const fixable = lyricIssues.filter((i) => i.fix?.lines && i.severity !== "hint" && SAFE_FIX(i.rule)).length;

  return (
    <div className="h-full grid grid-cols-[minmax(0,1fr)_420px] gap-6 px-8 py-6 max-w-[1600px] mx-auto">
      {/* ---------------- lyrics ---------------- */}
      <Card className="flex flex-col min-h-0 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-line flex-wrap">
          <div className="text-[11px] uppercase tracking-[.14em] text-ink-3 mr-2">{t("write.lyrics")}</div>
          {TAGS.map((tag) => (
            <button key={tag} onClick={() => editor.current?.insertAtCursor(`[${tag}]\n`)}
              className="h-7 px-2.5 rounded-full text-[12px] border transition hover:brightness-125"
              style={{ color: SECTION_COLORS[tag], borderColor: `color-mix(in oklab, ${SECTION_COLORS[tag]} 35%, transparent)`,
                background: `color-mix(in oklab, ${SECTION_COLORS[tag]} 10%, transparent)` }}>
              {tag}
            </button>
          ))}
          <div className="ml-auto flex items-center gap-1">
            {vocab && (
              <select onChange={(e) => {
                const tpl = vocab.templates.find((x) => x.id === e.target.value);
                if (tpl) work.setLyrics((work.lyrics.trim() ? work.lyrics.trimEnd() + "\n\n" : "") +
                  tpl.sections.map((s) => `[${s}]\n`).join("\n"));
                e.target.value = "";
              }} defaultValue="" className="h-7 rounded-lg bg-transparent text-[12px] text-ink-2 hover:text-ink outline-none">
                <option value="" disabled>{t("write.templates")}…</option>
                {vocab.templates.map((tp) => <option key={tp.id} value={tp.id}>{tp.name[L]}</option>)}
              </select>
            )}
            <Button size="sm" variant="ghost" icon={<Wand2 className="size-3.5" />} title={t("write.formatHint")}
              onClick={() => check?.sung && work.setLyrics(check.sung.trimEnd() + "\n")}>{t("write.format")}</Button>
            <Button size="sm" variant="ghost" icon={<BookA className="size-3.5" />} onClick={() => setLexOpen(true)}>{t("write.lexicon")}</Button>
            <Button size="sm" variant="ghost" icon={showSung ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />} onClick={() => setShowSung(!showSung)}>
              {t("write.sung")}
            </Button>
          </div>
        </div>
        {work.fields.gender === "none" && (
          <div className="px-4 py-2.5 border-b border-line bg-accent/8 text-[12px] text-ink-2 flex items-center gap-2">
            <Sparkles className="size-3.5 text-accent shrink-0" />{t("write.instrumental")}
          </div>
        )}
        <div className={cx("flex-1 min-h-0 grid", showSung ? "grid-cols-2" : "grid-cols-1")}>
          <div className="min-h-0 overflow-auto">
            <LyricsEditor ref={editor} value={work.lyrics} onChange={work.setLyrics} issues={lyricIssues} check={check}
              placeholderText={t("write.placeholder")} onFix={fix} maxSyl={maxSyl} />
          </div>
          {showSung && (
            <div className="min-h-0 overflow-auto border-l border-line bg-bg-2/40 px-5 py-4">
              <div className="text-[11px] uppercase tracking-[.14em] text-ink-3 mb-3">{t("write.sung")}</div>
              <pre className="font-mono text-[13px] leading-7 whitespace-pre-wrap text-ink-2">{check?.sung}</pre>
            </div>
          )}
        </div>
        <div className="flex items-center gap-4 px-4 py-2.5 border-t border-line text-[12px] text-ink-3">
          <span className="flex items-center gap-1.5"><Clock3 className="size-3.5" />{t("write.length")} ≈ <b className="text-ink-2 font-medium">{fmtTime(est?.seconds)}</b>
            {work.fields.target_seconds ? <span className={cx(est && Math.abs(est.seconds / work.fields.target_seconds - 1) > 0.2 ? "text-warn" : "text-ink-3")}>
              / {fmtTime(work.fields.target_seconds)}</span> : null}</span>
          <span className="flex items-center gap-1.5"><Languages className="size-3.5" />{check?.language ?? "–"}</span>
          {check && check.vocal_bpm !== check.bpm && <span>{Math.round(check.vocal_bpm)} BPM {t("write.tempoFeel")}</span>}
          {est && (
            <div className="relative flex-1 h-2 rounded-full overflow-hidden flex bg-line max-w-md">
              {work.fields.target_seconds ? <span className="absolute inset-y-0 w-0.5 bg-ink z-10" title="target"
                style={{ left: `${Math.min(100, (work.fields.target_seconds / Math.max(est.seconds, work.fields.target_seconds)) * 100)}%` }} /> : null}
              {est.sections.map((s, i) => (
                <div key={i} title={`${s.tag} · ${fmtTime(s.seconds)}`} style={{ width: `${(s.seconds / Math.max(1, est.seconds)) * 100}%`,
                  background: SECTION_COLORS[s.tag] ?? "var(--ink-3)", opacity: .75 }} className="h-full border-r border-bg" />
              ))}
            </div>
          )}
          {checking && <Spinner className="size-3.5" />}
        </div>
      </Card>

      {/* ---------------- side: coach / style ---------------- */}
      <div className="flex flex-col min-h-0 gap-4">
        <div className="flex rounded-xl bg-panel-2 border border-line p-1">
          {(["coach", "style"] as const).map((s) => (
            <button key={s} onClick={() => setSide(s)}
              className={cx("flex-1 h-9 rounded-lg text-[13px] flex items-center justify-center gap-2 transition",
                side === s ? "bg-bg-2 border border-line-2 text-ink" : "text-ink-3 hover:text-ink-2")}>
              {s === "coach" ? <Sparkles className="size-4" /> : <LayoutTemplate className="size-4" />}
              {t(`write.${s}`)}
              {s === "coach" && (counts.error + counts.warn > 0) && (
                <span className={cx("text-[10px] rounded-full px-1.5", counts.error ? "bg-bad/20 text-bad" : "bg-warn/20 text-warn")}>{counts.error + counts.warn}</span>
              )}
            </button>
          ))}
        </div>
        <Card className="flex-1 min-h-0 overflow-auto p-4">
          {side === "coach" ? (
            <>
              <SectionTitle right={fixable > 0 && <Button size="sm" variant="soft" icon={<Wand2 className="size-3.5" />} onClick={fixAll}>{t("write.fixAll")} ({fixable})</Button>}>
                <span className="flex items-center gap-2">
                  {t("write.coach")}
                  {counts.error > 0 && <Badge tone="bad">{counts.error}</Badge>}
                  {counts.warn > 0 && <Badge tone="warn">{counts.warn}</Badge>}
                  {counts.hint > 0 && <Badge tone="hint">{counts.hint}</Badge>}
                </span>
              </SectionTitle>
              <IssueList issues={all} onJump={(is) => { if (is.rule.startsWith("style.")) setSide("style"); else jump(is); }} onFix={fix} />
              {check && (
                <div className="mt-5 rounded-xl border border-line p-3 text-[12px] text-ink-3 leading-relaxed">
                  <div className="text-ink-2 font-medium mb-1">{t("style.preview")}</div>
                  <div className="font-mono text-ink-2">{check.style}</div>
                </div>
              )}
            </>
          ) : (
            <StyleBuilder fields={work.fields} onChange={work.setFields} vocab={vocab} composed={check?.style ?? ""}
              detectedLanguage={check?.language === "zh" ? "中文" : check?.language === "en" ? "English" : check?.language ?? ""} />
          )}
        </Card>
      </div>

      <Modal open={lexOpen} onOpenChange={setLexOpen} title={t("write.lexicon")}><Lexicon /></Modal>
    </div>
  );
}
