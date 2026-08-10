import type { Metadata } from "next";
import "./globals.css";
import { NavBar } from "./NavBar";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: {
    default: "Interview practice — scores understanding, not vocabulary",
    template: "%s · Interview practice",
  },
  description:
    "Practise realistic technical interviews and find out what your answers actually missed. " +
    "You are scored on the mechanism you describe, never on the words you use for it.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      {/* Browser extensions inject attributes onto <body> before React
          hydrates — ColorZilla's `cz-shortcut-listen`, password managers, and
          so on — and React reports the difference as a hydration mismatch. It
          is not our markup and we cannot prevent it, so the warning is noise
          that trains people to ignore real mismatches. Scoped to this element
          only: anything below still warns. */}
      <body suppressHydrationWarning>
        {/* Keyboard operability is a hard requirement (NFR-A), so the first
            tab stop skips the chrome. */}
        <a className="skip-link" href="#main">
          Skip to main content
        </a>
        <Providers>
          <header className="shell wide" style={{ paddingBottom: 0 }}>
            <NavBar />
          </header>
          <main id="main">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
