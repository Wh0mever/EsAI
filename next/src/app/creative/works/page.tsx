import "@/assets/style.scss";
import type { Metadata } from "next";
import WorksPage from "@/components/creative/works/WorksPage";
import { SITE_NAME } from "@/lib/seo/site";

// «Мои работы» Creative Studio: личный список, в поиск не попадает и в карту
// сайта не входит. Список грузится в браузере после входа (WorksPage).
export const metadata: Metadata = {
	title: `Мои работы — Creative Studio | ${SITE_NAME}`,
	description: "Все работы, созданные в Creative Studio EsAI: картинки и видео, которые можно скачать в любой момент.",
	alternates: { canonical: "/creative/works" },
	robots: { index: false, follow: false },
};

export default function CreativeWorksRoute() {
	return <WorksPage />;
}
