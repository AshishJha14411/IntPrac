# 009 — WebRTC is not required for recorded video

**Status:** Accepted · **Date:** 2026-07-28

## Context
The product records webcam video during an interview, which makes WebRTC look
like the obvious technology.

## Decision
`MediaRecorder` in the browser, chunked to object storage via presigned URLs
(FR-M2). No peer connection, no signalling server, no TURN.

## Consequences
WebRTC solves **real-time, low-latency, bidirectional** media between peers.
None of those words describe this: nobody is watching live, and the reviewer
opens the recording hours later. Adopting it would mean running signalling and
TURN infrastructure to deliver a file that HTTP already delivers.

Chunked presigned upload is also strictly better for the failure mode that
matters: uploading progressively during the session means a completed interview
isn't followed by a large fragile upload, and a failed chunk retries against an
idempotent key. If media upload fails entirely, the interview and its assessment
still stand — video is evidence, not a dependency (FR-M3).

**Revisit if** a "human joins the call" mode is ever built (§12 Q7). That is a
real-time multi-party problem, and it is the only thing here that would justify
a peer connection.
