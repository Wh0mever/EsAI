import Link from "next/link";
import ArticleContent from "@/components/blog/ArticleContent";
import ArticleReader from "@/components/blog/ArticleReader";
import ArticleOutline from "@/components/blog/ArticleOutline";
import { extractToc } from "@/lib/content";

type HomeArticleSectionProps = {
  title: string;
  body: string;
  slug: string;
};

/**
 * HomeArticleSection — server component rendered BELOW the 100dvh chat on the
 * home page. Scrolling down past the chat reveals the flagship SEO article with
 * the same reading-progress + reveal-on-scroll animation used on /blog/[slug],
 * matching the ai-flip.ru pattern.
 *
 * It is self-contained: brings its own top divider, container, max-width and
 * background so it works under the bare (home)/layout.tsx. Renders nothing when
 * the article body is empty.
 */
export default function HomeArticleSection({ title, body, slug }: HomeArticleSectionProps) {
  if (!body) return null;

  const toc = extractToc(body);

  return (
    <section
      aria-label="Подробнее об EsAI"
      className="border-t border-border bg-background"
      style={{ background: "var(--background)" }}
    >
      <div className="mx-auto max-w-5xl px-4 py-16 sm:py-24">
        {/* Subtle Apple-style scroll cue / eyebrow so users notice there is more below the chat. */}
        <div className="flex flex-col items-center gap-2 text-muted mb-12 sm:mb-16">
          <svg
            aria-hidden
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="opacity-70 motion-safe:animate-bounce"
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
          <span className="text-xs font-medium uppercase tracking-[0.2em]">
            Узнать больше об EsAI
          </span>
        </div>

        <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_16rem] lg:gap-10 lg:items-start">
          <article className="min-w-0">
            <header className="mb-6">
              <h2 className="text-3xl sm:text-4xl font-bold leading-tight">
                <Link href={`/blog/${slug}`} className="hover:text-accent-strong transition-colors">
                  {title}
                </Link>
              </h2>
            </header>

            {/* Mobile / tablet inline TOC — hidden on lg where the sticky outline takes over. */}
            {toc.length > 1 && (
              <nav
                aria-label="Содержание"
                className="mb-8 rounded-2xl border border-border bg-surface p-5 lg:hidden"
              >
                <p className="text-sm font-semibold text-muted mb-2">Содержание</p>
                <ul className="space-y-1.5 text-sm">
                  {toc.map((it) => (
                    <li key={it.id} className={it.level === 3 ? "pl-4" : ""}>
                      <a
                        href={`#${it.id}`}
                        className="text-accent-strong hover:underline underline-offset-2"
                      >
                        {it.text}
                      </a>
                    </li>
                  ))}
                </ul>
              </nav>
            )}

            <ArticleReader>
              <ArticleContent content={body} />
            </ArticleReader>

            {/* CTA block — same bg-accent-soft style as /blog/[slug]. */}
            <section className="mt-12 rounded-2xl border border-border bg-accent-soft p-6 text-center">
              <h2 className="text-xl font-bold mb-2">Попробуйте EsAI прямо сейчас</h2>
              <p className="text-sm text-muted mb-4">
                Все нейросети в одном чате — на русском и кыргызском. Начните бесплатно.
              </p>
              <div className="flex flex-wrap items-center justify-center gap-3">
                <Link
                  href="/#"
                  className="inline-flex items-center rounded-full bg-accent text-on-accent font-semibold px-6 py-3 hover:bg-accent-strong transition-colors"
                >
                  Открыть чат
                </Link>
                <Link
                  href="/blog"
                  className="inline-flex items-center rounded-full border border-border px-6 py-3 font-semibold text-foreground hover:border-accent/60 transition-colors"
                >
                  Все статьи →
                </Link>
              </div>
            </section>
          </article>

          {/* Desktop sticky outline — second grid column, hidden below lg so nothing overlaps on mobile. */}
          <aside className="hidden lg:block sticky top-24 self-start max-h-[calc(100vh-7rem)] overflow-y-auto">
            <ArticleOutline items={toc} />
          </aside>
        </div>
      </div>
    </section>
  );
}
