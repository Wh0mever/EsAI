import Link from "next/link";
import SeoShell from "@/components/seo/SeoShell";
import { SITE_NAME, absoluteUrl } from "@/lib/seo/site";
import { breadcrumbJsonLd } from "@/lib/seo/jsonLd";
import {
  getArticles,
  getSiteSettings,
  articleCover,
  articleDate,
  type Article,
} from "@/lib/content";

// Revalidate the list periodically; the underlying fetches are cached with ISR.
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

function ArticleCard({ a }: { a: Article }) {
  const cover = toAbs(articleCover(a));
  const date = formatDate(articleDate(a));
  return (
    <Link
      href={`/blog/${a.slug}`}
      className="group flex flex-col rounded-2xl border border-border bg-surface overflow-hidden hover:border-accent/60 transition-colors"
    >
      {cover ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={cover}
          alt={a.title || ""}
          className="w-full aspect-[16/9] object-cover"
          loading="lazy"
        />
      ) : (
        <div className="w-full aspect-[16/9] bg-surface-2 grid place-items-center">
          <img src="/esai-mark.svg" alt={SITE_NAME} className="h-10 opacity-50" />
        </div>
      )}
      <div className="flex flex-col gap-2 p-5">
        <h2 className="text-lg font-bold leading-snug group-hover:text-accent-strong transition-colors">
          {a.title}
        </h2>
        {a.excerpt && <p className="text-sm text-muted leading-relaxed line-clamp-3">{a.excerpt}</p>}
        {date && <p className="text-xs text-muted-2 mt-1">{date}</p>}
      </div>
    </Link>
  );
}

export default async function BlogListPage() {
  // Fetch list + settings in parallel; both are best-effort.
  const [articles, settings] = await Promise.all([getArticles(), getSiteSettings()]);

  const breadcrumb = breadcrumbJsonLd([
    { name: "Главная", url: "/" },
    { name: "Блог", url: "/blog" },
  ]);

  return (
    <SeoShell settings={settings}>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumb) }}
      />

      <nav aria-label="breadcrumbs" className="text-sm text-muted mb-6">
        <ol className="flex flex-wrap items-center gap-1">
          <li><Link href="/" className="hover:text-foreground">Главная</Link></li>
          <li aria-hidden>/</li>
          <li className="text-foreground">Блог</li>
        </ol>
      </nav>

      <header className="mb-8">
        <h1 className="text-3xl sm:text-4xl font-bold leading-tight">Блог {SITE_NAME}</h1>
        <p className="mt-3 text-base sm:text-lg text-muted leading-relaxed">
          Гайды по нейросетям, разбор моделей и советы, как выжать максимум из ИИ.
        </p>
      </header>

      {articles.length === 0 ? (
        <div className="rounded-2xl border border-border bg-surface p-10 text-center text-muted">
          <p>Скоро здесь появятся статьи.</p>
          <Link
            href="/"
            className="mt-4 inline-flex items-center rounded-full bg-accent text-on-accent font-semibold px-6 py-3 hover:bg-accent-strong transition-colors"
          >
            Открыть чат
          </Link>
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 gap-5">
          {articles.map((a) => (
            <ArticleCard key={String(a.id ?? a.slug)} a={a} />
          ))}
        </div>
      )}
    </SeoShell>
  );
}
