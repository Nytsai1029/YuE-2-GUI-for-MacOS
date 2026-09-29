import { Pause, Play } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin from "wavesurfer.js/dist/plugins/regions.esm.js";
import { fmtTime } from "./ui";

export interface Band { start: number; end: number; label: string; color: string }
export interface Marker { start: number; end: number; label: string; color: string; id?: string }
export interface WaveHandle { seek: (t: number) => void; toggle: () => void; time: () => number }

export const Waveform = forwardRef<WaveHandle, {
  url: string; bands?: Band[]; markers?: Marker[]; onSelect?: (start: number, end: number) => void;
  startAt?: number; onTime?: (t: number) => void;
}>(function Waveform({ url, bands = [], markers = [], onSelect, startAt = 0, onTime }, ref) {
  const host = useRef<HTMLDivElement>(null);
  const ws = useRef<WaveSurfer | null>(null);
  const regions = useRef<ReturnType<typeof RegionsPlugin.create> | null>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [dur, setDur] = useState(0);
  const [ready, setReady] = useState(false);
  const cb = useRef({ onSelect, onTime });
  cb.current = { onSelect, onTime };

  useEffect(() => {
    const css = getComputedStyle(document.documentElement);
    const accent = css.getPropertyValue("--accent").trim() || "#a78bfa";
    const reg = RegionsPlugin.create();
    const w = WaveSurfer.create({
      container: host.current!, url, height: 132, barWidth: 2, barGap: 1.5, barRadius: 3, normalize: true, cursorWidth: 2,
      waveColor: "rgba(160,166,190,.35)", progressColor: accent, cursorColor: "#fff", plugins: [reg], dragToSeek: true,
    });
    ws.current = w;
    regions.current = reg;
    w.on("ready", () => { setDur(w.getDuration()); setReady(true); if (startAt) w.setTime(Math.min(startAt, w.getDuration())); });
    w.on("timeupdate", (t) => { setTime(t); cb.current.onTime?.(t); });
    w.on("play", () => setPlaying(true));
    w.on("pause", () => setPlaying(false));
    w.on("finish", () => setPlaying(false));
    const off = reg.enableDragSelection({ color: "rgba(251,113,133,.22)" });
    reg.on("region-created", (r) => {
      if (r.id.startsWith("sel") || (!r.id.startsWith("band") && !r.id.startsWith("mk"))) {
        cb.current.onSelect?.(r.start, r.end);
        setTimeout(() => r.remove(), 50);
      }
    });
    return () => { off?.(); w.destroy(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  useEffect(() => {
    const reg = regions.current;
    if (!reg || !ready) return;
    for (const r of reg.getRegions()) if (r.id.startsWith("band") || r.id.startsWith("mk")) r.remove();
    bands.forEach((b, i) => {
      const label = document.createElement("div");
      label.textContent = b.label;
      label.style.cssText = `font:600 10px Inter;letter-spacing:.08em;text-transform:uppercase;color:${b.color};padding:4px 6px;`;
      reg.addRegion({ id: `band${i}`, start: b.start, end: b.end, color: `color-mix(in oklab, ${b.color} 10%, transparent)`, drag: false, resize: false, content: label });
    });
    markers.forEach((m, i) => {
      const el = document.createElement("div");
      el.title = m.label;
      el.style.cssText = `position:absolute;bottom:0;left:0;right:0;height:5px;background:${m.color};border-radius:3px;`;
      reg.addRegion({ id: `mk${i}`, start: m.start, end: Math.max(m.end, m.start + 0.3), color: `color-mix(in oklab, ${m.color} 16%, transparent)`, drag: false, resize: false, content: el });
    });
  }, [bands, markers, ready]);

  useImperativeHandle(ref, () => ({
    seek: (t) => { ws.current?.setTime(t); },
    toggle: () => { void ws.current?.playPause(); },
    time: () => ws.current?.getCurrentTime() ?? 0,
  }));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (e.code === "Space" && tag !== "INPUT" && tag !== "TEXTAREA" && !(e.target as HTMLElement)?.isContentEditable) {
        e.preventDefault(); void ws.current?.playPause();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex items-center gap-4">
      <button onClick={() => void ws.current?.playPause()} disabled={!ready}
        className="size-14 shrink-0 rounded-full grad-bg grid place-items-center text-white shadow-[0_10px_30px_-10px_var(--accent)] hover:scale-105 active:scale-95 transition disabled:opacity-50">
        {playing ? <Pause className="size-6 fill-current" /> : <Play className="size-6 fill-current translate-x-0.5" />}
      </button>
      <div className="flex-1 min-w-0">
        <div ref={host} className="w-full" />
        <div className="flex justify-between text-[11px] text-ink-3 tabular-nums mt-1"><span>{fmtTime(time)}</span><span>{fmtTime(dur)}</span></div>
      </div>
    </div>
  );
});
