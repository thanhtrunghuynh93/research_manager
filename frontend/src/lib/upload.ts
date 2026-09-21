/**
 * The three steps of putting a file in the object store, shared by everything that attaches one.
 *
 * The file never passes through the API: the client hashes it, asks for permission to write one
 * key, PUTs the bytes straight to object storage, and then asks the server to confirm — which is
 * when the server checks the checksum. The middle step is the part that must not go through this
 * application, and it is the reason these helpers exist rather than an `uploadFile()` in the API
 * client next to the JSON calls.
 *
 * Lifted out of the report's `Attachments` when project documents grew the same need (ADR 0018).
 * Two copies of a hashing loop and an XHR is how the two paths drift on the thing they must agree
 * about, which is what the server verifies.
 */

export type UploadGrant = {
  artifact_id: string;
  version_no: number;
  url: string;
  expires_in: number;
  headers: Record<string, string>;
};

/**
 * What is in flight, and how far along. `fraction` is null whenever nothing is measuring it —
 * hashing and confirming have no progress to report, and a browser may send the bytes without
 * ever firing a progress event. Null means "no number", and the bar is then not drawn at all
 * rather than drawn at a number nobody measured.
 */
export type Sending = {
  name: string;
  stage: "checking" | "sending" | "recording";
  fraction: number | null;
};

/** The browser's own SHA-256, so the server has something to verify the upload against. */
export async function sha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * PUT the bytes, reporting how many have gone.
 *
 * `fetch` cannot do this: it reports a response arriving and says nothing about a request body
 * leaving, which is the half that takes the time here. XHR still has `upload.onprogress`, so the
 * one request whose duration a person actually waits through is the one request not made with
 * fetch. The rest of the flow stays on the shared client.
 */
export function putWithProgress(
  url: string,
  headers: Record<string, string>,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("PUT", url);
    for (const [name, value] of Object.entries(headers)) request.setRequestHeader(name, value);
    request.upload.addEventListener("progress", (event) => {
      // `lengthComputable` is the browser saying it knows the total. Without it, dividing by
      // `event.total` yields Infinity or NaN and the bar reads as complete before anything is.
      if (event.lengthComputable && event.total > 0) onProgress(event.loaded / event.total);
    });
    request.addEventListener("load", () => {
      if (request.status >= 200 && request.status < 300) resolve();
      else reject(new Error(`upload failed with ${request.status}`));
    });
    // A refused connection, a DNS failure or a cancelled tab: all three end the upload without a
    // status, and none of them may leave the panel sitting at "Sending…" for ever.
    request.addEventListener("error", () => reject(new Error("the upload could not be sent")));
    request.addEventListener("abort", () => reject(new Error("the upload was interrupted")));
    request.send(file);
  });
}
