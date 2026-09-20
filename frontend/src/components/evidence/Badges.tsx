/**
 * Badges that keep the limits of the evidence visible beside whatever rests on them (UI-01, UI-05).
 *
 * Each of these exists because the same pixel-space would otherwise be filled by a number that
 * looks more certain than it is: a confidence level without its reasons, a rating whose evidence
 * has gone, a repository that is quiet because nobody synced it rather than because nobody worked.
 *
 * They are set in mono and upper case because they are the system speaking, not the author.
 */
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

const TONES = {
  neutral: "chip-neutral",
  good: "chip-good",
  warn: "chip-warn",
  bad: "chip-bad",
} as const;

type Tone = keyof typeof TONES;

export function Badge({
  tone = "neutral",
  children,
  title,
  className,
  ...rest
}: {
  tone?: Tone;
  children: React.ReactNode;
  title?: string;
} & React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span title={title} className={cn("chip uppercase", TONES[tone], className)} {...rest}>
      {children}
    </span>
  );
}

/**
 * ASSESS-06: the level, and how many rules produced it.
 *
 * The count is a pointer, not the explanation — `ConfidenceReasons` is the explanation, and every
 * screen showing this badge should show that too. The reasons used to be this badge's `title`,
 * which meant they did not exist on a touch device, were not announced as content by a screen
 * reader, and left "LOW CONFIDENCE · 2" as the whole of what a reader could find out.
 */
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
    <Badge tone={tone} data-testid="confidence-badge">
      {t(`assessment.confidence.${confidence}`, { defaultValue: confidence })}
      {reasons.length > 0 ? ` · ${reasons.length}` : ""}
    </Badge>
  );
}

/** The rules behind a confidence level, as text on the page rather than on hover. */
export function ConfidenceReasons({
  reasons = [],
  className,
}: {
  reasons?: string[];
  className?: string;
}) {
  if (reasons.length === 0) return null;
  return (
    <ul className={cn("mt-1", className)} data-testid="confidence-reasons">
      {reasons.map((reason) => (
        <li key={reason} className="text-[12.5px] leading-relaxed text-muted-foreground">
          {reason}
        </li>
      ))}
    </ul>
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
 * blank cell that the reader will fill in themselves. When it is shown it is set as a figure, with
 * its denominator attached, so it cannot be mistaken for a percentage or a grade.
 *
 * `size="figure"` is for the one place the index is the subject of the screen (UI-05); everywhere
 * else it sits inline in a row and must not shout over its neighbours.
 */
export function ProgressIndex({
  value,
  size = "inline",
}: {
  value: number | null | undefined;
  size?: "inline" | "figure";
}) {
  const { t } = useTranslation();
  if (value === null || value === undefined) {
    return (
      <span
        className={
          size === "figure" ? "text-sm text-muted-foreground" : "text-sm text-muted-foreground"
        }
        data-testid="progress-index"
      >
        {t("assessment.notRated")}
      </span>
    );
  }
  return (
    <span
      className={cn("font-display leading-none", size === "figure" ? "text-[2.125rem]" : "text-lg")}
      data-testid="progress-index"
    >
      {value}
      <span className="figure-unit">/100</span>
    </span>
  );
}
