import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import SeoShell from "@/components/seo/SeoShell";
import { SITE_NAME, absoluteUrl } from "@/lib/seo/site";
import { faqJsonLd, breadcrumbJsonLd } from "@/lib/seo/jsonLd";
import { SEO_MODELS, getModel, getRelatedModels } from "@/lib/seo/models";

type Params = { slug: string };

// Только слаги из SEO_MODELS валидны; любой другой (напр. удалённый /model/mistral)
// → настоящий 404, а не 200 (важно для SEO: не плодить пустые страницы).
export const dynamicParams = false;

export function generateStaticParams() {
  return SEO_MODELS.map((m) => ({ slug: m.slug }));
}

export async function generateMetadata(
  { params }: { params: Promise<Params> }
): Promise<Metadata> {
  const { slug } = await params;
  const model = getModel(slug);
  if (!model) return {};
  const title = `${model.name} онлайн на русском и кыргызском — ${SITE_NAME}`;
  const url = `/model/${model.slug}`;
  return {
    title,
    description: model.metaDescription,
    alternates: { canonical: url },
    openGraph: {
      title,
      description: model.metaDescription,
      url: absoluteUrl(url),
      siteName: SITE_NAME,
      type: "website",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description: model.metaDescription,
    },
  };
}

export default async function ModelPage({ params }: { params: Promise<Params> }) {
  const { slug } = await params;
  const model = getModel(slug);
  if (!model) notFound();

  const related = getRelatedModels(slug);
  const chatHref = `/?model=${encodeURIComponent(model.openrouter_id)}`;

  const breadcrumb = breadcrumbJsonLd([
    { name: "Главная", url: "/" },
    { name: "Нейросети", url: "/model/chatgpt" },
    { name: model.name, url: `/model/${model.slug}` },
  ]);
  const faq = faqJsonLd(model.faq);

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

      {/* Breadcrumbs */}
      <nav aria-label="breadcrumbs" className="text-sm text-muted mb-6">
        <ol className="flex flex-wrap items-center gap-1">
          <li><Link href="/" className="hover:text-foreground">Главная</Link></li>
          <li aria-hidden>/</li>
          <li className="text-foreground">{model.name}</li>
        </ol>
      </nav>

      <article>
        <header className="mb-8">
          <span className="inline-block text-xs font-medium text-accent-strong uppercase tracking-wide mb-2">
            {model.vendor}
          </span>
          <h1 className="text-3xl sm:text-4xl font-bold leading-tight">
            {model.name} онлайн в {SITE_NAME}
          </h1>
          <p className="mt-4 text-base sm:text-lg text-muted leading-relaxed">{model.intro}</p>
          <div className="mt-6">
            <Link
              href={chatHref}
              className="inline-flex items-center rounded-full bg-accent text-on-accent font-semibold px-6 py-3 hover:bg-accent-strong transition-colors"
            >
              Открыть {model.name} в чате
            </Link>
          </div>
        </header>

        <section className="mb-10">
          <h2 className="text-2xl font-bold mb-4">Преимущества {model.name}</h2>
          <ul className="grid sm:grid-cols-2 gap-3">
            {model.advantages.map((a, i) => (
              <li
                key={i}
                className="rounded-xl border border-border bg-surface p-4 text-sm leading-relaxed"
              >
                {a}
              </li>
            ))}
          </ul>
        </section>

        <section className="mb-10">
          <h2 className="text-2xl font-bold mb-4">Что можно сделать</h2>
          <ul className="space-y-2">
            {model.examples.map((e, i) => (
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
            {model.faq.map((f, i) => (
              <details
                key={i}
                className="rounded-xl border border-border bg-surface p-4 group"
              >
                <summary className="cursor-pointer font-medium list-none flex items-center justify-between">
                  {f.q}
                  <span className="text-muted group-open:rotate-180 transition-transform">⌄</span>
                </summary>
                {/* Размер как у подписей на главной (text-xs → sm), а не крупнее:
                    просьба клиента. whitespace-pre-line — ответ про оплату
                    разбит по строкам на страну. */}
                <p className="mt-2 text-xs sm:text-sm text-muted leading-relaxed whitespace-pre-line">
                  {f.a}
                </p>
              </details>
            ))}
          </div>
        </section>

        <section className="mb-10 rounded-2xl border border-border bg-accent-soft p-6 text-center">
          <h2 className="text-xl font-bold mb-2">Попробуйте {model.name} прямо сейчас</h2>
          <p className="text-sm text-muted mb-4">
            Без VPN, на русском и кыргызском, оплата в сомах. Начните бесплатно.
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
            <h2 className="text-2xl font-bold mb-4">Похожие модели</h2>
            <div className="grid sm:grid-cols-3 gap-3">
              {related.map((r) => (
                <Link
                  key={r.slug}
                  href={`/model/${r.slug}`}
                  className="rounded-xl border border-border bg-surface p-4 hover:border-accent/60 transition-colors"
                >
                  <span className="block font-semibold">{r.name}</span>
                  <span className="block text-xs text-muted mt-1">{r.vendor}</span>
                </Link>
              ))}
            </div>
          </section>
        )}
      </article>
    </SeoShell>
  );
}
