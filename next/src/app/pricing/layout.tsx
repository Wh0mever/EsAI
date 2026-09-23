import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { SITE_NAME, SITE_URL } from "@/lib/seo/site";
import { tokenPackagesJsonLd } from "@/lib/seo/jsonLd";
import { getPackages } from "@/lib/content";

/** «Про — 490 сом, Премиум — 990 сом, …» по тем пакетам, что сейчас продаются. */
function packagesLine(sep: string, withDash: boolean, list: { name: string; price: number }[]) {
	return list
		.map((p) => `${p.name}${withDash ? " — " : " "}${Math.round(p.price)}${withDash ? " сом" : ""}`)
		.join(sep);
}

export async function generateMetadata(): Promise<Metadata> {
	// Цены — из API: вписанные руками, они обещали снятый пакет за 190 сом.
	const packages = await getPackages();
	const full = packages.length
		? `Пакеты кредитов EsAI: ${packagesLine(", ", true, packages)}. `
		: "Пакеты кредитов EsAI без подписок. ";
	const short = packages.length
		? `Пакеты кредитов EsAI: ${packagesLine(", ", false, packages)} сом. `
		: "Пакеты кредитов EsAI. ";
	return {
		title: `Тарифы EsAI — пакеты кредитов, оплата в сомах без подписок`,
		description:
			full +
			"Доступ ко всем нейросетям (ChatGPT, Claude, Gemini, DeepSeek, Grok, Perplexity). Оплата в кыргызских сомах, без подписок.",
		alternates: { canonical: `${SITE_URL}/pricing` },
		openGraph: {
			title: "Тарифы EsAI — оплата в сомах, без подписок",
			description: short + "Все нейросети в одном месте.",
			url: `${SITE_URL}/pricing`,
			siteName: SITE_NAME,
			type: "website",
		},
	};
}

export default async function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	const packages = await getPackages();
	return (
		<>
			{/* Product/AggregateOffer для rich-результата по ценам в выдаче —
			    только если пакеты удалось получить: неверные цены хуже никаких. */}
			{packages.length > 0 && (
				<script
					type="application/ld+json"
					dangerouslySetInnerHTML={{ __html: JSON.stringify(tokenPackagesJsonLd(packages)) }}
				/>
			)}
			<Header />
			{children}
			<Footer />
		</>
	);
}
