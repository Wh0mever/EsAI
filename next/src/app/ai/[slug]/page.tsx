import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import SeoShell from "@/components/seo/SeoShell";
import { SITE_NAME, absoluteUrl, OG_IMAGE, OG_IMAGE_ALT, OG_IMAGE_META } from "@/lib/seo/site";
import { faqJsonLd, breadcrumbJsonLd } from "@/lib/seo/jsonLd";
import { SEO_FUNCTIONS, getFunction, getRelatedFunctions } from "@/lib/seo/functions";

type Params = { slug: string };

// Только слаги из SEO_FUNCTIONS валидны; любой другой → настоящий 404 (SEO).
export const dynamicParams = false;

export function generateStaticParams() {
  return SEO_FUNCTIONS.map((f) => ({ slug: f.slug }));
}

export async function generateMetadata(
  { params }: { params: Promise<Params> }
): Promise<Metadata> {
  const { slug } = await params;
  const fn = getFunction(slug);
  if (!fn) return {};
  const title = `${fn.name} — ${SITE_NAME}`;
  const url = `/ai/${fn.slug}`;
  return {
    title,
    description: fn.metaDescription,
    alternates: { canonical: url },
    openGraph: {
      images: [OG_IMAGE_META],
      title,
      description: fn.metaDescription,
      url: absoluteUrl(url),
      siteName: SITE_NAME,
      type: "website",
    },
    twitter: {
      images: [{ url: OG_IMAGE, alt: OG_IMAGE_ALT }],
      card: "summary_large_image",
      title,
      description: fn.metaDescription,
    },
  };
}

function buildChatHref(fn: { starterPrompt?: string; model?: string }): string {
  const params = new URLSearchParams();
  if (fn.starterPrompt) params.set("q", fn.starterPrompt);
  if (fn.model) params.set("model", fn.model);
  const qs = params.toString();
  return qs ? `/?${qs}` : "/";
}

export default async function FunctionPage({ params }: { params: Promise<Params> }) {
  const { slug } = await params;
  const fn = getFunction(slug);
  if (!fn) notFound();

  const related = getRelatedFunctions(slug);
  const chatHref = buildChatHref(fn);

  const breadcrumb = breadcrumbJsonLd([
    { name: "Главная", url: "/" },
    { name: "Возможности", url: "/ai/napisat-tekst" },
    { name: fn.name, url: `/ai/${fn.slug}` },
  ]);
  const faq = faqJsonLd(fn.faq);

  return (
    <SeoShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumb) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faq) }}
      />

      <nav aria-label="breadcrumbs" className="text-sm text-muted mb-6">
        <ol className="flex flex-wrap items-center gap-1">
          <li><Link href="/" className="hover:text-foreground">Главная</Link></li>
          <li aria-hidden>/</li>
          <li className="text-foreground">{fn.name}</li>
        </ol>
      </nav>

      <article>
        <header className="mb-8">
          <h1 className="text-3xl sm:text-4xl font-bold leading-tight">{fn.name}</h1>
          <p className="mt-4 text-base sm:text-lg text-muted leading-relaxed">{fn.intro}</p>
          <div className="mt-6">
            <Link
              href={chatHref}
              className="inline-flex items-center rounded-full bg-accent text-on-accent font-semibold px-6 py-3 hover:bg-accent-strong transition-colors"
            >
              Открыть в чате
            </Link>
          </div>
        </header>

        <section className="mb-10">
          <h2 className="text-2xl font-bold mb-4">Что умеет {SITE_NAME}</h2>
          <ul className="space-y-2">
            {fn.examples.map((e, i) => (
              <li key={i} className="flex gap-2 text-sm sm:text-base">
                <span className="text-accent shrink-0">→</span>
                <span>{e}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="mb-10">
          <h2 className="text-2xl font-bold mb-4">Частые вопросы</h2>
          <div className="space-y-3">
            {fn.faq.map((f, i) => (
              <details
                key={i}
                className="rounded-xl border border-border bg-surface p-4 group"
              >
                <summary className="cursor-pointer font-medium list-none flex items-center justify-between">
                  {f.q}
                  <span className="text-muted group-open:rotate-180 transition-transform">⌄</span>
                </summary>
                <p className="mt-2 text-sm text-muted leading-relaxed">{f.a}</p>
              </details>
            ))}
          </div>
        </section>

        <section className="mb-10 rounded-2xl border border-border bg-accent-soft p-6 text-center">
          <h2 className="text-xl font-bold mb-2">Начните бесплатно</h2>
          <p className="text-sm text-muted mb-4">
            Все нейросети в одном чате. На русском и кыргызском, оплата в сомах.
          </p>
          <Link
            href={chatHref}
            className="inline-flex items-center rounded-full bg-accent text-on-accent font-semibold px-6 py-3 hover:bg-accent-strong transition-colors"
          >
            Открыть в чате
          </Link>
        </section>

        {related.length > 0 && (
          <section>
            <h2 className="text-2xl font-bold mb-4">Другие возможности</h2>
            <div className="grid sm:grid-cols-2 gap-3">
              {related.map((r) => (
                <Link
                  key={r.slug}
                  href={`/ai/${r.slug}`}
                  className="rounded-xl border border-border bg-surface p-4 hover:border-accent/60 transition-colors"
                >
                  <span className="block font-semibold">{r.name}</span>
                </Link>
              ))}
            </div>
          </section>
        )}
      </article>
    </SeoShell>
  );
}
