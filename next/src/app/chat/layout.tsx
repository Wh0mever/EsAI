// /chat — рабочий чат EsAI (на весь экран, без шапки и подвала сайта):
// свою верхнюю строку и боковую панель он рисует сам.
export default function ChatLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return <>{children}</>;
}
