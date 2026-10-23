import type { Metadata, Viewport } from "next";
import VsThemeScope from "@/components/vstudio/ui/VsThemeScope";
import { SITE_NAME, SITE_URL, OG_IMAGE, OG_IMAGE_ALT, OG_IMAGE_META } from "@/lib/seo/site";

export const metadata: Metadata = {
	title: "Создание мультфильмов — студия EsAI: сценарий, персонажи, видео",
	description:
		"Придумайте историю, нарисуйте героев и оживите их в видео — прямо в EsAI, без навыков. Пошаговая студия: ИИ пишет сценарий, рисует персонажей и создаёт видео.",
	alternates: { canonical: `${SITE_URL}/studio` },
	openGraph: {
		images: [OG_IMAGE_META],
		title: "Создание мультфильмов — студия EsAI",
		description:
			"От идеи до готового мультфильма: ИИ напишет сценарий, нарисует героев и оживит их в видео. Без навыков.",
		url: `${SITE_URL}/studio`,
		siteName: SITE_NAME,
		type: "website",
	},
};

// Рабочий экран, как у видеостудии: Android Chrome сжимает страницу под
// клавиатуру (interactive-widget), и док остаётся над ней. iOS этот ключ не
// знает — там высоту держит visualViewport (hooks/useVisualViewport).
export const viewport: Viewport = {
	width: "device-width",
	initialScale: 1,
	viewportFit: "cover",
	interactiveWidget: "resizes-content",
};

/**
 * Полноэкранная оболочка мультстудии — та же, что у видеостудии
 * (app/video-studio/layout.tsx): без маркетинговой шапки и подвала. Свой верх
 * (логотип, баланс, профиль) рисует сама студия — левая колонка на компьютере
 * и верхняя панель на телефоне.
 *
 * Тема — та же, что у сайта (data-theme на <html>). Обёртка несёт vs-root для
 * первого кадра, а VsThemeScope ставит тот же класс на <html> — туда порталом
 * рисуются шторки и окна.
 */
export default function StudioLayout({
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
