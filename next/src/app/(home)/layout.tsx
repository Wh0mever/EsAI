import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";

// Главная «/» — хаб платформы (этап A6) с шапкой и подвалом сайта.
// Чат (полноэкранный, со своей верхней строкой и боковой панелью) — на /chat.
export default function HomeLayout({ children }: Readonly<{ children: React.ReactNode }>) {
	return (
		<div className="min-h-[100dvh] bg-background text-foreground">
			<Header />
			{children}
			<Footer />
		</div>
	);
}
