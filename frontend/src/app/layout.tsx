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

/**
 * Resolve the theme before the first paint.
 *
 * This has to be a blocking inline script in `<head>`, not an effect. The
 * choice lives in `localStorage`, which the server cannot read, so the server
 * always emits the dark palette. An effect would flip a light-theme user's
 * screen from black to white *after* paint — the flash-of-wrong-theme — which
 * is both ugly and, at night, genuinely unpleasant.
 *
 * Falling back to `prefers-color-scheme` means an OS-level preference is
 * honoured on the first visit, before anyone has touched the toggle.
 *
 * The `try` matters: `localStorage` throws outright in some private-browsing
 * modes, and an exception here would abort the script and leave the document
 * with no `data-theme` at all.
 */
const THEME_SCRIPT = `try{var s=localStorage.getItem("theme");document.documentElement.dataset.theme=(s==="light"||s==="dark")?s:(window.matchMedia("(prefers-color-scheme: light)").matches?"light":"dark")}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // The script above writes an attribute onto this element before React
    // hydrates, which is by definition a difference from what the server sent.
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      {/* Browser extensions inject attributes onto <body> before React
          hydrates — ColorZilla's `cz-shortcut-listen`, password managers, and
          so on — and React reports the difference as a hydration mismatch. It
          is not our markup and we cannot prevent it, so the warning is noise
          that trains people to ignore real mismatches. Scoped to this element
          only: anything below still warns. */}
      <body suppressHydrationWarning className="min-h-dvh bg-void text-ink">
        {/* Keyboard operability is a hard requirement (NFR-A), so the first
            tab stop skips the chrome. `sr-only` until focused, then a real,
            visible, high-contrast target — an invisible skip link is worse
            than none, because it is a tab stop that appears to do nothing. */}
        <a
          href="#main"
          className="sr-only rounded-xl border border-accent/60 bg-panel px-4 py-2.5 text-sm font-medium text-ink focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-50"
        >
          Skip to main content
        </a>

        {/* The page's own light. Fixed rather than absolute so it stays put
            while long pages (the report) scroll past it, and `-z-10` so no
            part of it can ever sit over a control. */}
        <div
          aria-hidden="true"
          className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"
        >
          <div className="absolute -top-1/3 left-1/2 h-[42rem] w-[64rem] -translate-x-1/2 rounded-full bg-bloom-1 blur-[150px]" />
          <div className="absolute right-[-10%] bottom-[-20%] h-[34rem] w-[34rem] rounded-full bg-bloom-2 blur-[150px]" />
        </div>

        <Providers>
          <NavBar />
          <main id="main" className="relative">
            {children}
          </main>
          <SiteFooter />
        </Providers>
      </body>
    </html>
  );
}

function SiteFooter() {
  return (
    <footer className="relative mt-auto border-t border-line-soft">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-5 py-8 text-xs text-faint sm:px-6">
        <span>Scored on understanding, not vocabulary.</span>
        <span>No audio or video is ever stored — only the transcript.</span>
      </div>
    </footer>
  );
}
