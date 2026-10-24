import type { Metadata, Viewport } from "next";
import VsThemeScope from "@/components/vstudio/ui/VsThemeScope";
import { SITE_NAME, SITE_URL, OG_IMAGE, OG_IMAGE_ALT, OG_IMAGE_META } from "@/lib/seo/site";

// Публичная страница: склейка — одно из трёх направлений EsAI и бесплатна, её ищут («склеить видео
// онлайн»), поэтому она открыта для индексации и стоит в sitemap. Личные ролики человека подгружаются
// только после входа — в HTML для поисковика их нет.
export const metadata: Metadata = {
	title: "Склейка видео — EsAI",
	description:
		"Соберите в одно видео готовые ролики из видеостудии, мультстудии и чата EsAI или свои файлы: выберите фрагменты, расставьте по порядку и скачайте.",
	alternates: { canonical: `${SITE_URL}/merge` },
	openGraph: {
		images: [OG_IMAGE_META],
		title: "Склейка видео — EsAI",
		description: "Готовые ролики из студий и чата EsAI и свои файлы — в одно видео.",
		url: `${SITE_URL}/merge`,
		siteName: SITE_NAME,
		type: "website",
	},
};

// Рабочий экран, как у студий: Android Chrome сжимает страницу под клавиатуру
// (interactive-widget), и док остаётся над ней. iOS этот ключ не знает — там
// высоту держит visualViewport (hooks/useVisualViewport).
export const viewport: Viewport = {
	width: "device-width",
	initialScale: 1,
	viewportFit: "cover",
	interactiveWidget: "resizes-content",
};

/**
 * Полноэкранная оболочка склейки — та же, что у видеостудии и мультстудии:
 * без маркетинговой шапки и подвала. Свой верх (логотип, баланс, профиль)
 * рисует сама страница — левая колонка на компьютере и верхняя панель на
 * телефоне. Тема — та же, что у сайта; VsThemeScope ставит vs-root на <html>,
 * куда порталом рисуются шторки и окна.
 */
export default function MergeLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<div className="vs-root min-h-[100dvh] bg-background text-foreground">
			<VsThemeScope />
			{children}
		</div>
	);
}
