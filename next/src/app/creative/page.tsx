import "@/assets/style.scss";
import { Suspense } from "react";
import { preload } from "react-dom";
import CreativeCatalog from "@/components/creative/CreativeCatalog";

// useSearchParams (фильтр ?cat=) требует Suspense вокруг клиентского компонента.
export default function CreativePage() {
	// Первый экран (LCP) приходит с сервера (i18n/settings.ts, SSR_ROUTES); подсказка
	// картинки остаётся — ранний старт загрузки и запасной путь при I18N_SSR=off.
	preload("/images/creative/cs-hero-1280.webp", { as: "image", fetchPriority: "high" });
	return (
		<Suspense fallback={<main className="min-h-[100dvh]" />}>
			<CreativeCatalog />
		</Suspense>
	);
}
