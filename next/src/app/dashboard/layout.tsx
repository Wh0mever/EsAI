import type { Metadata } from "next";
// import Header from "@/components/Header/Header";

export const metadata: Metadata = {
	title: "EsAI — Все AI в одном месте",
	description: "EsAI — все нейросети в одном месте. ChatGPT, DeepSeek, Claude, Gemini онлайн.",
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<>
			{children}
		</>
	);
}
