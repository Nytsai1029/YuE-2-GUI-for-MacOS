/** Instant score audition in the browser: melody, instrumental line, chord pad and bass
 *  synthesised with Web Audio — no soundfont download, works offline. */
export interface SketchNotes {
  bpm: number; seconds: number;
  vocal: [number, number, number][]; ins: [number, number, number][];
  chords: [number, number, string, number[], number][];
}

const hz = (m: number) => 440 * Math.pow(2, (m - 69) / 12);

export class Sketch {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private started = 0;
  private offset = 0;
  private raf = 0;
  playing = false;
  onTime?: (t: number) => void;
  onEnd?: () => void;

  private voice(dest: AudioNode, at: number, dur: number, freq: number, type: OscillatorType, gain: number, attack = 0.015, release = 0.08, vibrato = 0) {
    const ctx = this.ctx!;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    if (vibrato) {
      const lfo = ctx.createOscillator();
      const depth = ctx.createGain();
      lfo.frequency.value = 5.4;
      depth.gain.value = freq * vibrato;
      lfo.connect(depth).connect(osc.frequency);
      lfo.start(at + 0.15);
      lfo.stop(at + dur + release);
    }
    g.gain.setValueAtTime(0, at);
    g.gain.linearRampToValueAtTime(gain, at + attack);
    g.gain.setValueAtTime(gain, Math.max(at + attack, at + dur - release));
    g.gain.linearRampToValueAtTime(0, at + dur + release);
    osc.connect(g).connect(dest);
    osc.start(at);
    osc.stop(at + dur + release + 0.05);
  }

  play(notes: SketchNotes, from = 0, opts: { vocal?: boolean; ins?: boolean; chords?: boolean } = {}) {
    this.stop();
    const ctx = (this.ctx ??= new AudioContext());
    void ctx.resume();
    this.master = ctx.createGain();
    this.master.gain.value = 0.9;
    const comp = ctx.createDynamicsCompressor();
    this.master.connect(comp).connect(ctx.destination);
    const lp = ctx.createBiquadFilter();
    lp.type = "lowpass"; lp.frequency.value = 1600;
    lp.connect(this.master);
    const t0 = ctx.currentTime + 0.08;
    const when = (t: number) => t0 + t - from;
    if (opts.chords !== false) for (const [t, d, , pitches, bass] of notes.chords) {
      if (t + d < from) continue;
      const s = Math.max(t, from);
      for (const p of pitches) this.voice(lp, when(s), t + d - s, hz(p + 12), "sawtooth", 0.018, 0.12, 0.25);
      this.voice(this.master, when(s), t + d - s, hz(bass), "sine", 0.12, 0.02, 0.1);
    }
    if (opts.ins !== false) for (const [t, d, p] of notes.ins) if (t >= from) this.voice(this.master, when(t), d, hz(p), "square", 0.02, 0.005, 0.05);
    if (opts.vocal !== false) for (const [t, d, p] of notes.vocal) if (t >= from) this.voice(this.master, when(t), d, hz(p), "triangle", 0.2, 0.02, 0.06, 0.006);
    this.started = t0;
    this.offset = from;
    this.playing = true;
    const tick = () => {
      if (!this.playing || !this.ctx) return;
      const now = this.ctx.currentTime - this.started + this.offset;
      this.onTime?.(now);
      if (now > notes.seconds + 0.3) { this.stop(); this.onEnd?.(); return; }
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  stop() {
    this.playing = false;
    cancelAnimationFrame(this.raf);
    if (this.master && this.ctx) {
      const g = this.master.gain;
      g.cancelScheduledValues(this.ctx.currentTime);
      g.setValueAtTime(g.value, this.ctx.currentTime);
      g.linearRampToValueAtTime(0, this.ctx.currentTime + 0.05);
      const m = this.master;
      setTimeout(() => m.disconnect(), 120);
    }
    this.master = null;
  }
}
