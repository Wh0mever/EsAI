"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";

type Props = {
  threshold?: number; // px before showing the button
  className?: string;
};

export default function BackToTopButton({ threshold = 100, className = "" }: Props) {
  const { t } = useTranslation("common");
  const [visible, setVisible] = useState(false);
  const tickingRef = useRef(false);

  // read scroll position from the root scrolling element
  const getY = () => {
    const el = document.scrollingElement || document.documentElement;
    return el ? el.scrollTop : window.scrollY || 0;
  };

  useEffect(() => {
    const onScroll = () => {
      if (tickingRef.current) return;
      tickingRef.current = true;
      requestAnimationFrame(() => {
        setVisible(getY() >= threshold);
        tickingRef.current = false;
      });
    };

    // init
    setVisible(getY() >= threshold);

    // single passive listener is enough
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [threshold]);

  const prefersNoMotion =
    typeof window !== "undefined" &&
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const scrollToTop = useCallback(() => {
    const behavior: ScrollBehavior = prefersNoMotion ? "auto" : "smooth";
    // scroll the scrollingElement if present, else window
    const el = document.scrollingElement || document.documentElement;
    if (el && el.scrollTo) el.scrollTo({ top: 0, behavior });
    else window.scrollTo({ top: 0, behavior });
  }, [prefersNoMotion]);

  return (
    <button
      type="button"
      onClick={scrollToTop}
      aria-label={t("common.back_to_top", { defaultValue: "Back to top" })}
      title={t("common.back_to_top", { defaultValue: "Back to top" })}
      className={[
        "fixed right-4 bottom-6 md:right-6 md:bottom-6 z-[1000] cursor-pointer",
        "h-12 w-12 rounded-full border border-border",
        "bg-surface-2/80 backdrop-blur shadow-lg",
        "transition-all duration-300",
        visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-4 pointer-events-none",
        "hover:bg-surface-3 active:scale-95 focus:outline-none focus:ring-2 focus:ring-yellow-400/60",
        "text-foreground",
        className,
      ].join(" ")}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          scrollToTop();
        }
      }}
      style={{ WebkitTapHighlightColor: "transparent" }}
    >
      {/* simple up arrow */}
      <svg viewBox="0 0 24 24" className="mx-auto h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M6 15l6-6 6 6" />
      </svg>
    </button>
  );
}
