'use client';

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import "./NextLink.scss";

interface NextLinkProps {
	children: React.ReactNode;
	href: string;
	className?: string;
}

export default function NextLink(NextLinkProps: NextLinkProps) {
	const { children, href, className } = NextLinkProps;
	const pathname = usePathname();

	const active = pathname === href ? true : false;

	return (
		<Link
			href={href}
			className={`link cursor-pointer select-none flex items-center gap-2 rounded-3xl transition-all duration-300 font-bold ${className} ${
				active ? "text-blue-500 active" : ""
			}`}
		>
			{children}
		</Link>
	);
}
