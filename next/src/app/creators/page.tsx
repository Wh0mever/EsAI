import "@/assets/style.scss";
import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import CreatorsLanding from "@/components/creators/public/CreatorsLanding";
import { OG_IMAGE, SITE_NAME, SITE_URL } from "@/lib/seo/site";

/**
 * /creators — публичная страница программы EsAI Creators: условия, уровни,
 * заявка на участие и её статус. Форма заявки открывается здесь же (?apply=1),
 * отдельного адреса у неё нет.
 *
 * Шапка, подвал и метаданные живут в самой странице, а не в layout.tsx этой
 * папки: layout накрыл бы и вложенный /creators/dashboard, у которого свой
 * layout с шапкой и подвалом, — они нарисовались бы дважды, а кабинет
 * унаследовал бы canonical публичной страницы.
 */
const TITLE = `EsAI Creators — партнёрская программа — ${SITE_NAME}`;
const DESCRIPTION =
	"Создавайте контент с EsAI и получайте до 25% с каждого платежа привлечённых пользователей — постоянно. Выплаты в USDT TRC20.";

export const metadata: Metadata = {
	title: TITLE,
	description: DESCRIPTION,
	alternates: { canonical: `${SITE_URL}/creators` },
	// Свои openGraph/twitter: иначе ссылка на программу в мессенджере показывала
	// бы карточку главной страницы (унаследованную от корневого layout).
	openGraph: {
		title: TITLE,
		description: DESCRIPTION,
		url: `${SITE_URL}/creators`,
		siteName: SITE_NAME,
		type: "website",
		images: [{ url: OG_IMAGE }],
	},
	twitter: {
		card: "summary_large_image",
		title: TITLE,
		description: DESCRIPTION,
		images: [OG_IMAGE],
	},
	// Пока программа не открыта всем (флаг сборки, как у пунктов меню и карты
	// сайта), страницу в поиск не отдаём: в режиме «только сотрудники»
	// посетитель увидел бы на ней «программа недоступна».
	robots: process.env.NEXT_PUBLIC_CREATORS_NAV === "1" ? undefined : { index: false },
};

export default function CreatorsPage() {
	return (
		<>
			<Header />
			<CreatorsLanding />
			<Footer />
		</>
	);
}
