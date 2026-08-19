import type { Metadata } from "next";
import { cache } from "react";
import { notFound } from "next/navigation";
import NextLink from "@/components/ui/nextLink/NextLink";
import { SITE_NAME, SITE_URL, absoluteUrl } from "@/lib/seo/site";
import SharedVideoPlayer from "@/components/video/SharedVideoPlayer";

/**
 * Публичная страница ролика: esai.kg/v/<код>.
 *
 * Ради неё всё и затевалось — Telegram, WhatsApp и соцсети читают og:video и
 * проигрывают ролик прямо в переписке, не заставляя никого переходить по
 * ссылке. Поэтому метаданные здесь важнее вёрстки: без og:video:type и
 * размеров Telegram покажет просто картинку со ссылкой.
 *
 * Страница динамическая (no-store): ссылка одноразовая по смыслу, кэшировать
 * нечего, а сервер на каждом заходе считает просмотр.
 */

type Params = { slug: string };

type Share = {
  slug: string;
  video_url: string;
  poster_url?: string;
  prompt?: string;
  model?: string;
  width?: number | null;
  height?: number | null;
  duration?: number | null;
  created_at?: string;
};

/** cache() — чтобы generateMetadata и сам рендер не сходили за данными дважды. */
const getShare = cache(async (slug: string): Promise<Share | null> => {
  const origin = (process.env.NEXT_PUBLIC_SITE_URL || "").replace(/\/$/, "") || SITE_URL;
  try {
    const res = await fetch(`${origin}/api/ai/video/share/${encodeURIComponent(slug)}/`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = (await res.json()) as Share;
    return data?.video_url ? data : null;
  } catch {
    return null;
  }
});

function shortPrompt(p?: string): string {
  const s = (p || "").replace(/\s+/g, " ").trim();
  if (!s) return "";
  return s.length > 120 ? `${s.slice(0, 117)}…` : s;
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { slug } = await params;
  const share = await getShare(slug);
  if (!share) return { title: `Видео — ${SITE_NAME}`, robots: { index: false, follow: false } };

  const prompt = shortPrompt(share.prompt);
  const title = prompt ? `${prompt} — видео от ${SITE_NAME}` : `Видео от ${SITE_NAME}`;
  const description = prompt
    ? `Ролик создан нейросетью в ${SITE_NAME}. Запрос: «${prompt}». Сделайте своё — бесплатные кредиты каждый день.`
    : `Ролик создан нейросетью в ${SITE_NAME}. Сделайте своё — бесплатные кредиты каждый день.`;

  const width = share.width || 1280;
  const height = share.height || 720;

  return {
    title,
    description,
    alternates: { canonical: `/v/${share.slug}` },
    // Пользовательские ролики в поиске не нужны: ссылка личная, ею делятся
    // адресно. follow оставляем — ссылки со страницы на сайт пусть работают.
    robots: { index: false, follow: true },
    openGraph: {
      type: "video.other",
      title,
      description,
      url: absoluteUrl(`/v/${share.slug}`),
      siteName: SITE_NAME,
      videos: [{ url: share.video_url, type: "video/mp4", width, height }],
      ...(share.poster_url ? { images: [{ url: share.poster_url, width, height }] } : {}),
    },
    // card: player требует отдельную страницу-плеер под iframe с жёсткими
    // требованиями X; своей у нас нет, а битая player-карточка показывается
    // хуже обычной. Крупная картинка с обложкой ролика надёжнее.
    twitter: {
      card: "summary_large_image",
      title,
      description,
      ...(share.poster_url ? { images: [share.poster_url] } : {}),
    },
  };
}

export default async function SharedVideoPage({ params }: { params: Promise<Params> }) {
  const { slug } = await params;
  const share = await getShare(slug);
  if (!share) notFound();

  const prompt = (share.prompt || "").trim();
  // Вертикальный ролик не должен растягиваться на всю ширину — иначе на
  // десктопе он занимает экран целиком и выглядит нелепо.
  const vertical = Boolean(share.width && share.height && share.height > share.width);

  return (
    <main className="min-h-dvh bg-background text-foreground flex flex-col">
      <header className="flex items-center justify-between px-4 sm:px-6 h-14 border-b border-border">
        <NextLink href="/" className="text-lg font-semibold tracking-tight">
          {SITE_NAME}
          <span className="text-accent">✨</span>
        </NextLink>
        <NextLink
          href="/"
          className="rounded-full bg-accent text-on-accent text-sm font-semibold px-4 py-1.5 hover:bg-accent-strong transition-colors"
        >
          Создать своё
        </NextLink>
      </header>

      <div className="flex-1 flex flex-col items-center justify-center gap-4 px-4 py-8">
        <div className={vertical ? "w-full max-w-[360px]" : "w-full max-w-3xl"}>
          <SharedVideoPlayer
            src={share.video_url}
            poster={share.poster_url || ""}
            downloadName={`esai-video-${share.slug}.mp4`}
          />
        </div>

        {prompt && (
          <p className="max-w-2xl text-center text-sm text-muted leading-relaxed">
            «{prompt}»
          </p>
        )}

        <p className="text-xs text-muted-2 text-center">
          Ролик создан нейросетью в {SITE_NAME}
          {share.model ? ` · ${share.model}` : ""}
        </p>

        <NextLink
          href="/"
          className="mt-2 rounded-full border border-accent text-accent hover:bg-accent-soft transition-colors text-sm font-medium px-5 py-2"
        >
          Сделать такое же видео бесплатно
        </NextLink>
      </div>
    </main>
  );
}
