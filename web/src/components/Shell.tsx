import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cpu, ListChecks, Music2, Plus, Settings2, Workflow } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api, type EngineInfo, type Job, type Song } from "../api";
import { useLive } from "../store";
import { cx, Tip } from "./ui";

export function EnginePill() {
  const { t } = useTranslation();
  const live = useLive((s) => s.engine);
  const { data } = useQuery({ queryKey: ["engine"], queryFn: () => api.get<EngineInfo>("/api/engine"), refetchInterval: 15000 });
  const status = live.status !== "stopped" ? live.status : data?.status ?? "stopped";
  const fake = data?.caps?.fake;
  const color = status === "error" ? "bg-bad" : status === "busy" || status === "loading" || status === "starting" ? "bg-warn" : status === "idle" ? "bg-good" : "bg-ink-3";
  return (
    <Tip content={live.detail || data?.detail || ""} side="right">
      <NavLink to="/settings" className="flex items-center gap-2.5 rounded-xl px-3 py-2 hover:bg-panel-2 transition-colors">
        <span className="relative flex size-2.5">
          {(status === "busy" || status === "loading") && <span className={cx("absolute inset-0 rounded-full animate-ping opacity-60", color)} />}
          <span className={cx("relative size-2.5 rounded-full", color)} />
        </span>
        <span className="text-xs text-ink-2 truncate">{t(`engine.${status}`, status)}{fake ? ` · ${t("engine.fake")}` : ""}</span>
      </NavLink>
    </Tip>
  );
}

export function Shell() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const qc = useQueryClient();
  const connected = useLive((s) => s.connected);
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => api.get<{ queue: Job[] }>("/api/jobs"), refetchInterval: 10000 });
  const newSong = useMutation({
    mutationFn: () => api.post<Song>("/api/songs", { title: "" }),
    onSuccess: (s) => { qc.invalidateQueries({ queryKey: ["songs"] }); nav(`/song/${s.id}`); },
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "n" && e.shiftKey) { e.preventDefault(); newSong.mutate(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [newSong]);
  const running = jobs.data?.queue?.length ?? 0;
  const item = "flex items-center gap-3 rounded-xl px-3 h-10 text-[14px] transition-colors";
  return (
    <div className="ambient h-full flex relative">
      <aside className="w-[232px] shrink-0 h-full flex flex-col border-r border-line bg-bg/60 backdrop-blur-xl z-10">
        <div className="px-5 pt-6 pb-5 flex items-center gap-3">
          <div className="size-9 rounded-xl grad-bg grid place-items-center shadow-[0_6px_24px_-6px_var(--accent)]">
            <Music2 className="size-5 text-white" />
          </div>
          <div className="leading-tight">
            <div className="font-display text-[22px] tracking-tight">YuE Studio</div>
            <div className="text-[10px] uppercase tracking-[.2em] text-ink-3">quality harness</div>
          </div>
        </div>
        <div className="px-3">
          <button onClick={() => newSong.mutate()} className="w-full h-10 rounded-xl grad-bg text-white text-sm font-medium flex items-center justify-center gap-2 shadow-[0_8px_30px_-10px_var(--accent)] hover:brightness-110 transition">
            <Plus className="size-4" /> {t("nav.newSong")}
          </button>
        </div>
        <nav className="px-3 mt-5 flex flex-col gap-1">
          <NavLink to="/" end className={({ isActive }) => cx(item, isActive ? "bg-panel-2 text-ink" : "text-ink-2 hover:text-ink hover:bg-panel")}>
            <Music2 className="size-4" /> {t("nav.library")}
          </NavLink>
          <NavLink to="/queue" className={({ isActive }) => cx(item, isActive ? "bg-panel-2 text-ink" : "text-ink-2 hover:text-ink hover:bg-panel")}>
            <Workflow className="size-4" /> {t("nav.queue")}
            {running > 0 && <span className="ml-auto text-[11px] rounded-full px-1.5 min-w-5 h-5 grid place-items-center grad-bg text-white">{running}</span>}
          </NavLink>
          <NavLink to="/checks" className={({ isActive }) => cx(item, isActive ? "bg-panel-2 text-ink" : "text-ink-2 hover:text-ink hover:bg-panel")}>
            <ListChecks className="size-4" /> {t("nav.catalog")}
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => cx(item, isActive ? "bg-panel-2 text-ink" : "text-ink-2 hover:text-ink hover:bg-panel")}>
            <Settings2 className="size-4" /> {t("nav.settings")}
          </NavLink>
        </nav>
        <div className="mt-auto p-3 flex flex-col gap-1">
          {!connected && <div className="text-[11px] text-warn px-3 flex items-center gap-2"><Cpu className="size-3.5" /> reconnecting…</div>}
          <EnginePill />
        </div>
      </aside>
      <main className="flex-1 min-w-0 h-full overflow-auto relative z-[1]">
        <Outlet />
      </main>
    </div>
  );
}
