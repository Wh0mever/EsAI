// app/layout.tsx
"use client";

import { AppsConfigProvider } from "@/context/AppsConfigContext";
import SideBar from "@/components/Admin/SideBar/SideBar";

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<AppsConfigProvider>
			<div className="flex w-full h-screen">
				<SideBar />
				<main className="flex-1 p-3 overflow-auto">{children}</main>
			</div>
		</AppsConfigProvider>
	);
}
