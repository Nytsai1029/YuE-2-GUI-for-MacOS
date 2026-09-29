import { useMemo } from "react";

function rng(seed: number) {
  let s = seed >>> 0 || 1;
  return () => {
    s ^= s << 13; s ^= s >>> 17; s ^= s << 5;
    return ((s >>> 0) % 10000) / 10000;
  };
}

const PALETTES = [
  ["#a78bfa", "#fb7185", "#fbbf24"], ["#38bdf8", "#a78bfa", "#f472b6"], ["#34d399", "#38bdf8", "#818cf8"],
  ["#f97316", "#fb7185", "#c084fc"], ["#facc15", "#fb923c", "#f43f5e"], ["#2dd4bf", "#a3e635", "#38bdf8"],
  ["#e879f9", "#818cf8", "#22d3ee"], ["#fda4af", "#fcd34d", "#a78bfa"],
];

/** Deterministic generative cover: soft gradient orbs + a waveform line, unique per song. */
export function CoverArt({ seed, title, className, size = 400 }: { seed: number; title?: string; className?: string; size?: number }) {
  const art = useMemo(() => {
    const r = rng(seed);
    const pal = PALETTES[Math.floor(r() * PALETTES.length)];
    const orbs = Array.from({ length: 4 }, (_, i) => ({ x: r() * 100, y: r() * 100, rad: 35 + r() * 45, c: pal[i % 3], o: .55 + r() * .4 }));
    const pts: string[] = [];
    const amp = 6 + r() * 10, freq = 2 + r() * 4, phase = r() * 6;
    for (let i = 0; i <= 60; i++) {
      const x = (i / 60) * 100;
      const y = 72 + Math.sin(i / 60 * Math.PI * freq + phase) * amp * Math.sin(i / 60 * Math.PI);
      pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
    }
    return { pal, orbs, pts: pts.join(" "), angle: Math.floor(r() * 360) };
  }, [seed]);
  const id = `c${seed}`;
  return (
    <svg viewBox="0 0 100 100" className={className} width={size} height={size} preserveAspectRatio="xMidYMid slice" aria-label={title}>
      <defs>
        <linearGradient id={`${id}bg`} gradientTransform={`rotate(${art.angle} .5 .5)`}>
          <stop offset="0" stopColor="#0f1016" /><stop offset="1" stopColor="#1c1d27" />
        </linearGradient>
        <filter id={`${id}blur`} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="9" /></filter>
        <filter id={`${id}grain`}>
          <feTurbulence type="fractalNoise" baseFrequency="1.4" numOctaves="2" seed={seed % 100} />
          <feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .06 0" />
        </filter>
      </defs>
      <rect width="100" height="100" fill={`url(#${id}bg)`} />
      <g filter={`url(#${id}blur)`}>
        {art.orbs.map((o, i) => <circle key={i} cx={o.x} cy={o.y} r={o.rad / 2} fill={o.c} opacity={o.o} />)}
      </g>
      <polyline points={art.pts} fill="none" stroke="white" strokeOpacity=".75" strokeWidth=".8" strokeLinecap="round" />
      <rect width="100" height="100" filter={`url(#${id}grain)`} />
    </svg>
  );
}
