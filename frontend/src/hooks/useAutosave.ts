import { useEffect, useRef, useState } from "react";

export type AutosaveState = "idle" | "saving" | "saved" | "error";

/**
 * REP-04: autosave after typing stops, and on unmount, so a closed tab does not lose work.
 * The value is compared by its serialised form, so an edit that changes nothing writes nothing.
 */
export function useAutosave<T>(
  value: T,
  save: (value: T) => Promise<unknown>,
  { delayMs = 1500 }: { delayMs?: number } = {},
): { state: AutosaveState; savedAt: Date | null; flush: () => Promise<void> } {
  const [state, setState] = useState<AutosaveState>("idle");
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const lastSaved = useRef<string | null>(null);
  const pending = useRef<T>(value);
  pending.current = value;

  async function persist(): Promise<void> {
    const serialised = JSON.stringify(pending.current);
    if (serialised === lastSaved.current) return;
    setState("saving");
    try {
      await save(pending.current);
      lastSaved.current = serialised;
      setSavedAt(new Date());
      setState("saved");
    } catch {
      setState("error");
    }
  }

  useEffect(() => {
    const serialised = JSON.stringify(value);
    if (lastSaved.current === null) {
      lastSaved.current = serialised; // the first render is the loaded draft, not an edit
      return;
    }
    if (serialised === lastSaved.current) return;
    const timer = setTimeout(() => void persist(), delayMs);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(value), delayMs]);

  return { state, savedAt, flush: persist };
}
