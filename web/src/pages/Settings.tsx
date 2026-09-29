import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Cpu, Download, FolderOpen, Info, Loader2, Power, ScanSearch, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type EngineInfo, type Settings } from "../api";
import { EnginePill } from "../components/Shell";
import { Badge, Button, Card, SectionTitle, Segmented, Slider, Switch } from "../components/ui";
import { setLanguage } from "../i18n";
import { useUi } from "../store";

interface Detected {
  mlx_yue_dir: string | null; python: string | null; python_info: { python?: string; lyra?: boolean; mlx_yue?: string; mlx?: string; error?: string } | null;
  models: { path: string; precisions: string[]; converted: boolean }[]; vaes: string[]; notes: string[];
}

function PathField({ label, value, onChange, prompt }: { label: string; value: string; onChange: (v: string) => void; prompt: string }) {
  const { t } = useTranslation();
  const pick = useMutation({ mutationFn: () => api.post<{ path: string | null }>("/api/system/pick-folder", { prompt }),
    onSuccess: (r) => r.path && onChange(r.path) });
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[12px] text-ink-2">{label}</span>
      <div className="flex gap-2">
        <input value={value} onChange={(e) => onChange(e.target.value)} placeholder="/Users/you/…" spellCheck={false}
          className="flex-1 h-10 rounded-xl bg-panel-2 border border-line px-3 text-sm font-mono outline-none focus:border-accent/60" />
        <Button variant="soft" icon={<FolderOpen className="size-4" />} onClick={() => pick.mutate()} loading={pick.isPending}>{t("settings.choose")}</Button>
      </div>
    </label>
  );
}

export function SettingsPage() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings>("/api/settings") });
  const engine = useQuery({ queryKey: ["engine"], queryFn: () => api.get<EngineInfo>("/api/engine"), refetchInterval: 4000 });
  const system = useQuery({ queryKey: ["system"], queryFn: () => api.get<{ asr: string | null; ffmpeg: boolean; data_dir: string; version: string }>("/api/system") });
  const [draft, setDraft] = useState<Settings | null>(null);
  const [detected, setDetected] = useState<Detected | null>(null);
  useEffect(() => { if (settings.data && !draft) setDraft(settings.data); }, [settings.data, draft]);
  const save = useMutation({ mutationFn: (s: Partial<Settings>) => api.put<Settings>("/api/settings", s),
    onSuccess: (s) => { setDraft(s); qc.setQueryData(["settings"], s); qc.invalidateQueries({ queryKey: ["engine"] }); } });
  const detect = useMutation({ mutationFn: () => api.post<Detected>("/api/engine/detect", { mlx_yue_dir: draft?.engine.mlx_yue_dir || null }),
    onSuccess: (d) => {
      setDetected(d);
      if (!draft) return;
      const e = { ...draft.engine };
      if (d.mlx_yue_dir && !e.mlx_yue_dir) e.mlx_yue_dir = d.mlx_yue_dir;
      if (d.models[0] && !e.model_dir) { e.model_dir = d.models[0].path; if (!d.models[0].precisions.includes(e.precision)) e.precision = d.models[0].precisions[0]; }
      if (d.vaes[0] && !e.vae_dir) e.vae_dir = d.vaes[0];
      setDraft({ ...draft, engine: e });
    } });
  const load = useMutation({ mutationFn: async () => { await api.put("/api/settings", { engine: draft!.engine }); return api.post("/api/engine/load"); },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["engine"] }) });
  const unload = useMutation({ mutationFn: () => api.post("/api/engine/unload"), onSuccess: () => qc.invalidateQueries({ queryKey: ["engine"] }) });
  if (!draft) return null;
  const e = draft.engine;
  const setE = (patch: Partial<Settings["engine"]>) => setDraft({ ...draft, engine: { ...e, ...patch } });
  const dirty = JSON.stringify(draft) !== JSON.stringify(settings.data);
  const precisions = detected?.models.find((m) => m.path === e.model_dir)?.precisions ?? ["bf16", "8bit", "4bit"];

  return (
    <div className="max-w-4xl mx-auto px-10 py-10 pb-28">
      <div className="flex items-end justify-between mb-8">
        <h1 className="font-display text-5xl">{t("settings.title")}</h1>
        {dirty && <Button variant="primary" onClick={() => save.mutate(draft)} loading={save.isPending}>{t("review.save")}</Button>}
      </div>

      <Card className="p-6 mb-6">
        <SectionTitle right={<EnginePill />}><span className="flex items-center gap-2"><Cpu className="size-4" />{t("settings.engine")}</span></SectionTitle>
        <p className="text-sm text-ink-2 mb-5">{t("settings.engineHint")}</p>
        <div className="mb-5">
          <Segmented value={e.mode} onChange={(v) => setE({ mode: v })} options={[{ value: "real", label: t("settings.real") }, { value: "fake", label: t("settings.fake") }]} />
        </div>
        {e.mode === "real" && (
          <div className="flex flex-col gap-4">
            <PathField label={t("settings.mlxYue")} value={e.mlx_yue_dir} onChange={(v) => setE({ mlx_yue_dir: v })} prompt="Choose your mlx-Yue folder (it contains .venv)" />
            <div className="flex items-center gap-3">
              <Button variant="soft" icon={<ScanSearch className="size-4" />} onClick={() => detect.mutate()} loading={detect.isPending}>{t("settings.detect")}</Button>
              {detected?.python_info && (detected.python_info.lyra
                ? <Badge tone="good"><CheckCircle2 className="size-3" />lyra OK · Python {detected.python_info.python} · mlx {detected.python_info.mlx}</Badge>
                : <Badge tone="bad"><TriangleAlert className="size-3" />{detected.python_info.error ?? "lyra not importable"}</Badge>)}
            </div>
            {detected?.notes.map((n) => <div key={n} className="text-[12px] text-warn flex gap-2"><Info className="size-3.5 mt-0.5" />{n}</div>)}
            <PathField label={t("settings.model")} value={e.model_dir} onChange={(v) => setE({ model_dir: v })} prompt="Choose the converted mlx-Yue2-3B model folder" />
            {detected?.models.length ? (
              <div className="flex flex-wrap gap-1.5 -mt-2">
                {detected.models.map((m) => (
                  <button key={m.path} onClick={() => setE({ model_dir: m.path })} className="text-[11px] rounded-full border border-line px-2.5 py-1 hover:border-accent/50 font-mono truncate max-w-full">
                    {m.path.split("/").slice(-3).join("/")} · {m.precisions.join("/")}
                  </button>
                ))}
              </div>
            ) : null}
            <PathField label={t("settings.vae")} value={e.vae_dir} onChange={(v) => setE({ vae_dir: v })} prompt="Choose the YuE2-Vae folder" />
            <div className="flex items-center gap-6">
              <label className="flex items-center gap-3 text-sm">{t("settings.precision")}
                <Segmented value={e.precision} onChange={(v) => setE({ precision: v })} size="sm" options={precisions.map((p) => ({ value: p, label: p }))} />
              </label>
              <label className="flex items-center gap-3 text-sm">{t("settings.memory")}
                <input type="number" value={e.memory_budget_gib ?? ""} placeholder="auto" onChange={(ev) => setE({ memory_budget_gib: ev.target.value ? Number(ev.target.value) : null })}
                  className="w-20 h-8 rounded-lg bg-panel-2 border border-line px-2 text-sm" />
              </label>
            </div>
          </div>
        )}
        <div className="flex items-center gap-2 mt-6 pt-5 border-t border-line">
          <Button variant="primary" icon={load.isPending ? <Loader2 className="size-4 animate-spin" /> : <Power className="size-4" />} onClick={() => load.mutate()}>{t("settings.test")}</Button>
          <Button variant="ghost" onClick={() => unload.mutate()}>{t("settings.unload")}</Button>
          <span className="text-[12px] text-ink-3 ml-2 truncate">{engine.data?.detail}</span>
        </div>
        {engine.data?.status === "error" && engine.data && (
          <pre className="mt-3 max-h-40 overflow-auto text-[11px] text-bad bg-bad/5 rounded-lg p-3 whitespace-pre-wrap">{(engine.data as unknown as { stderr_tail?: string }).stderr_tail}</pre>
        )}
      </Card>

      <Card className="p-6 mb-6">
        <SectionTitle>{t("settings.quality")}</SectionTitle>
        <div className="grid grid-cols-2 gap-6">
          <div className="flex items-center justify-between">
            <span className="text-sm">{t("settings.asr")} <span className="text-[11px] text-ink-3">{system.data?.asr ?? "not installed"}</span></span>
            <Switch checked={draft.asr.enabled} onChange={(v) => setDraft({ ...draft, asr: { ...draft.asr, enabled: v } })} />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm">{t("settings.mastering")}</span>
            <Switch checked={draft.mastering.enabled} onChange={(v) => setDraft({ ...draft, mastering: { ...draft.mastering, enabled: v } })} />
          </div>
          <label className="flex flex-col gap-2 col-span-2">
            <span className="text-sm flex justify-between">{t("settings.lufs")}<span className="tabular-nums text-ink-2">{draft.mastering.lufs} LUFS</span></span>
            <Slider value={draft.mastering.lufs} min={-20} max={-8} step={0.5} onChange={(v) => setDraft({ ...draft, mastering: { ...draft.mastering, lufs: v } })} />
          </label>
        </div>
      </Card>

      <Card className="p-6 mb-6">
        <SectionTitle>{t("settings.language")} · {t("settings.theme")}</SectionTitle>
        <div className="flex gap-6 flex-wrap">
          <Segmented value={i18n.language.startsWith("zh") ? "zh" : "en"} onChange={(v) => setLanguage(v)} options={[{ value: "en", label: "English" }, { value: "zh", label: "简体中文" }]} />
          <Segmented value={theme} onChange={setTheme} options={[{ value: "dark", label: t("settings.dark") }, { value: "light", label: t("settings.light") }, { value: "system", label: t("settings.system") }]} />
        </div>
      </Card>

      <Card className="p-6">
        <SectionTitle>About</SectionTitle>
        <p className="text-sm text-ink-2 leading-relaxed">{t("settings.license")}</p>
        <div className="flex items-center gap-3 mt-4 text-[12px] text-ink-3">
          <span>v{system.data?.version}</span><span>·</span><span className="font-mono truncate">{system.data?.data_dir}</span>
          <span>·</span><span>ffmpeg {system.data?.ffmpeg ? "✓" : "✗"}</span>
          <a href="/api/diagnostics" className="ml-auto"><Button size="sm" variant="soft" icon={<Download className="size-3.5" />}>{t("settings.diagnostics")}</Button></a>
        </div>
      </Card>
    </div>
  );
}
