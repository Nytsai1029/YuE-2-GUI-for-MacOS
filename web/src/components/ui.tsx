import * as Dialog from "@radix-ui/react-dialog";
import * as RSlider from "@radix-ui/react-slider";
import * as RSwitch from "@radix-ui/react-switch";
import * as RTooltip from "@radix-ui/react-tooltip";
import clsx from "clsx";
import { Loader2, X } from "lucide-react";
import { motion } from "motion/react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { Scorecard, Severity } from "../api";

export const cx = clsx;

type Variant = "primary" | "ghost" | "soft" | "danger" | "outline";
export function Button({ variant = "soft", size = "md", loading, icon, className, children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "lg"; loading?: boolean; icon?: ReactNode }) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all select-none whitespace-nowrap",
        "disabled:opacity-45 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        size === "sm" && "h-8 px-3 text-[13px]", size === "md" && "h-10 px-4 text-sm", size === "lg" && "h-12 px-6 text-[15px]",
        variant === "primary" && "grad-bg text-white shadow-[0_8px_30px_-8px_var(--accent)] hover:brightness-110 active:scale-[.98]",
        variant === "soft" && "bg-panel-2 border border-line hover:border-line-2 text-ink",
        variant === "ghost" && "text-ink-2 hover:text-ink hover:bg-panel-2",
        variant === "outline" && "border border-line-2 text-ink hover:bg-panel-2",
        variant === "danger" && "bg-bad/15 text-bad border border-bad/30 hover:bg-bad/25",
        className,
      )}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return <div {...rest} className={cx("glass rounded-2xl", className)}>{children}</div>;
}

export function SectionTitle({ children, right, className }: { children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <div className={cx("flex items-center justify-between gap-3 mb-3", className)}>
      <h3 className="text-[11px] font-semibold uppercase tracking-[.14em] text-ink-3">{children}</h3>
      {right}
    </div>
  );
}

export function Badge({ tone = "neutral", children, className }: { tone?: "neutral" | "good" | "warn" | "bad" | "accent" | "hint"; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium border",
      tone === "neutral" && "bg-panel-2 border-line text-ink-2",
      tone === "good" && "bg-good/12 border-good/30 text-good",
      tone === "warn" && "bg-warn/12 border-warn/30 text-warn",
      tone === "bad" && "bg-bad/12 border-bad/30 text-bad",
      tone === "hint" && "bg-hint/12 border-hint/30 text-hint",
      tone === "accent" && "bg-accent/15 border-accent/30 text-accent", className)}>
      {children}
    </span>
  );
}

export function Chip({ active, onClick, children, color }: { active?: boolean; onClick?: () => void; children: ReactNode; color?: string }) {
  return (
    <button type="button" onClick={onClick}
      style={active && color ? { borderColor: color, color, background: `color-mix(in oklab, ${color} 14%, transparent)` } : undefined}
      className={cx("rounded-full px-3 h-8 text-[13px] border transition-all",
        active ? "border-accent/60 bg-accent/15 text-ink" : "border-line text-ink-2 hover:text-ink hover:border-line-2")}>
      {children}
    </button>
  );
}

export function Segmented<T extends string>({ value, options, onChange, size = "md" }:
  { value: T; options: { value: T; label: ReactNode; hint?: string }[]; onChange: (v: T) => void; size?: "sm" | "md" }) {
  return (
    <div className="inline-flex rounded-xl bg-panel-2 border border-line p-1 relative">
      {options.map((o) => (
        <button key={o.value} type="button" title={o.hint} onClick={() => onChange(o.value)}
          className={cx("relative rounded-lg transition-colors z-10", size === "sm" ? "px-2.5 h-7 text-xs" : "px-3.5 h-8 text-[13px]",
            value === o.value ? "text-ink" : "text-ink-3 hover:text-ink-2")}>
          {value === o.value && (
            <motion.span layoutId={`seg-${options.map((x) => x.value).join("")}`} className="absolute inset-0 rounded-lg bg-bg-2 border border-line-2 shadow-sm -z-10"
              transition={{ type: "spring", stiffness: 500, damping: 38 }} />
          )}
          {o.label}
        </button>
      ))}
    </div>
  );
}

export const GOAL_COLORS: Record<string, string> = {
  lyrics: "var(--color-lyrics)", variety: "var(--color-variety)", harmony: "var(--color-harmony)", singing: "var(--color-singing)",
};

export function GoalMeters({ card, compact }: { card?: Scorecard | null; compact?: boolean }) {
  const { t } = useTranslation();
  if (!card) return null;
  return (
    <div className={cx("grid gap-x-4 gap-y-2", compact ? "grid-cols-2" : "grid-cols-1")}>
      {(["lyrics", "singing", "variety", "harmony"] as const).map((g) => (
        <div key={g} className="flex items-center gap-2 min-w-0">
          <span className="text-[11px] text-ink-3 w-14 shrink-0">{t(`goals.${g}`)}</span>
          <div className="h-1.5 flex-1 rounded-full bg-line overflow-hidden">
            <motion.div className="h-full rounded-full" style={{ background: GOAL_COLORS[g] }}
              initial={{ width: 0 }} animate={{ width: `${Math.max(3, card[g] ?? 0)}%` }} transition={{ duration: .7, ease: "easeOut" }} />
          </div>
          <span className="text-[11px] tabular-nums text-ink-2 w-7 text-right">{Math.round(card[g] ?? 0)}</span>
        </div>
      ))}
    </div>
  );
}

export function ScoreRing({ value, size = 44, passed }: { value: number | null | undefined; size?: number; passed?: boolean }) {
  const v = Math.max(0, Math.min(100, value ?? 0));
  const r = size / 2 - 4, c = 2 * Math.PI * r;
  const color = passed === false ? "var(--color-warn)" : v >= 80 ? "var(--color-good)" : v >= 60 ? "var(--accent)" : "var(--color-warn)";
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--line-2)" strokeWidth="3.5" fill="none" />
        <motion.circle cx={size / 2} cy={size / 2} r={r} stroke={color} strokeWidth="3.5" fill="none" strokeLinecap="round"
          strokeDasharray={c} initial={{ strokeDashoffset: c }} animate={{ strokeDashoffset: c * (1 - v / 100) }} transition={{ duration: .8 }} />
      </svg>
      <span className="absolute inset-0 grid place-items-center text-[12px] font-semibold tabular-nums">{value == null ? "–" : Math.round(v)}</span>
    </div>
  );
}

export function SeverityDot({ severity }: { severity: Severity }) {
  return <span className={cx("inline-block size-2 rounded-full shrink-0",
    severity === "error" ? "bg-bad" : severity === "warn" ? "bg-warn" : "bg-hint")} />;
}

export function Tip({ content, children, side = "top" }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  if (!content) return <>{children}</>;
  return (
    <RTooltip.Root delayDuration={250}>
      <RTooltip.Trigger asChild>{children}</RTooltip.Trigger>
      <RTooltip.Portal>
        <RTooltip.Content side={side} sideOffset={6}
          className="z-50 max-w-xs rounded-lg bg-panel-2 border border-line-2 px-2.5 py-1.5 text-xs text-ink shadow-xl backdrop-blur-xl">
          {content}
        </RTooltip.Content>
      </RTooltip.Portal>
    </RTooltip.Root>
  );
}

export function Modal({ open, onOpenChange, title, children, width = 560 }:
  { open: boolean; onOpenChange: (o: boolean) => void; title: ReactNode; children: ReactNode; width?: number }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm data-[state=open]:animate-in" />
        <Dialog.Content style={{ width: `min(${width}px, calc(100vw - 32px))` }}
          className="fixed z-50 left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 max-h-[85vh] overflow-auto rounded-2xl glass p-6 shadow-2xl">
          <div className="flex items-start justify-between mb-4">
            <Dialog.Title className="text-lg font-semibold">{title}</Dialog.Title>
            <Dialog.Close className="text-ink-3 hover:text-ink"><X className="size-5" /></Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function Slider({ value, min, max, step = 1, onChange }: { value: number; min: number; max: number; step?: number; onChange: (v: number) => void }) {
  return (
    <RSlider.Root value={[value]} min={min} max={max} step={step} onValueChange={(v) => onChange(v[0])}
      className="relative flex items-center select-none touch-none h-5 w-full">
      <RSlider.Track className="relative grow h-1.5 rounded-full bg-line-2">
        <RSlider.Range className="absolute h-full rounded-full grad-bg" />
      </RSlider.Track>
      <RSlider.Thumb className="block size-4 rounded-full bg-white shadow ring-4 ring-accent/25 focus:outline-none" />
    </RSlider.Root>
  );
}

export function Switch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <RSwitch.Root checked={checked} onCheckedChange={onChange}
      className={cx("w-10 h-6 rounded-full relative transition-colors", checked ? "grad-bg" : "bg-line-2")}>
      <RSwitch.Thumb className="block size-5 rounded-full bg-white shadow transition-transform translate-x-0.5 data-[state=checked]:translate-x-[18px]" />
    </RSwitch.Root>
  );
}

export function Empty({ icon, title, hint, action }: { icon?: ReactNode; title: ReactNode; hint?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-6 gap-3">
      {icon && <div className="size-14 rounded-2xl grid place-items-center bg-panel-2 border border-line text-ink-2">{icon}</div>}
      <div className="text-base font-medium">{title}</div>
      {hint && <div className="text-sm text-ink-3 max-w-md">{hint}</div>}
      {action}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("size-4 animate-spin text-ink-3", className)} />;
}

export function fmtTime(s: number | null | undefined) {
  if (s == null || !isFinite(s)) return "–";
  const m = Math.floor(s / 60), r = Math.floor(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
}

export function fmtEta(s: number | null | undefined) {
  if (s == null || !isFinite(s)) return "";
  if (s < 60) return `${Math.max(1, Math.round(s))}s`;
  return `${Math.round(s / 60)} min`;
}
