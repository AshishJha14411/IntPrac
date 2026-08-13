import type { Metadata } from "next";
import { PageHeader, Shell } from "@/components/ui/shell";
import { Dashboard } from "./Dashboard";

export const metadata: Metadata = { title: "My interviews" };

export default function DashboardPage() {
  return (
    <Shell width="wide">
      <PageHeader
        eyebrow="Your practice"
        title="My interviews"
        lede={
          <>
            Every session you&rsquo;ve taken, and whether the competencies you keep practising are
            actually moving. The delta against your last attempt is computed in the database, not
            estimated here.
          </>
        }
      />
      <Dashboard />
    </Shell>
  );
}
