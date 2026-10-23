import type { Metadata, Viewport } from "next";
import VsThemeScope from "@/components/vstudio/ui/VsThemeScope";
import { OG_IMAGE, OG_IMAGE_ALT, OG_IMAGE_META, SITE_NAME, SITE_URL } from "@/lib/seo/site";

// Пока видеостудия открыта только сотрудникам (VSTUDIO_MODE=staff), страница
// для остальных — «скоро откроется»: индексировать её рано. Флаг тот же, что
// у пункта меню и карты сайта.
const PUBLIC = process.env.NEXT_PUBLIC_VSTUDIO_NAV === "1";

const SHARE_TITLE = "Видеостудия — EsAI";
const SHARE_DESCRIPTION =
	"Видео по описанию и вашим фото: несколько моделей в одном окне, честная цена до запуска и оплата только за готовый результат.";

export const metadata: Metadata = {
	title: SHARE_TITLE,
	description:
		"Видео и картинки по вашему описанию и фото: Seedance, Veo, Kling и другие модели в одном окне. Отметьте фото через @, выберите пропорции и длительность — цена видна до запуска, кредиты списываются только за готовый результат.",
	// Свой openGraph заменяет корневой целиком, вместе с картинкой: без images
	// ссылка на студию в мессенджере осталась бы без обложки. Карточку twitter
	// задаём тоже — иначе она наследует заголовок и описание главной.
	openGraph: {
		title: SHARE_TITLE,
		description: SHARE_DESCRIPTION,
		url: `${SITE_URL}/video-studio`,
		siteName: SITE_NAME,
		type: "website",
		images: [OG_IMAGE_META],
	},
	twitter: {
		card: "summary_large_image",
		title: SHARE_TITLE,
		description: SHARE_DESCRIPTION,
		images: [{ url: OG_IMAGE, alt: OG_IMAGE_ALT }],
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
 *
 * Тема — та же, что у сайта (data-theme на <html>): тёмная и светлая палитры
 * студии описаны в globals.css. Обёртка несёт vs-root для первого кадра, а
 * VsThemeScope ставит тот же класс на <html> — туда порталом рисуются шторки
 * и меню.
 */
export default function VideoStudioLayout({
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
