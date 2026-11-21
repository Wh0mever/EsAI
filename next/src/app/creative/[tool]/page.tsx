import "@/assets/style.scss";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { CREATIVE_TOOLS, toolById } from "@/lib/creative/tools";
import { SITE_NAME } from "@/lib/seo/site";
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
	return {
		title: `${tool.name} — Creative Studio | ${SITE_NAME}`,
		description: tool.desc,
		alternates: { canonical: `/creative/${tool.id}` },
		robots: { index: false, follow: true },
	};
}

export default async function ToolPage({ params }: Params) {
	const tool = toolById((await params).tool);
	if (!tool) notFound();
	return <ToolSoon id={tool.id} />;
}
