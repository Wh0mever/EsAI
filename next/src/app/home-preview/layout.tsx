import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";

// Временный адрес новой главной (этап A4) — для согласования с клиентом.
// Закрыт от поиска, не в меню и не в карте сайта. После замены главной (A6)
// этот адрес перенаправляется на «/».
export const metadata: Metadata = {
	title: "EsAI — всё для творчества и работы с ИИ",
	robots: { index: false, follow: false },
};

export default function HomePreviewLayout({ children }: Readonly<{ children: React.ReactNode }>) {
	return (
		<div className="min-h-[100dvh] bg-background text-foreground">
			<Header />
			{children}
			<Footer />
		</div>
	);
}
