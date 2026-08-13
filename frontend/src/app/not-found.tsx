import { Aurora, GridGround } from "@/components/ui/backgrounds";
import { LinkButton } from "@/components/ui/button";
import { PageHeader, Shell } from "@/components/ui/shell";

/**
 * App Router 404.
 *
 * Without this file Next falls back to the pages-router error page, and the
 * production build fails prerendering `/404` with a confusing
 * "<Html> should not be imported outside of pages/_document".
 */
export default function NotFound() {
  return (
    <div className="relative isolate">
      <Aurora className="h-[30rem]" />
      <GridGround className="h-[30rem]" />
      <Shell className="relative">
        <p className="text-gradient-accent mb-2 font-mono text-6xl font-semibold">404</p>
        <PageHeader
          title="Not found"
          lede="That page doesn’t exist, or it isn’t yours to see."
          actions={<LinkButton href="/">Back to the start</LinkButton>}
        />
      </Shell>
    </div>
  );
}
