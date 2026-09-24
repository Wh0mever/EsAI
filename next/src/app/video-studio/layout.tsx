import type { Metadata, Viewport } from "next";
import { SITE_NAME, SITE_URL } from "@/lib/seo/site";

// Пока видеостудия открыта только сотрудникам (VSTUDIO_MODE=staff), страница
// для остальных — «скоро откроется»: индексировать её рано. Флаг тот же, что
// у пункта меню и карты сайта.
const PUBLIC = process.env.NEXT_PUBLIC_VSTUDIO_NAV === "1";

export const metadata: Metadata = {
	title: "Видеостудия — EsAI",
	description:
		"Видео и картинки по вашему описанию и фото: Seedance, Veo, Kling и другие модели в одном окне. Отметьте фото через @, выберите пропорции и длительность — цена видна до запуска, кредиты списываются только за готовый результат.",
	openGraph: {
		title: "Видеостудия — EsAI",
		description:
			"Видео по описанию и вашим фото: несколько моделей в одном окне, честная цена до запуска и оплата только за готовый результат.",
		url: `${SITE_URL}/video-studio`,
		siteName: SITE_NAME,
		type: "website",
	},
	...(PUBLIC ? {} : { robots: { index: false, follow: false } }),
};

// Рабочий экран на телефоне: Android Chrome сжимает страницу под клавиатуру
// (interactive-widget), и прилипший композер остаётся над ней. iOS этот ключ
// не знает — там высоту держит visualViewport (hooks/useVisualViewport).
// Масштаб жестом не запрещаем: поле ввода от 16 px и так не зумится (§9.7).
export const viewport: Viewport = {
	width: "device-width",
	initialScale: 1,
	viewportFit: "cover",
	interactiveWidget: "resizes-content",
};

/**
 * Полноэкранная оболочка видеостудии (§9.1): без маркетинговой шапки и
 * подвала. Свой верх (логотип, баланс, профиль) рисует сама студия — левая
 * колонка на компьютере и верхняя панель на телефоне.
 */
export default function VideoStudioLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return <div className="min-h-[100dvh] bg-background text-foreground">{children}</div>;
}
