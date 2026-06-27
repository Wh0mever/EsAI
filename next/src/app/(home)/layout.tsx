// The root route `/` is the EsAI chat workspace (full-screen, no marketing
// header/footer). It renders its own top bar and sidebar.
export default function HomeLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return <>{children}</>;
}
