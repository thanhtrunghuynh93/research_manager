/**
 * Badges that keep the limits of the evidence visible beside whatever rests on them (UI-01, UI-05).
 *
 * Each of these exists because the same pixel-space would otherwise be filled by a number that
 * looks more certain than it is: a confidence level without its reasons, a rating whose evidence
 * has gone, a repository that is quiet because nobody synced it rather than because nobody worked.
 */
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

const TONES = {
  neutral: "bg-muted text-muted-foreground",
  good: "bg-emerald-50 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100",
  warn: "bg-amber-50 text-amber-900 dark:bg-amber-950 dark:text-amber-100",
  bad: "bg-rose-50 text-rose-900 dark:bg-rose-950 dark:text-rose-100",
} as const;

type Tone = keyof typeof TONES;

export function Badge({
  tone = "neutral",
  children,
  title,
  ...rest
}: {
  tone?: Tone;
  children: React.ReactNode;
  title?: string;
} & React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        TONES[tone],
      )}
      {...rest}
    >
      {children}
    </span>
  );
}

/** ASSESS-06: a level is meaningless without the rules that produced it, so they are the tooltip. */
export function ConfidenceBadge({
  confidence,
  reasons = [],
}: {
  confidence: string;
  reasons?: string[];
}) {
  const { t } = useTranslation();
  const tone: Tone = confidence === "high" ? "good" : confidence === "medium" ? "warn" : "bad";
  return (
    <Badge tone={tone} title={reasons.join("\n")} data-testid="confidence-badge">
      {t(`assessment.confidence.${confidence}`, { defaultValue: confidence })}
      {reasons.length > 0 ? ` · ${reasons.length}` : ""}
    </Badge>
  );
}

/** AC-04: a stale source is stale evidence. It is never rendered as an absence of work. */
export function FreshnessBadge({
  state,
  lastFinishedAt,
}: {
  state: string;
  lastFinishedAt?: string | null;
}) {
  const { t } = useTranslation();
  const stale = state !== "completed";
  return (
    <Badge tone={stale ? "warn" : "good"} data-testid="freshness-badge">
      {stale
        ? t("evidence.stale", { state })
        : t("evidence.fresh", { when: lastFinishedAt?.slice(0, 10) ?? "" })}
    </Badge>
  );
}

/**
 * ASSESS-04: an index that must not be shown reads as "Not rated", never as a zero and never as a
 * blank cell that the reader will fill in themselves.
 */
export function ProgressIndex({ value }: { value: number | null | undefined }) {
  const { t } = useTranslation();
  if (value === null || value === undefined) {
    return (
      <span className="text-sm text-muted-foreground" data-testid="progress-index">
        {t("assessment.notRated")}
      </span>
    );
  }
  return (
    <span className="text-sm font-semibold" data-testid="progress-index">
      {value}
      <span className="text-muted-foreground">/100</span>
    </span>
  );
}
