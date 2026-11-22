import "@/assets/style.scss";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { CREATIVE_TOOLS, toolById } from "@/lib/creative/tools";
import { OG_IMAGE, OG_IMAGE_ALT, OG_IMAGE_META, SITE_NAME, SITE_URL } from "@/lib/seo/site";
import { CREATIVE_NAV } from "@/lib/nav/menu";
import { preload } from "react-dom";
import ToolSoon from "@/components/creative/ToolSoon";

// Страница инструмента. На этапе A3 — заглушка «скоро»; форма появится на B3.
export function generateStaticParams() {
	return CREATIVE_TOOLS.map((t) => ({ tool: t.id }));
}
export const dynamicParams = false;

type Params = { params: Promise<{ tool: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
	const tool = toolById((await params).tool);
	if (!tool) return {};
	const title = `${tool.name} — Creative Studio | ${SITE_NAME}`;
	return {
		title,
		description: tool.desc,
		alternates: { canonical: `/creative/${tool.id}` },
		// Индексируется вместе с разделом (флаг сборки NEXT_PUBLIC_CREATIVE_NAV, см. creative/layout.tsx).
		robots: { index: CREATIVE_NAV, follow: true },
		openGraph: {
			images: [OG_IMAGE_META],
			title,
			description: tool.desc,
			url: `${SITE_URL}/creative/${tool.id}`,
			siteName: SITE_NAME,
			type: "website",
		},
		twitter: { card: "summary_large_image", title, description: tool.desc, images: [{ url: OG_IMAGE, alt: OG_IMAGE_ALT }] },
	};
}

export default async function ToolPage({ params }: Params) {
	const tool = toolById((await params).tool);
	if (!tool) notFound();
	if (tool.img) {
		preload(`${tool.img}-960.webp`, {
			as: "image",
			fetchPriority: "high",
			imageSrcSet: `${tool.img}-320.webp 320w, ${tool.img}-480.webp 480w, ${tool.img}-960.webp 960w`,
			imageSizes: "(min-width: 1280px) 570px, (min-width: 768px) 45vw, 100vw",
		});
	}
	return <ToolSoon id={tool.id} />;
}
