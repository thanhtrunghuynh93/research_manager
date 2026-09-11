/**
 * Server-Sent Events helper for the assistant stream (architecture §11).
 * Events: "progress" (router / retrieval steps), "chunk" (answer text), "citations", "done", "error".
 */

export type SseHandlers = {
  onProgress?: (step: string) => void;
  onChunk?: (text: string) => void;
  onCitations?: (citations: unknown[]) => void;
  onDone?: () => void;
  onError?: (message: string) => void;
};

export function openStream(url: string, handlers: SseHandlers): () => void {
  const source = new EventSource(url, { withCredentials: true });

  source.addEventListener("progress", (e) => handlers.onProgress?.((e as MessageEvent).data));
  source.addEventListener("chunk", (e) => handlers.onChunk?.((e as MessageEvent).data));
  source.addEventListener("citations", (e) =>
    handlers.onCitations?.(JSON.parse((e as MessageEvent).data) as unknown[]),
  );
  source.addEventListener("done", () => {
    handlers.onDone?.();
    source.close();
  });
  source.addEventListener("error", (e) => {
    const data = (e as MessageEvent).data as string | undefined;
    handlers.onError?.(data ?? "stream error");
    source.close();
  });

  return () => source.close();
}
