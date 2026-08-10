# 011 — The voice pipeline runs in the browser; the server stores the transcript

**Status:** Accepted · **Date:** 2026-07-31

## Context

Interviews are spoken. A text-only interview app is a quiz, so §4.7 (`FR-V`)
asks for the real thing: questions read aloud and cached so re-asks are free
(FR-V1), **streaming** STT producing interim and final transcripts with
per-segment timings and confidence (FR-V2/V3), low-confidence spans marked
rather than silently guessed at (FR-V4), and the transcript — never the audio —
as the artifact grading consumes (FR-V5).

The obvious build is a server pipeline: WebSocket up from the browser, audio
frames into a metered STT vendor, partials back down. That collides with two
things at once.

**It cannot scale to zero.** A streaming STT session is a held-open connection
for the length of every answer. ADR 010 deleted the worker and beat precisely
because a process that must always be up is the whole bill on a self-funded
deployment; adding a WebSocket tier back would undo that and cost more.

**It is metered per minute of speech.** §8.3 lists STT as one of only two
variable costs, and a practice product's usage is unbounded by design — people
practise. Per-minute billing on the one thing we want users to do a lot of is
the wrong shape of cost for this product.

Meanwhile the browser already ships both halves. `SpeechRecognition` is a
streaming recogniser with interim results and per-alternative confidence, and
`speechSynthesis` renders speech locally.

## Decision

**Run the voice pipeline in the browser. The server stores the transcript and
its timeline, and nothing else.**

- **STT — two engines behind one interface.** `Dictation` in `lib/speech.ts` is
  the contract; the interview room never branches on which engine it got.
  - `native` — `SpeechRecognition` (`webkitSpeechRecognition` in practice) on
    Chrome, Edge and Safari. Nothing to download, starts instantly.
  - `wasm` — a **Vosk model running in a worker on the candidate's device**,
    used automatically where the native API does not exist (Firefox) and
    selectable by anyone who would rather their audio stayed local.

  Vosk rather than Whisper because the requirements already ask for what Vosk
  emits: `setWords(true)` returns `{word, start, end, conf}`, which *is* FR-V3's
  timings and FR-V4's confidence, and it streams true partial results (FR-V2)
  where Whisper transcribes in fixed windows. Whisper is the more accurate
  model; it is the wrong shape for this spec.

  Either way, interim text is shown live and never submitted, and finalised
  phrases become `TranscriptSegment` rows timed against the answer's own clock.
- **TTS** — `speechSynthesis` reads the question. NFR-C2 asks for TTS cached
  permanently so marginal cost approaches zero; rendering on the device reaches
  the same end by a shorter route, because there is nothing to pay for and
  therefore nothing to cache.
- **The server owns the judgement, not the client.** `low_confidence` is
  derived server-side from `STT_LOW_CONFIDENCE_THRESHOLD` and is not a field
  the request schema accepts. A client that could set it would be able to
  present its own bad transcription as a certain one, and FR-V4 exists to stop
  exactly that.
- **The candidate edits the transcript before submitting.** This is load-bearing,
  not a convenience — see Consequences.
- **No audio is captured, uploaded or stored.** There is no media object, no
  bucket lifecycle, and nothing to leak.

### Text is a peer, not a fallback

Speaking is the default because interviews are spoken. Typing sits next to it
and can be switched to mid-answer.

The reason this is a genuine choice rather than a courtesy is FR-V5: **grading
consumes the transcript and nothing else.** `build_grading_payload()` takes
rubric concepts and a transcript string; there is no parameter through which
"this was spoken" could reach a score, and `test_score_invariance.py` asserts
that signature. So a typed answer and a spoken one are not merely *intended* to
score the same — the system has no mechanism by which they could differ.

That covers the candidate who is deaf, is mute, has a speech difference, is
sharing a room, or simply does not feel like talking, and it covers them
structurally rather than by policy. It is the same argument ADR 007 uses to
refuse affect scoring from video.

## Consequences

**What it costs.**

- *The on-device engine costs a ~40 MB model download*, once per session, on
  the browsers that need it. The UI says so in words while it happens, because
  an unexplained ten-second button is a bug report. The model is fetched at
  build time into `public/models/` and served from our own origin — never from
  a third-party CDN that could be down in the middle of someone's interview —
  and it is gitignored, because a repository carrying a 40 MB binary is a
  repository everybody clones slowly forever.
- *The on-device engine is slower on weak hardware.* Vosk's small English model
  is CPU-only and comfortably real-time on a modern laptop; on an old one it
  lags behind the speaker. The native engine, where it exists, stays the
  default for that reason.
- *Two engines is two things to keep working.* Mitigated by the shared
  `Dictation` type: the room codes against one interface, so an engine cannot
  quietly drift into being a second-class path. It is still two.
- *Transcription quality is the browser's or the model's, and neither is
  accent-neutral.*
  Accent is explicitly never scored — but a mis-transcription would damage a
  score *indirectly*, by putting words the candidate never said in front of the
  grader. This is why the edit step and the low-confidence prompt are part of
  the design and not polish: they are the control that keeps FR-V5's "the
  transcript is the record" from becoming "the recogniser is the judge."
- *Chrome and Edge send audio to Google/Microsoft to transcribe it.* We store
  none of it, but the candidate's audio does leave their machine, so the
  consent disclosure says so in those words — and offers "keep my voice on this
  device", which switches to the on-device engine. Disclosing someone else's
  data flow is still our job; being able to opt out of it is better than
  disclosing it well.
- *There is no audio or video artifact.* FR-M (recorded media) and HR's "jump
  to this answer" playback (FR-H4) are therefore not satisfied by this ADR. The
  timings are stored and correct; there is simply nothing yet to seek within.
  Both are P3 alongside the reviewer workspace.
- *TTS voice quality varies by operating system*, and is noticeably worse than
  a hosted neural voice.
- *No re-transcription is possible.* Keeping no audio means a better model
  later cannot be run over old answers.
- *Official mode needs a separate decision.* Letting a candidate edit their own
  transcript is obviously right in practice mode, where the transcript is a
  study aid. In a hiring decision, "correcting a mis-hearing" and "improving
  the answer after the fact" look identical from the outside. Official mode is
  P3; it must not inherit this behaviour without a deliberate ruling.

**What we gave up.** Control of transcription quality, and any audio record.

**What the correct answer would be at scale.** Keep the browser recogniser for
the live, interactive layer — it is free and genuinely streaming — and add a
**server-side transcription of an uploaded recording** as the authoritative
pass once media exists for FR-M anyway. Gemini accepts audio natively, so this
is one adapter behind the boundary in `app/llm/client.py`, not a new
subsystem: upload the recording via the presigned path that already exists,
stage an outbox event, transcribe, and reconcile against the live transcript.
That buys accent robustness and a re-runnable record, at a per-minute cost
that only makes sense when someone other than the author is paying.

**Revisit when:** official mode ships, HR playback is needed, a candidate
reports being mis-transcribed in a way the edit step didn't catch, or the
project is funded by something other than a personal wallet.

## Alternatives considered

| Option | Cost | Why not (now) |
|---|---|---|
| Server-side streaming STT (Google/Deepgram over a WebSocket) | Per-minute, plus an always-on socket tier | Spec-perfect and directly against ADR 010. Reintroduces the process we deleted, and meters the activity the product wants to encourage. |
| Upload audio, transcribe with Gemini after the fact | Per-minute of audio | Not streaming, so it fails FR-V2's interim results and leaves the candidate staring at a dead screen while they talk. **The right upgrade path, not the right starting point** — see above. |
| Server-hosted Whisper | A GPU, or a very slow CPU worker | Needs the always-on worker ADR 010 removed, and a small instance transcribes slower than real time. |
| Whisper via transformers.js, in the browser | $0 | More accurate than Vosk, especially on accents, and the obvious name to reach for. Rejected as the *engine*: it transcribes in fixed windows rather than streaming (fails FR-V2's interim results) and reports no per-word confidence (fails FR-V4). Worth revisiting if accent robustness beats live feedback. |
| "Please use Chrome" | $0 | What most products do, and the reason a lot of hiring tools quietly exclude people. The whole argument for two input modes collapses if the browser decides who gets to speak. |
| Text only | $0 | What the app already was. It is not an interview. |
| **Native `SpeechRecognition`, falling back to on-device Vosk** | $0 | **Chosen.** Streaming everywhere, no server tier, no audio held, works in every browser, and the more private engine is one checkbox away. |
