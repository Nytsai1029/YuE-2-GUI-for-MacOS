import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { linter, lintGutter, setDiagnostics, type Diagnostic } from "@codemirror/lint";
import { EditorState, RangeSetBuilder, StateEffect, StateField, type Extension } from "@codemirror/state";
import {
  Decoration, EditorView, GutterMarker, gutter, keymap, placeholder, ViewPlugin, type DecorationSet, type ViewUpdate,
} from "@codemirror/view";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { CheckResult, Fix, Issue } from "../api";
import { lang } from "../i18n";

export const SECTION_COLORS: Record<string, string> = {
  Intro: "#94a3b8", Verse: "#38bdf8", "Pre-Chorus": "#a78bfa", Chorus: "#fb7185", Bridge: "#fbbf24",
  Interlude: "#2dd4bf", Outro: "#94a3b8",
};

export function applyFix(text: string, fix: Fix): string {
  if (fix.doc != null) return fix.doc;
  const lines = text.split("\n");
  const out: string[] = [];
  lines.forEach((line, i) => {
    const key = String(i);
    if (fix.lines && key in fix.lines) {
      const rep = fix.lines[key];
      if (rep !== null && rep !== undefined) out.push(rep);
    } else out.push(line);
  });
  return out.join("\n");
}

/* ------------------------------------------------------------ decorations fed from the analysis */
interface Meta { counts: Record<string, number>; sections: CheckResult["sections"]; maxSyl: number }
const setMeta = StateEffect.define<Meta>();
const metaField = StateField.define<Meta>({
  create: () => ({ counts: {}, sections: [], maxSyl: 14 }),
  update: (v, tr) => { for (const e of tr.effects) if (e.is(setMeta)) return e.value; return v; },
});

function sectionDecorations(view: EditorView): DecorationSet {
  const meta = view.state.field(metaField);
  const builder = new RangeSetBuilder<Decoration>();
  const byLine = new Map<number, { cls: string; color: string }>();
  for (const s of meta.sections) {
    const color = SECTION_COLORS[s.tag ?? ""] ?? "#6b7185";
    if (s.tag_line != null) byLine.set(s.tag_line, { cls: "cm-tag-line", color });
    for (const l of s.lines) byLine.set(l, { cls: "cm-sec", color });
  }
  for (let i = 1; i <= view.state.doc.lines; i++) {
    const d = byLine.get(i - 1);
    if (!d) continue;
    const line = view.state.doc.line(i);
    builder.add(line.from, line.from, Decoration.line({ class: d.cls, attributes: { style: `--sec:${d.color}` } }));
  }
  return builder.finish();
}

const sectionPlugin = ViewPlugin.fromClass(class {
  decorations: DecorationSet;
  constructor(view: EditorView) { this.decorations = sectionDecorations(view); }
  update(u: ViewUpdate) {
    if (u.docChanged || u.viewportChanged || u.transactions.some((t) => t.effects.some((e) => e.is(setMeta))))
      this.decorations = sectionDecorations(u.view);
  }
}, { decorations: (v) => v.decorations });

/** Tag lines render as pills: wrap the text in a mark. */
const tagMark = ViewPlugin.fromClass(class {
  decorations: DecorationSet;
  constructor(view: EditorView) { this.decorations = this.build(view); }
  update(u: ViewUpdate) { if (u.docChanged || u.viewportChanged) this.decorations = this.build(u.view); }
  build(view: EditorView) {
    const b = new RangeSetBuilder<Decoration>();
    for (let i = 1; i <= view.state.doc.lines; i++) {
      const line = view.state.doc.line(i);
      const m = /^\s*[[【][^\]】]+[\]】]/.exec(line.text);
      if (m) b.add(line.from + m.index, line.from + m.index + m[0].length, Decoration.mark({ class: "cm-tag-pill" }));
    }
    return b.finish();
  }
}, { decorations: (v) => v.decorations });

class SylMarker extends GutterMarker {
  constructor(readonly n: number, readonly max: number) { super(); }
  eq(o: SylMarker) { return o.n === this.n && o.max === this.max; }
  toDOM() {
    const el = document.createElement("div");
    el.className = "cm-syl";
    const ratio = this.n / this.max;
    const color = ratio > 1.3 ? "var(--color-bad)" : ratio > 1 ? "var(--color-warn)" : "var(--color-good)";
    el.innerHTML = `<span style="color:${ratio > 1 ? color : "var(--ink-3)"}">${this.n}</span><span class="bar"><i style="width:${Math.min(100, ratio * 100)}%;background:${color}"></i></span>`;
    el.title = `${this.n} syllables`;
    return el;
  }
}

const sylGutter = gutter({
  class: "cm-syl-gutter",
  lineMarker(view, line) {
    const meta = view.state.field(metaField);
    const idx = view.state.doc.lineAt(line.from).number - 1;
    const n = meta.counts[String(idx)];
    return n ? new SylMarker(n, meta.maxSyl) : null;
  },
  lineMarkerChange: (u) => u.transactions.some((t) => t.effects.some((e) => e.is(setMeta))),
  initialSpacer: () => new SylMarker(10, 14),
});

/* ------------------------------------------------------------ component */
export interface LyricsEditorHandle { focusLine: (line: number) => void; insertAtCursor: (text: string) => void }

export const LyricsEditor = forwardRef<LyricsEditorHandle, {
  value: string; onChange: (v: string) => void; issues: Issue[]; check?: CheckResult | null; placeholderText: string;
  onFix: (fix: Fix) => void; maxSyl?: number;
}>(function LyricsEditor({ value, onChange, issues, check, placeholderText, onFix, maxSyl = 14 }, ref) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const cb = useRef({ onChange, onFix });
  cb.current = { onChange, onFix };

  useEffect(() => {
    const extensions: Extension[] = [
      history(), keymap.of([...defaultKeymap, ...historyKeymap]), EditorView.lineWrapping, placeholder(placeholderText),
      metaField, sectionPlugin, tagMark, sylGutter, lintGutter(), linter(null),
      EditorView.updateListener.of((u) => { if (u.docChanged) cb.current.onChange(u.state.doc.toString()); }),
      EditorView.theme({ "&": { height: "100%" } }),
    ];
    view.current = new EditorView({ state: EditorState.create({ doc: value, extensions }), parent: host.current! });
    return () => view.current?.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // external value (fixes, templates, format)
  useEffect(() => {
    const v = view.current;
    if (!v) return;
    const cur = v.state.doc.toString();
    if (cur !== value) v.dispatch({ changes: { from: 0, to: cur.length, insert: value } });
  }, [value]);

  // analysis -> decorations + diagnostics
  useEffect(() => {
    const v = view.current;
    if (!v) return;
    const L = lang();
    const doc = v.state.doc;
    const diags: Diagnostic[] = [];
    for (const is of issues) {
      if (is.line == null || is.line + 1 > doc.lines) continue;
      const line = doc.line(is.line + 1);
      const from = is.start != null ? Math.min(line.to, line.from + is.start) : line.from;
      const to = is.end != null ? Math.min(line.to, line.from + is.end) : line.to;
      diags.push({
        from, to: Math.max(from, to), severity: is.severity === "error" ? "error" : is.severity === "warn" ? "warning" : "info",
        message: is.message[L], source: is.catalog,
        actions: is.fix ? [{ name: is.fix.label[L], apply: () => cb.current.onFix(is.fix!) }] : [],
      });
    }
    v.dispatch(setDiagnostics(v.state, diags));
    v.dispatch({ effects: setMeta.of({ counts: check?.counts ?? {}, sections: check?.sections ?? [], maxSyl }) });
  }, [issues, check, maxSyl]);

  useImperativeHandle(ref, () => ({
    focusLine: (line: number) => {
      const v = view.current;
      if (!v || line + 1 > v.state.doc.lines) return;
      const l = v.state.doc.line(line + 1);
      v.dispatch({ selection: { anchor: l.from, head: l.to }, scrollIntoView: true });
      v.focus();
    },
    insertAtCursor: (text: string) => {
      const v = view.current;
      if (!v) return;
      const pos = v.state.selection.main.head;
      const line = v.state.doc.lineAt(pos);
      const atStart = line.text.trim() === "";
      const insert = (atStart ? "" : "\n") + text;
      const at = atStart ? line.from : line.to;
      v.dispatch({ changes: { from: at, to: atStart ? line.to : at, insert }, selection: { anchor: at + insert.length } });
      v.focus();
    },
  }));

  return <div ref={host} className="h-full min-h-[420px]" />;
});
