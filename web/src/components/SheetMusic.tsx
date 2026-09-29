import abcjs from "abcjs";
import { useEffect, useRef } from "react";

/** Engraved lead sheet (melody + instrumental line, chords, lyrics under notes).
 *  ``playhead`` (seconds) highlights the notes being played by the sketch player. */
export function SheetMusic({ abc, bpm, playhead }: { abc: string; bpm: number; playhead?: number | null }) {
  const host = useRef<HTMLDivElement>(null);
  const timings = useRef<{ ms: number; els: Element[] }[]>([]);
  const lit = useRef<Element[]>([]);

  useEffect(() => {
    if (!host.current || !abc) return;
    const tunes = abcjs.renderAbc(host.current, abc, {
      add_classes: true, responsive: "resize", staffwidth: 900, paddingleft: 0, paddingright: 0, paddingtop: 8,
      scale: 1.0, foregroundColor: "currentColor",
      format: { titlefont: "\"Instrument Serif\" 26", gchordfont: "Inter 12", annotationfont: "Inter 12 bold", vocalfont: "Inter 12" },
    } as abcjs.AbcVisualParams);
    try {
      const tc = new abcjs.TimingCallbacks(tunes[0], { qpm: bpm });
      timings.current = (tc.noteTimings ?? []).filter((e) => e.type === "event" && e.elements)
        .map((e) => ({ ms: e.milliseconds, els: (e.elements ?? []).flat() as Element[] }));
    } catch { timings.current = []; }
  }, [abc, bpm]);

  useEffect(() => {
    for (const el of lit.current) el.classList.remove("playing");
    lit.current = [];
    if (playhead == null || !timings.current.length) return;
    const ms = playhead * 1000;
    let lo = 0, hi = timings.current.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (timings.current[mid].ms <= ms) lo = mid; else hi = mid - 1; }
    const now = timings.current[lo];
    for (const el of now.els) el.classList.add("playing");
    lit.current = now.els;
    const first = now.els[0] as HTMLElement | undefined;
    first?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [playhead]);

  return <div ref={host} className="sheet text-ink" />;
}
