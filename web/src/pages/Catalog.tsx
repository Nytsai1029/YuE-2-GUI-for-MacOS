import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type Bi } from "../api";
import { Badge, Card, cx, GOAL_COLORS, Segmented } from "../components/ui";
import { lang } from "../i18n";

interface Rule { id: string; catalog: string; stage: string; severity: string; goal: string; title: Bi; doc: string }

const GROUPS: Record<string, Bi> = {
  A: { en: "Lyrics & vocals", zh: "歌词与人声" }, B: { en: "Composition & arrangement", zh: "作曲与编曲" },
  C: { en: "Audio & delivery", zh: "音频与交付" }, D: { en: "Workflow", zh: "工作流程" },
};

export function Catalog() {
  const { t } = useTranslation();
  const L = lang();
  const [stage, setStage] = useState("all");
  const rules = useQuery({ queryKey: ["rules"], queryFn: () => api.get<Rule[]>("/api/rules"), staleTime: Infinity });
  const grouped = useMemo(() => {
    const out: Record<string, Rule[]> = {};
    for (const r of rules.data ?? []) {
      if (stage !== "all" && r.stage !== stage) continue;
      (out[r.catalog[0]] ??= []).push(r);
    }
    return out;
  }, [rules.data, stage]);
  return (
    <div className="max-w-5xl mx-auto px-10 py-10">
      <h1 className="font-display text-5xl mb-3">{t("nav.catalog")}</h1>
      <p className="text-ink-2 mb-6 max-w-2xl">
        {L === "zh" ? "每一条检查都针对一种常见问题：在生成前预防、在乐谱阶段发现，或在音频中检测。团队在“标记问题”中发现的新问题可以不断补充进来。"
          : "Every check guards against one known failure mode — prevented before generation, caught in the score, or detected in the audio. New ones your team marks in Review can be added over time."}
      </p>
      <div className="mb-6"><Segmented value={stage} onChange={setStage} size="sm" options={[
        { value: "all", label: "All" }, { value: "pre", label: L === "zh" ? "写作" : "Writing" },
        { value: "plan", label: L === "zh" ? "乐谱" : "Score" }, { value: "audio", label: L === "zh" ? "音频" : "Audio" }]} /></div>
      <div className="flex flex-col gap-6">
        {Object.entries(grouped).sort().map(([g, list]) => (
          <Card key={g} className="p-5">
            <div className="text-[11px] uppercase tracking-[.14em] text-ink-3 mb-3">{g} · {GROUPS[g]?.[L]}</div>
            <ul className="grid grid-cols-2 gap-2">
              {list.map((r) => (
                <li key={r.id} className="rounded-xl border border-line px-3 py-2.5 flex items-start gap-3">
                  <span className="font-mono text-[11px] text-ink-3 mt-0.5 w-8">{r.catalog}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px]">{r.title[L]}</div>
                    <div className="flex gap-1.5 mt-1.5">
                      <Badge>{r.stage}</Badge>
                      <Badge tone={r.severity === "error" ? "bad" : r.severity === "warn" ? "warn" : "hint"}>{r.severity}</Badge>
                    </div>
                  </div>
                  <span className={cx("size-2 rounded-full mt-1.5")} style={{ background: GOAL_COLORS[r.goal] ?? "var(--ink-3)" }} />
                </li>
              ))}
            </ul>
          </Card>
        ))}
      </div>
    </div>
  );
}
