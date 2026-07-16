import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import SeoShell from "@/components/seo/SeoShell";
import ArticleContent from "@/components/blog/ArticleContent";
import ArticleReader from "@/components/blog/ArticleReader";
import ArticleOutline from "@/components/blog/ArticleOutline";
import { SITE_NAME, absoluteUrl } from "@/lib/seo/site";
import { breadcrumbJsonLd, articleJsonLd } from "@/lib/seo/jsonLd";
import {
  getArticle,
  getArticles,
  getSiteSettings,
  articleCover,
  articleDate,
  articleMeta,
  articleTitle,
  articleBody,
  extractToc,
  type Article,
} from "@/lib/content";

type Params = { slug: string };

export const revalidate = 300;

function toAbs(url: string): string {
  if (!url) return "";
  if (/^https?:\/\//i.test(url)) return url;
  return absoluteUrl(url);
}

function formatDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  try {
    return d.toLocaleDateString("ru-RU", { year: "numeric", month: "long", day: "numeric" });
  } catch {
    return d.toISOString().slice(0, 10);
  }
}

export async function generateMetadata(
  { params }: { params: Promise<Params> }
): Promise<Metadata> {
  const { slug } = await params;
  const article = await getArticle(slug);
  if (!article) return { title: `Блог — ${SITE_NAME}` };

  const { title, description } = articleMeta(article);
  const url = `/blog/${article.slug}`;
  const cover = toAbs(articleCover(article));
  const fullTitle = title ? `${title} — ${SITE_NAME}` : `Блог — ${SITE_NAME}`;

  return {
    title: fullTitle,
    description,
    alternates: { canonical: url },
    openGraph: {
      title: fullTitle,
      description,
      url: absoluteUrl(url),
      siteName: SITE_NAME,
      type: "article",
      ...(cover ? { images: [{ url: cover }] } : {}),
    },
    twitter: {
      card: cover ? "summary_large_image" : "summary",
      title: fullTitle,
      description,
      ...(cover ? { images: [cover] } : {}),
    },
  };
}

function RelatedArticles({ items }: { items: Article[] }) {
  if (!items.length) return null;
  return (
    <section className="mt-12 pt-8 border-t border-border">
      <h2 className="text-2xl font-bold mb-4">Похожие статьи</h2>
      <div className="grid sm:grid-cols-3 gap-3">
        {items.map((r) => (
          <Link
            key={String(r.id ?? r.slug)}
            href={`/blog/${r.slug}`}
            className="rounded-xl border border-border bg-surface p-4 hover:border-accent/60 transition-colors"
          >
            <span className="block font-semibold leading-snug line-clamp-2">{articleTitle(r)}</span>
            {articleDate(r) && (
              <span className="block text-xs text-muted mt-1">{formatDate(articleDate(r))}</span>
            )}
          </Link>
        ))}
      </div>
    </section>
  );
}

export default async function ArticlePage({ params }: { params: Promise<Params> }) {
  const { slug } = await params;

  // Fetch the article, the full list (for related) and settings in parallel.
  const [article, all, settings] = await Promise.all([
    getArticle(slug),
    getArticles(),
    getSiteSettings(),
  ]);

  if (!article) notFound();

  const title = articleTitle(article) || article.slug;
  const cover = toAbs(articleCover(article));
  const dateIso = articleDate(article);
  const dateLabel = formatDate(dateIso);
  const body = articleBody(article);
  const toc = extractToc(body);

  const related = all
    .filter((a) => a.slug && a.slug !== article.slug)
    .slice(0, 3);

  const url = `/blog/${article.slug}`;
  const breadcrumb = breadcrumbJsonLd([
    { name: "Главная", url: "/" },
    { name: "Блог", url: "/blog" },
    { name: title || article.slug, url },
  ]);
  const articleLd = articleJsonLd({
    title: title || article.slug,
    description: articleMeta(article).description,
    url,
    image: cover || undefined,
    author: article.author,
    datePublished: dateIso || undefined,
    dateModified: (article.updated_at || "").toString() || dateIso || undefined,
  });

  return (
    <SeoShell settings={settings}>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumb) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleLd) }}
      />

      <nav aria-label="breadcrumbs" className="text-sm text-muted mb-6">
        <ol className="flex flex-wrap items-center gap-1">
          <li><Link href="/" className="hover:text-foreground">Главная</Link></li>
          <li aria-hidden>/</li>
          <li><Link href="/blog" className="hover:text-foreground">Блог</Link></li>
          <li aria-hidden>/</li>
          <li className="text-foreground truncate max-w-[12rem]">{title || article.slug}</li>
        </ol>
      </nav>

      <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_16rem] lg:gap-10 lg:items-start">
        <article className="min-w-0">
          <header className="mb-6">
            <h1 className="text-3xl sm:text-4xl font-bold leading-tight">{title || article.slug}</h1>
            <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
              {article.author && <span>{article.author}</span>}
              {article.author && dateLabel && <span aria-hidden>·</span>}
              {dateLabel && <time dateTime={dateIso}>{dateLabel}</time>}
            </div>
          </header>

          {cover && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={cover}
              alt={title || ""}
              className="w-full rounded-2xl border border-border mb-8 object-cover"
            />
          )}

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
                    <a href={`#${it.id}`} className="text-accent-strong hover:underline underline-offset-2">
                      {it.text}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>
          )}

          {body ? (
            <ArticleReader>
              <ArticleContent content={body} />
            </ArticleReader>
          ) : (
            <p className="text-muted">Содержимое статьи недоступно.</p>
          )}

          <section className="mt-12 rounded-2xl border border-border bg-accent-soft p-6 text-center">
            <h2 className="text-xl font-bold mb-2">Попробуйте EsAI прямо сейчас</h2>
            <p className="text-sm text-muted mb-4">
              Все нейросети в одном чате — на русском и кыргызском. Начните бесплатно.
            </p>
            <Link
              href="/"
              className="inline-flex items-center rounded-full bg-accent text-on-accent font-semibold px-6 py-3 hover:bg-accent-strong transition-colors"
            >
              Открыть чат
            </Link>
          </section>

          <RelatedArticles items={related} />
        </article>

        {/* Desktop sticky outline — second grid column, hidden below lg so nothing overlaps on mobile. */}
        <aside className="hidden lg:block sticky top-24 self-start max-h-[calc(100vh-7rem)] overflow-y-auto">
          <ArticleOutline items={toc} />
        </aside>
      </div>
    </SeoShell>
  );
}
