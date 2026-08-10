import type { Metadata } from "next";
import { Dashboard } from "./Dashboard";

export const metadata: Metadata = { title: "My interviews" };

export default function DashboardPage() {
  return (
    <div className="shell">
      <h1>My interviews</h1>
      <p className="muted">
        Every session you&rsquo;ve taken, and whether the competencies you keep practising are
        actually moving. The delta against your last attempt is computed in the database, not
        estimated here.
      </p>
      <Dashboard />
    </div>
  );
}
