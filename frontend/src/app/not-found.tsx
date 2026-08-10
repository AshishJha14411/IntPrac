import Link from "next/link";

/**
 * App Router 404.
 *
 * Without this file Next falls back to the pages-router error page, and the
 * production build fails prerendering `/404` with a confusing
 * "<Html> should not be imported outside of pages/_document".
 */
export default function NotFound() {
  return (
    <div className="shell">
      <h1>Not found</h1>
      <p className="muted">That page doesn&rsquo;t exist, or it isn&rsquo;t yours to see.</p>
      <Link href="/">
        <button>Back to the start</button>
      </Link>
    </div>
  );
}
