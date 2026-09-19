import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

// Feature tests register handlers with server.use(...) per test.
//
// The calendar is the one exception, and it is here rather than in each test because every screen
// that prints a time asks for it: instants are rendered in the workspace's timezone (REP-01) and
// `useTimezone` reads it from the calendar in force. A suite that does not care about times should
// not have to say so, and `onUnhandledRequest: "error"` means leaving it out is not an option.
export const server = setupServer(http.get("/api/v1/calendar", () => HttpResponse.json(null)));

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// jsdom's Blob has no `arrayBuffer`, and its `crypto` lacks `subtle`. Both exist in every browser
// the product runs in, so they are supplied here rather than worked around in the components.
import { createHash, randomBytes, randomUUID } from "node:crypto";

if (typeof Blob.prototype.arrayBuffer !== "function") {
  Blob.prototype.arrayBuffer = function arrayBuffer(this: Blob): Promise<ArrayBuffer> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        // Copy into this realm's ArrayBuffer: jsdom's belongs to another one, and node:crypto
        // refuses buffers it does not recognise.
        const source = new Uint8Array(reader.result as ArrayBuffer);
        const copy = new Uint8Array(new ArrayBuffer(source.length));
        copy.set(source);
        resolve(copy.buffer);
      };
      reader.onerror = () => reject(reader.error);
      reader.readAsArrayBuffer(this);
    });
  };
}

if (typeof Blob.prototype.stream !== "function") {
  // fetch streams a request body; jsdom's Blob cannot. The upload sends the File itself rather
  // than a buffered copy, which is the behaviour that matters for a 25 MB attachment.
  Blob.prototype.stream = function stream(this: Blob): ReadableStream<Uint8Array<ArrayBuffer>> {
    const bytes = this.arrayBuffer();
    return new ReadableStream({
      async start(controller) {
        controller.enqueue(new Uint8Array((await bytes) as ArrayBuffer));
        controller.close();
      },
    });
  };
}

{
  // Always installed, not only when `subtle` is missing: jsdom ships one that type-checks its
  // arguments against its own realm and rejects the buffer the Blob polyfill above produces.
  // A digest shim rather than Node's whole webcrypto: that one type-checks its arguments against
  // its own realm's ArrayBuffer and rejects the one jsdom hands it.
  const subtle = {
    digest: async (algorithm: string, data: BufferSource): Promise<ArrayBuffer> => {
      const view: Uint8Array<ArrayBuffer> = ArrayBuffer.isView(data)
        ? new Uint8Array(data.buffer as ArrayBuffer, data.byteOffset, data.byteLength)
        : new Uint8Array(data as ArrayBuffer);
      const hash = createHash(algorithm.toLowerCase().replace("-", "")).update(Buffer.from(view));
      const digest = hash.digest();
      const out = new Uint8Array(digest.length);
      out.set(digest);
      return out.buffer;
    },
  };
  // Spreading `globalThis.crypto` would copy own properties only, and `getRandomValues` lives on
  // the prototype — so the shim silently dropped it and code reaching for it saw a browser that
  // does not exist. Both randomness functions are supplied explicitly, and both return what a
  // browser returns: a real v4 uuid, and bytes actually written into the caller's array.
  Object.defineProperty(globalThis, "crypto", {
    value: {
      subtle,
      randomUUID,
      getRandomValues: <T extends ArrayBufferView>(target: T): T => {
        // Filled element-wise from node:crypto rather than handed the view directly: jsdom's
        // typed arrays belong to another realm, which randomFillSync refuses.
        const bytes = randomBytes(target.byteLength);
        const out = new Uint8Array(target.buffer, target.byteOffset, target.byteLength);
        out.set(bytes);
        return target;
      },
    },
    configurable: true,
  });
}
