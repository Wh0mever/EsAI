"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Nav from "./Nav";
import LangSwitch from "./LangSwitch";
import AuthButtons from "@/components/auth/AuthButtons";
import NextLink from "../ui/nextLink/NextLink";
import EsaiLogo from "@/components/brand/EsaiLogo";


export default function Header() {
	const { t } = useTranslation("common");
	const [open, setOpen] = useState(false);
	const [scrolled, setScrolled] = useState(false);
	const [hidden, setHidden] = useState(false);

	const lastYRef = useRef(0);
	const tickingRef = useRef(false);

	// lock page scroll when mobile menu open
	useEffect(() => {
		document.body.classList.toggle("overflow-hidden", open);
	}, [open]);

	useEffect(() => {
		const rootEl = document.scrollingElement || document.documentElement;
		const getY = () => (rootEl ? rootEl.scrollTop : 0);

		const rafState = { ticking: false };
		const last = { y: 0 };

		const handle = () => {
			if (rafState.ticking) return;
			rafState.ticking = true;

			requestAnimationFrame(() => {
				const y = getY();
				const was = last.y;

				setScrolled(y > 10);

				if (open) {
					setHidden(false);
				} else if (y <= 50) {
					setHidden(false);
				} else {
					const down = y > was + 2;
					const upEnough = was - y >= 8;
					if (down) setHidden(true);
					else if (upEnough) setHidden(false);
				}

				last.y = y;
				rafState.ticking = false;
			});
		};

		// init
		last.y = getY();
		setScrolled(last.y > 10);

		rootEl.addEventListener("scroll", handle, { passive: true });

		window.addEventListener("scroll", handle, { passive: true });

		document.addEventListener("scroll", handle, { passive: true });

		handle();

		return () => {
			rootEl.removeEventListener("scroll", handle);
			window.removeEventListener("scroll", handle);
			document.removeEventListener("scroll", handle);
		};
	}, [open]);
	const closeMenu = () => setOpen(false);

	return (
		<header
			className={[
				"fixed w-full z-[200] select-none transition-transform duration-300",
				"will-change-transform",
				hidden ? "-translate-y-full" : "translate-y-0",
				scrolled ? "bg-background/20 backdrop-blur" : "",
				// pt учитывает вырез iOS (safe-area) в установленном PWA, иначе
				// лого/меню налезали на системную строку (время/сеть/зарядку).
				"pb-2 pt-[calc(0.5rem_+_env(safe-area-inset-top,0px))]",
				// На 1024–1535 px полей 80 px десктопному меню не хватает: у вошедшего
				// шапка уезжала за край. Мобильные 40 px — как были.
				"px-10 lg:px-4 xl:px-10 2xl:px-20",
			].join(" ")}
		>
			{/* gap при justify-between — лишь минимум, он заметен только в тесноте: на 1024 px
			    у вошедшего по-кыргызски, да ещё с полосой прокрутки Windows (~16 px), больший
			    зазор вытолкнул бы кнопки входа за поле шапки. */}
			<div className="flex items-center justify-between gap-5 lg:gap-2">
				<div className="flex items-center gap-4">
					<button
						className="lg:hidden cursor-pointer inline-flex h-12 w-12 items-center justify-center rounded-xl border border-border bg-surface-2/70 backdrop-blur active:scale-95"
						aria-label={
							open
								? t("common.close_menu", { defaultValue: "Close menu" })
								: t("common.open_menu", { defaultValue: "Open menu" })
						}
						aria-expanded={open}
						onClick={() => setOpen((v) => !v)}
					>
						<span className="relative block h-5 w-6">
							<span
								className={`absolute left-0 top-0 h-0.5 w-6 bg-foreground transition-transform ${
									open ? "translate-y-2 rotate-45" : ""
								}`}
							/>
							<span
								className={`absolute left-0 top-2 h-0.5 w-6 bg-foreground transition-opacity ${
									open ? "opacity-0" : "opacity-100"
								}`}
							/>
							<span
								className={`absolute left-0 top-4 h-0.5 w-6 bg-foreground transition-transform ${
									open ? "-translate-y-2 -rotate-45" : ""
								}`}
							/>
						</span>
					</button>

					<NextLink href="/">
						<EsaiLogo className="h-9 w-auto max-w-[150px]" />
					</NextLink>
				</div>

				<div className="hidden lg:flex">
					<Nav variant="desktop" />
				</div>

				<AuthButtons />
			</div>

			{/* overlay */}
			<div
				className={`lg:hidden fixed inset-0 z-[190] transition-opacity ${
					open ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"
				}`}
				onClick={closeMenu}
			>
				<div className="absolute inset-0 bg-black/50" />
			</div>

			{/* mobile drawer */}
			<aside
				className={`lg:hidden fixed right-0 top-0 z-[200] h-dvh w-[88%] max-w-[420px]
	bg-surface/95 text-foreground backdrop-blur-xl border-l border-border
	transition-transform will-change-transform
	${open ? "translate-x-0" : "translate-x-full"} 
	flex flex-col`} // make column
			>
				<div className="shrink-0 flex items-center justify-between gap-3 px-6 pb-6 pt-[calc(1.5rem_+_env(safe-area-inset-top,0px))]">
					<EsaiLogo className="h-8 w-auto" />
					<div className="flex items-center gap-3">
						{/* Компактный переключатель языка — вынесен из меню (запрос клиента) */}
						<LangSwitch />
						<button
							className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-border bg-surface-2 active:scale-95 cursor-pointer"
							onClick={closeMenu}
							aria-label={t("common.close", { defaultValue: "Close" })}
						>
							<svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2}>
								<path d="M6 6l12 12M18 6L6 18" />
							</svg>
						</button>
					</div>
				</div>

				{/* scrollable content */}
				<div
					className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-4
				[padding-bottom:env(safe-area-inset-bottom)]"
					style={{ WebkitOverflowScrolling: "touch" }}
				>
					<Nav variant="mobile" onNavigate={closeMenu} />
				</div>
			</aside>
		</header>
	);
}
