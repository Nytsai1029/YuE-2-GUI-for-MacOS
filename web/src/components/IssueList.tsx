import { CheckCircle2, Wrench } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useTranslation } from "react-i18next";
import type { Fix, Issue } from "../api";
import { lang } from "../i18n";
import { cx, GOAL_COLORS, SeverityDot, Tip } from "./ui";

export function IssueList({ issues, onJump, onFix, empty, compact }:
  { issues: Issue[]; onJump?: (i: Issue) => void; onFix?: (f: Fix) => void; empty?: string; compact?: boolean }) {
  const { t } = useTranslation();
  const L = lang();
  if (!issues.length) {
    return (
      <div className="flex items-center gap-2 text-sm text-good py-3">
        <CheckCircle2 className="size-4" /> {empty ?? t("write.noIssues")}
      </div>
    );
  }
  return (
    <ul className="flex flex-col gap-1.5">
      <AnimatePresence initial={false}>
        {issues.map((is, i) => (
          <motion.li key={`${is.rule}-${is.line ?? ""}-${is.time?.[0] ?? ""}-${i}`} layout initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, height: 0 }}
            className={cx("group rounded-xl border border-line bg-panel-2/60 hover:border-line-2 transition-colors", compact ? "px-2.5 py-2" : "px-3 py-2.5")}>
            <div className="flex items-start gap-2.5">
              <span className="mt-1.5"><SeverityDot severity={is.severity} /></span>
              <button type="button" className="text-left flex-1 min-w-0" onClick={() => onJump?.(is)}>
                <div className="text-[13px] leading-snug text-ink">{is.message[L]}</div>
                <div className="mt-1 flex items-center gap-2 text-[11px] text-ink-3">
                  <Tip content={is.rule}><span className="font-mono">{is.catalog}</span></Tip>
                  <span className="size-1 rounded-full" style={{ background: GOAL_COLORS[is.goal] ?? "var(--ink-3)" }} />
                  <span>{t(`goals.${is.goal}`, is.goal)}</span>
                  {is.line != null && <span>· L{is.line + 1}</span>}
                  {is.time && <span>· {Math.floor(is.time[0] / 60)}:{String(Math.floor(is.time[0] % 60)).padStart(2, "0")}</span>}
                </div>
              </button>
              {is.fix && onFix && (
                <button type="button" onClick={() => onFix(is.fix!)}
                  title={is.fix.label[L]}
                  className="shrink-0 max-w-[132px] h-7 px-2.5 rounded-lg text-[12px] bg-accent/15 text-accent border border-accent/30 hover:bg-accent/25 flex items-center gap-1 transition">
                  <Wrench className="size-3 shrink-0" /><span className="truncate">{is.fix.label[L]}</span>
                </button>
              )}
            </div>
          </motion.li>
        ))}
      </AnimatePresence>
    </ul>
  );
}
