"use client";

/** App Router error boundary. Never leaks internals to the page. */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="shell">
      <h1>Something went wrong</h1>
      <p className="muted">
        This has been logged. If you were part-way through an interview, your answers are safe —
        reopening the session picks up where you left off.
      </p>
      {error.digest && (
        <p className="small muted mono">
          Reference: {error.digest}
        </p>
      )}
      <button onClick={reset}>Try again</button>
    </div>
  );
}
