import Link from "next/link";
import type { ReactNode } from "react";
import { SITE_NAME } from "@/lib/seo/site";
import type { SiteSettings } from "@/lib/content";

/**
 * SeoShell — lightweight, server-rendered wrapper for SEO landing pages
 * (/model/*, /ai/*, /blog/*). Header with the EsAI logo + "Open in chat" link,
 * the page content, and a minimal footer. Uses the existing brand CSS variables
 * so it follows the dark/light theme automatically.
 *
 * `settings` is optional dynamic contact data (from /api/content/site-settings/).
 * When present, contact links are rendered in the footer; otherwise the footer
 * falls back to the static nav only.
 */
export default function SeoShell({
  children,
  settings,
}: {
  children: ReactNode;
  settings?: SiteSettings | null;
}) {
  const year = new Date().getFullYear();
  return (
    <div className="min-h-[100dvh] flex flex-col bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b border-border bg-background/80 backdrop-blur">
        <div className="mx-auto max-w-4xl w-full px-4 h-14 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2" aria-label={SITE_NAME}>
            <img src="/esai-logo.svg" alt={SITE_NAME} className="h-6" />
          </Link>
          <Link
            href="/"
            className="inline-flex items-center rounded-full bg-accent text-on-accent text-sm font-semibold px-4 py-2 hover:bg-accent-strong transition-colors"
          >
            Открыть чат
          </Link>
        </div>
      </header>

      <main className="flex-1 mx-auto max-w-4xl w-full px-4 py-8 sm:py-10">{children}</main>

      <footer className="border-t border-border">
        <div className="mx-auto max-w-4xl w-full px-4 py-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-sm text-muted">
          <div className="flex items-center gap-2">
            <img src="/esai-mark.svg" alt={SITE_NAME} className="h-5" />
            <span>© {year} {SITE_NAME}</span>
          </div>
          <nav className="flex items-center gap-4">
            <Link href="/" className="hover:text-foreground transition-colors">Чат</Link>
            <Link href="/pricing" className="hover:text-foreground transition-colors">Цены</Link>
            <Link href="/blog" className="hover:text-foreground transition-colors">Блог</Link>
          </nav>
        </div>
        {settings && (settings.email || settings.phone || settings.address) && (
          <div className="mx-auto max-w-4xl w-full px-4 pb-6 -mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-2">
            {settings.email && (
              <a href={`mailto:${settings.email}`} className="hover:text-foreground transition-colors">
                {settings.email}
              </a>
            )}
            {settings.phone && (
              <a href={`tel:${settings.phone}`} className="hover:text-foreground transition-colors">
                {settings.phone}
              </a>
            )}
            {settings.address && <span>{settings.address}</span>}
          </div>
        )}
      </footer>
    </div>
  );
}
