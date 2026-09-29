import { create } from "zustand";
import type { QueryClient } from "@tanstack/react-query";

export interface LiveProgress {
  stage: string; detail?: string; done?: number | null; total?: number | null; eta?: number | null; rate?: number; t: number;
  status?: string; candidate_id?: string;
}

interface LiveState {
  engine: { status: string; detail?: string };
  takes: Record<string, LiveProgress>;
  connected: boolean;
  setEngine: (e: { status: string; detail?: string }) => void;
  setTake: (id: string, p: LiveProgress) => void;
  setConnected: (c: boolean) => void;
}

export const useLive = create<LiveState>((set) => ({
  engine: { status: "stopped" },
  takes: {},
  connected: false,
  setEngine: (engine) => set({ engine }),
  setTake: (id, p) => set((s) => ({ takes: { ...s.takes, [id]: { ...s.takes[id], ...p } } })),
  setConnected: (connected) => set({ connected }),
}));

/** One EventSource for the whole app; progress goes to the store, results invalidate queries. */
export function connectEvents(qc: QueryClient) {
  let es: EventSource | null = null;
  let retry = 1000;
  let timer: number | undefined;
  const invalidateTake = (takeId?: string) => {
    if (takeId) qc.invalidateQueries({ queryKey: ["take", takeId] });
  };
  const open = () => {
    es = new EventSource("/api/events");
    es.onopen = () => { retry = 1000; useLive.getState().setConnected(true); };
    es.onerror = () => {
      useLive.getState().setConnected(false);
      es?.close();
      timer = window.setTimeout(open, retry);
      retry = Math.min(retry * 2, 15000);
    };
    es.addEventListener("engine", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      if (d.kind === "engine") useLive.getState().setEngine({ status: d.status, detail: d.detail });
    });
    es.addEventListener("take", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      useLive.getState().setTake(d.take_id, d);
      if (["done", "failed", "cancelled", "plan_chosen"].includes(d.stage)) {
        invalidateTake(d.take_id);
        qc.invalidateQueries({ queryKey: ["songs"] });
        qc.invalidateQueries({ queryKey: ["song"] });
      }
    });
    for (const topic of ["plan", "candidate"]) {
      es.addEventListener(topic, (e) => invalidateTake(JSON.parse((e as MessageEvent).data).take_id));
    }
    es.addEventListener("job", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      qc.invalidateQueries({ queryKey: ["jobs"] });
      invalidateTake(d.take_id);
      if (d.state === "queued" || d.state === "running") useLive.getState().setTake(d.take_id, { stage: d.state === "queued" ? "queued" : "plan", t: Date.now() / 1000 });
    });
  };
  open();
  return () => { es?.close(); window.clearTimeout(timer); };
}

interface UiState { theme: string; setTheme: (t: string) => void }
const initialTheme = (() => { try { return localStorage.getItem("ys.theme") || "dark"; } catch { return "dark"; } })();
export const useUi = create<UiState>((set) => ({
  theme: initialTheme,
  setTheme: (theme) => {
    try { localStorage.setItem("ys.theme", theme); } catch { /* ignore */ }
    applyTheme(theme);
    set({ theme });
  },
}));

export function applyTheme(theme: string) {
  const light = theme === "light" || (theme === "system" && window.matchMedia("(prefers-color-scheme: light)").matches);
  document.documentElement.classList.toggle("light", light);
  document.documentElement.classList.toggle("dark", !light);
}
