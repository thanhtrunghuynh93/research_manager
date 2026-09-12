import { useEffect, useRef, useState } from "react";

export type AutosaveState = "idle" | "saving" | "saved" | "error";

/**
 * REP-04: autosave after typing stops, and on unmount, so a closed tab does not lose work.
 * The value is compared by its serialised form, so an edit that changes nothing writes nothing.
 *
 * Two things this has to get right, both of which are silent when wrong — the indicator says
 * "Saved" either way, and the student finds out on their next visit:
 *
 *   - Unmount flushes rather than cancels. Clicking a link within the debounce window used to
 *     clear the timer and send nothing at all.
 *   - Saves are serialised and the newest value always wins. Two requests in flight could return
 *     out of order, and the older response would then overwrite the newer one as "what is saved".
 *
 * `value` must be null until the stored draft has loaded. A non-null first value is taken as the
 * baseline, so passing a placeholder makes the hook save the placeholder over the real draft.
 */
export function useAutosave<T>(
  value: T | null,
  save: (value: T) => Promise<unknown>,
  { delayMs = 1500 }: { delayMs?: number } = {},
): { state: AutosaveState; savedAt: Date | null; flush: () => Promise<void> } {
  const [state, setState] = useState<AutosaveState>("idle");
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const lastSaved = useRef<string | null>(null);
  const pending = useRef<T | null>(value);
  pending.current = value;
  // Keeps `save` current without making it an effect dependency: callers pass a new closure
  // every render, which would restart the debounce on each keystroke.
  const saveRef = useRef(save);
  saveRef.current = save;
  // The save in flight, so a second one queues behind it instead of racing it.
  const inFlight = useRef<Promise<void>>(Promise.resolve());

  async function persist(): Promise<void> {
    const run = inFlight.current.then(async () => {
      const current = pending.current;
      if (current === null) return;
      const serialised = JSON.stringify(current);
      if (serialised === lastSaved.current) return;
      setState("saving");
      try {
        await saveRef.current(current);
        lastSaved.current = serialised;
        setSavedAt(new Date());
        setState("saved");
      } catch {
        setState("error");
      }
    });
    inFlight.current = run.catch(() => undefined);
    return run;
  }

  const persistRef = useRef(persist);
  persistRef.current = persist;

  useEffect(() => {
    if (value === null) return; // the draft has not loaded yet; there is nothing to compare
    const serialised = JSON.stringify(value);
    if (lastSaved.current === null) {
      lastSaved.current = serialised; // the first value is the loaded draft, not an edit
      return;
    }
    if (serialised === lastSaved.current) return;
    const timer = setTimeout(() => void persistRef.current(), delayMs);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(value), delayMs]);

  // Separate from the debounce effect, which re-runs on every edit: this one runs once, so its
  // cleanup is the real unmount rather than the end of a keystroke.
  useEffect(() => {
    const onHide = () => void persistRef.current();
    window.addEventListener("pagehide", onHide);
    return () => {
      window.removeEventListener("pagehide", onHide);
      void persistRef.current();
    };
  }, []);

  return { state, savedAt, flush: () => persistRef.current() };
}
