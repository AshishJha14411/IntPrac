/**
 * Fetch the Vosk speech model into `public/models/`.
 *
 * Not committed: it is ~40 MB of binary, and a repo that carries one is a repo
 * everybody clones slowly forever. Run this once locally; the Docker build runs
 * it too, so the shipped image is self-contained and the app never depends on
 * a third-party CDN staying up mid-interview.
 *
 *   npm run fetch:model
 *
 * Skips silently if the file is already there, so it is safe in a build step
 * and safe to re-run.
 */
import { createWriteStream } from "node:fs";
import { mkdir, stat } from "node:fs/promises";
import { dirname, join } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { fileURLToPath } from "node:url";

const MODEL = "vosk-model-small-en-us-0.15";
const SOURCE = `https://alphacephei.com/vosk/models/${MODEL}.tar.gz`;

const here = dirname(fileURLToPath(import.meta.url));
const target = join(here, "..", "public", "models", `${MODEL}.tar.gz`);

async function main() {
  try {
    const existing = await stat(target);
    if (existing.size > 0) {
      console.log(`[model] already present (${(existing.size / 1e6).toFixed(1)} MB), skipping`);
      return;
    }
  } catch {
    // Not there yet, which is the normal path on a fresh checkout.
  }

  await mkdir(dirname(target), { recursive: true });
  console.log(`[model] downloading ${SOURCE}`);

  const response = await fetch(SOURCE);
  if (!response.ok || !response.body) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  // Stream to disk rather than buffering: this is 40 MB, and a build container
  // is not the place to hold it in memory for no reason.
  await pipeline(Readable.fromWeb(response.body), createWriteStream(target));

  const written = await stat(target);
  console.log(`[model] saved ${target} (${(written.size / 1e6).toFixed(1)} MB)`);
}

main().catch((error) => {
  // Deliberately non-fatal. A failed model download costs Firefox users
  // dictation; it must not cost everyone else a deployable build.
  console.warn(`[model] download failed: ${error.message}`);
  console.warn("[model] on-device dictation will be unavailable; typing still works.");
});
