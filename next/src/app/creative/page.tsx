import "@/assets/style.scss";
import { Suspense } from "react";
import CreativeCatalog from "@/components/creative/CreativeCatalog";

// useSearchParams (фильтр ?cat=) требует Suspense вокруг клиентского компонента.
export default function CreativePage() {
	return (
		<Suspense fallback={<main className="min-h-[100dvh]" />}>
			<CreativeCatalog />
		</Suspense>
	);
}
