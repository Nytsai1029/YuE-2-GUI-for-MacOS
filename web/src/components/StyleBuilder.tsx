import { Mic, Pencil, Piano, RotateCcw, Wand2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { StyleFields, Vocab, VocabItem } from "../api";
import { lang } from "../i18n";
import { Chip, cx, Segmented, Slider } from "./ui";

export const DEFAULT_FIELDS: StyleFields = {
  language: "auto", genres: ["pop"], moods: [], gender: "female", timbre: ["warm"], delivery: "controlled",
  instruments: ["acoustic piano", "bass guitar", "drums"], production: ["polished studio mix"], harmony: "color",
  phrasing: ["memorable melody", "smooth phrasing"], bpm: 96, key: null, extra: "", override: null,
};

function Row({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div className="py-3 border-b border-line last:border-0">
      <div className="flex items-baseline justify-between mb-2">
        <div className="text-[12px] font-medium text-ink-2">{label}</div>
        {hint && <div className="text-[11px] text-ink-3">{hint}</div>}
      </div>
      {children}
    </div>
  );
}

function ChipSet({ items, value, onChange, max, color }: { items: VocabItem[]; value: string[]; onChange: (v: string[]) => void; max: number; color?: string }) {
  const L = lang();
  const toggle = (en: string) => {
    if (value.includes(en)) onChange(value.filter((x) => x !== en));
    else onChange([...value, en].slice(-max));
  };
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((it) => (
        <Chip key={it.en} active={value.includes(it.en)} onClick={() => toggle(it.en)} color={color}>
          {L === "zh" ? it.zh : it.en}
        </Chip>
      ))}
    </div>
  );
}

export function StyleBuilder({ fields, onChange, vocab, composed, detectedLanguage }:
  { fields: StyleFields; onChange: (f: StyleFields) => void; vocab?: Vocab; composed: string; detectedLanguage: string }) {
  const { t } = useTranslation();
  const L = lang();
  const [cat, setCat] = useState<"pop" | "edm">(fields.genres.some((g) => vocab?.genres.find((x) => x.en === g)?.cat === "edm") ? "edm" : "pop");
  const [editing, setEditing] = useState(false);
  const set = <K extends keyof StyleFields>(k: K, v: StyleFields[K]) => onChange({ ...fields, [k]: v });
  if (!vocab) return null;
  const genres = vocab.genres.filter((g) => (g.cat ?? "pop") === cat);
  const bpmOf = (name: string) => vocab.genres.find((g) => g.en === name)?.bpm;
  const instrumental = fields.gender === "none";
  return (
    <div className="flex flex-col">
      <div className="grid grid-cols-2 gap-2 pb-3 border-b border-line">
        {([false, true] as const).map((inst) => (
          <button key={String(inst)} type="button"
            onClick={() => onChange({ ...fields, gender: inst ? "none" : (fields.gender === "none" ? "female" : fields.gender) })}
            className={cx("rounded-xl border px-3 py-2.5 text-left transition flex items-center gap-2.5",
              instrumental === inst ? "border-accent/60 bg-accent/12 text-ink" : "border-line text-ink-3 hover:text-ink-2 hover:border-line-2")}>
            {inst ? <Piano className="size-4 shrink-0" /> : <Mic className="size-4 shrink-0" />}
            <span className="text-[13px] leading-tight">{inst ? t("style.modeInstrumental") : t("style.modeVocal")}</span>
          </button>
        ))}
      </div>
      <Row label={t("style.presets")}>
        <div className="flex flex-wrap gap-1.5">
          {vocab.presets.map((p) => (
            <button key={p.id} type="button" onClick={() => onChange({ ...DEFAULT_FIELDS, ...fields, ...p.fields, override: null } as StyleFields)}
              className="h-8 px-3 rounded-full text-[13px] border border-line hover:border-accent/50 hover:text-ink text-ink-2 flex items-center gap-1.5 transition">
              <Wand2 className="size-3.5 text-accent" />{p.name[L]}
            </button>
          ))}
        </div>
      </Row>

      <Row label={t("style.language")} hint={fields.language === "auto" ? `→ ${detectedLanguage}` : undefined}>
        <Segmented value={fields.language} onChange={(v) => set("language", v)} size="sm" options={[
          { value: "auto", label: t("style.auto") }, { value: "Chinese", label: "中文" }, { value: "English", label: "English" },
          { value: "Chinese and English", label: "中 + EN" }]} />
      </Row>

      <Row label={t("style.genre")} hint={`${fields.genres.length}/3`}>
        <div className="mb-2"><Segmented value={cat} onChange={setCat} size="sm" options={vocab.genre_categories.map((c) => ({ value: c.id as "pop" | "edm", label: c[L] }))} /></div>
        <div className="flex flex-wrap gap-1.5">
          {genres.map((g) => (
            <Chip key={g.en} active={fields.genres.includes(g.en)} onClick={() => {
              const on = fields.genres.includes(g.en);
              const next = on ? fields.genres.filter((x) => x !== g.en) : [...fields.genres, g.en].slice(-3);
              // Picking the first tempo-defining genre (e.g. artcore 175) suggests its typical BPM.
              const first = !on && g.bpm && fields.genres.every((x) => bpmOf(x) === undefined);
              onChange({ ...fields, genres: next, bpm: first ? g.bpm! : fields.bpm });
            }}>
              {L === "zh" ? g.zh : g.en}{g.half_time ? <span className="ml-1 text-[10px] text-ink-3">½</span> : null}
            </Chip>
          ))}
        </div>
      </Row>

      <Row label={t("style.tempo")} hint={fields.bpm ? `${fields.bpm} BPM` : ""}>
        <div className="flex items-center gap-3">
          <Slider value={fields.bpm ?? 96} min={50} max={230} onChange={(v) => set("bpm", v)} />
          <input type="number" value={fields.bpm ?? ""} min={40} max={240} onChange={(e) => set("bpm", e.target.value ? Number(e.target.value) : null)}
            className="w-16 h-8 rounded-lg bg-panel-2 border border-line px-2 text-sm text-center outline-none focus:border-accent/60" />
        </div>
      </Row>

      <Row label={t("style.mood")}><ChipSet items={vocab.moods} value={fields.moods} onChange={(v) => set("moods", v)} max={2} /></Row>

      <Row label={t("style.vocal")}>
        <div className="flex flex-col gap-2.5">
          <Segmented value={fields.gender} onChange={(v) => set("gender", v)} size="sm"
            options={(["female", "male", "duet", "choir", "none"] as const).map((g) => ({ value: g, label: t(`style.gender.${g}`) }))} />
          {fields.gender !== "none" && (
            <>
              <ChipSet items={vocab.timbres} value={fields.timbre} onChange={(v) => set("timbre", v)} max={2} color="var(--color-singing)" />
              <div className="flex flex-wrap gap-1.5 items-center">
                <span className="text-[11px] text-ink-3 mr-1">{t("style.delivery")}</span>
                {vocab.deliveries.map((d) => (
                  <Chip key={d.id} active={fields.delivery === d.id} onClick={() => set("delivery", d.id)} color="var(--color-singing)">{d[L]}</Chip>
                ))}
              </div>
            </>
          )}
        </div>
      </Row>

      <Row label={t("style.instruments")} hint={`${fields.instruments.length}/5`}>
        <ChipSet items={vocab.instruments.filter((i) => cat === "edm" || i.cat !== "edm")} value={fields.instruments} onChange={(v) => set("instruments", v)} max={5} />
      </Row>
      <Row label={t("style.production")}>
        <ChipSet items={vocab.production.filter((i) => cat === "edm" || i.cat !== "edm")} value={fields.production} onChange={(v) => set("production", v)} max={2} />
      </Row>
      <Row label={t("style.harmony")}>
        <Segmented value={fields.harmony} onChange={(v) => set("harmony", v)} size="sm"
          options={(["keep", "color", "rich", "jazz"] as const).map((h) => ({ value: h, label: t(`style.harmonyLevels.${h}`) }))} />
      </Row>
      <Row label={t("style.phrasing")}><ChipSet items={vocab.phrasing} value={fields.phrasing} onChange={(v) => set("phrasing", v)} max={3} color="var(--color-lyrics)" /></Row>
      <Row label={t("style.key")}>
        <select value={fields.key ?? ""} onChange={(e) => set("key", e.target.value || null)}
          className="h-8 rounded-lg bg-panel-2 border border-line px-2 text-sm outline-none">
          <option value="">{t("style.none")}</option>
          {vocab.keys.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      </Row>
      <Row label={t("style.extra")}>
        <input value={fields.extra} onChange={(e) => set("extra", e.target.value)} placeholder="e.g. vinyl crackle, big final chorus"
          className="w-full h-9 rounded-lg bg-panel-2 border border-line px-3 text-sm outline-none focus:border-accent/60" />
      </Row>

      <div className="mt-4 rounded-xl border border-line bg-bg-2/60 p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="text-[11px] uppercase tracking-[.14em] text-ink-3">{t("style.preview")}</div>
          {fields.override != null ? (
            <button className="text-[12px] text-ink-2 hover:text-ink flex items-center gap-1" onClick={() => { set("override", null); setEditing(false); }}>
              <RotateCcw className="size-3.5" />{t("style.reset")}
            </button>
          ) : (
            <button className="text-[12px] text-ink-2 hover:text-ink flex items-center gap-1" onClick={() => { set("override", composed); setEditing(true); }}>
              <Pencil className="size-3.5" />{t("style.edit")}
            </button>
          )}
        </div>
        {fields.override != null || editing ? (
          <textarea value={fields.override ?? composed} onChange={(e) => set("override", e.target.value)} rows={4}
            className="w-full rounded-lg bg-panel-2 border border-line p-2 text-[13px] font-mono outline-none focus:border-accent/60" />
        ) : (
          <p className={cx("text-[13px] leading-relaxed font-mono text-ink")}>{composed}</p>
        )}
      </div>
    </div>
  );
}
