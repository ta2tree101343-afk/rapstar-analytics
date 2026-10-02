import { Link, NavLink, useLocation } from "react-router-dom";
import { MockDataBanner } from "./MockDataBanner";
import { IS_MOCK } from "../api/client";
import { clsx } from "clsx";
import type { PropsWithChildren } from "react";

function TopNavLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        clsx(
          "whitespace-nowrap px-2 py-1 text-sm font-medium transition-colors",
          isActive ? "text-fg-primary" : "text-fg-secondary hover:text-fg-primary",
        )
      }
    >
      {children}
    </NavLink>
  );
}

export function Layout({ children }: PropsWithChildren) {
  const { search } = useLocation();
  const useBebas = new URLSearchParams(search).get("brand") === "bebas";

  return (
    // overflow-x-clip at the root prevents any child from creating page-level
    // horizontal scroll while allowing sticky children to keep working.
    <div className="min-h-screen bg-bg-base overflow-x-clip">
      {IS_MOCK && <MockDataBanner />}
      <header className="sticky top-0 z-10 border-b border-border-subtle bg-bg-base">
        <div className="mx-auto max-w-6xl px-4 py-2.5 sm:py-3 flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
          <Link to="/" className="flex items-center gap-2 group min-w-0">
            <span
              className={clsx(
                "text-fg-primary group-hover:text-accent-yellow transition-colors whitespace-nowrap",
                // Bebas Neue is condensed and reads smaller at the same px
                // size, so bump one step. `tracking-[0.02em]` avoids the
                // over-tight look Bebas gets at bold/dark backgrounds.
                useBebas
                  ? "font-display font-normal text-xl sm:text-2xl tracking-[0.02em]"
                  : "font-sans font-bold text-lg sm:text-xl tracking-tight",
              )}
            >
              RAPSTAR
              <span
                className={clsx(
                  "ml-1 text-fg-secondary group-hover:text-fg-primary transition-colors",
                  // Keep "Analytics" in Inter regardless of display toggle so
                  // the data-side of the brand stays consistent.
                  useBebas
                    ? "font-sans font-semibold text-sm sm:text-base tracking-tight"
                    : "font-sans",
                )}
              >
                Analytics
              </span>
            </span>
          </Link>
          <nav className="-mx-1 flex items-center gap-1 sm:gap-3">
            <TopNavLink to="/">ランキング</TopNavLink>
            <TopNavLink to="/compare">全体比較</TopNavLink>
            <TopNavLink to="/about">このサイト</TopNavLink>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6 sm:py-8">{children}</main>

      <footer className="mt-4 border-t border-border-subtle">
        <div className="mx-auto max-w-6xl px-4 py-4 text-xs text-fg-muted flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <div>
            RAPSTAR Analytics — Instagram 公開指標集計
          </div>
          <div>Instagram Graph API v26.0 / Business Discovery</div>
        </div>
      </footer>
    </div>
  );
}
