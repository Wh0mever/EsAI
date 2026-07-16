"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type TocItem = { id: string; text: string; level: number };

type Props = {
  items: TocItem[];
};

/**
 * ArticleOutline — premium sticky table of contents (Google/Stripe docs style).
 *
 * - Scroll-spy via IntersectionObserver: the topmost visible heading is "active".
 * - A single moving indicator bar slides to the active link (transform-only, GPU-friendly).
 * - Clicking smooth-scrolls to the heading and updates the hash without a hard jump.
 * - SSR-safe: all DOM work happens in effects; guards for window/document.
 * - Honors prefers-reduced-motion: disables the sliding transition and uses
 *   instant scroll; content/links still fully functional.
 *
 * The parent page is responsible for sticky placement of the surrounding <aside>
 * (e.g. `className="hidden lg:block sticky top-24 self-start"`). This component is
 * self-contained and looks good standalone.
 */
export default function ArticleOutline({ items }: Props) {
  // Stable list of valid items (must have an id + text).
  const toc = useMemo(
    () => items.filter((it) => it && it.id && it.text),
    [items]
  );

  const [activeId, setActiveId] = useState<string>("");
  const [reduceMotion, setReduceMotion] = useState<boolean>(false);

  // Indicator geometry (top offset + height of the active link), in px.
  const [indicator, setIndicator] = useState<{ top: number; height: number; ready: boolean }>({
    top: 0,
    height: 0,
    ready: false,
  });

  const navRef = useRef<HTMLElement | null>(null);
  // Map of itemId -> anchor element, to measure the active link's position.
  const linkRefs = useRef<Map<string, HTMLAnchorElement>>(new Map());
  // Track visible headings so we can always pick the topmost one.
  const visibleRef = useRef<Set<string>>(new Set());

  const setLinkRef = useCallback(
    (id: string) => (el: HTMLAnchorElement | null) => {
      if (el) linkRefs.current.set(id, el);
      else linkRefs.current.delete(id);
    },
    []
  );

  // Detect reduced-motion preference (SSR-safe).
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setReduceMotion(mq.matches);
    apply();
    // addEventListener is supported in all evergreen browsers.
    mq.addEventListener?.("change", apply);
    return () => mq.removeEventListener?.("change", apply);
  }, []);

  // Scroll-spy: observe each heading; the topmost visible heading is active.
  useEffect(() => {
    if (typeof window === "undefined" || typeof document === "undefined") return;
    if (toc.length < 2) return;
    if (!("IntersectionObserver" in window)) return;

    visibleRef.current = new Set();

    const headings = toc
      .map((it) => document.getElementById(it.id))
      .filter((el): el is HTMLElement => Boolean(el));

    if (!headings.length) return;

    // Order ids by document position so "topmost" comparisons are cheap.
    const orderedIds = toc.map((it) => it.id);

    const pickActive = () => {
      // Prefer the topmost currently-visible heading.
      let best = "";
      for (const id of orderedIds) {
        if (visibleRef.current.has(id)) {
          best = id;
          break;
        }
      }
      if (best) {
        setActiveId(best);
        return;
      }
      // Nothing visible (between sections): keep the last heading scrolled past.
      // Find the last heading whose top is above the viewport's reading line.
      const line = 120; // px from top, matches scroll-margin region
      let passed = "";
      for (const id of orderedIds) {
        const el = document.getElementById(id);
        if (!el) continue;
        if (el.getBoundingClientRect().top <= line) passed = id;
        else break;
      }
      // If we found a passed heading use it; otherwise keep current active.
      setActiveId((prev) => passed || prev || orderedIds[0]);
    };

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = entry.target.id;
          if (!id) continue;
          if (entry.isIntersecting) visibleRef.current.add(id);
          else visibleRef.current.delete(id);
        }
        pickActive();
      },
      {
        // Bias the "active" zone toward the upper portion of the viewport,
        // so a heading becomes active as it reaches the top reading area.
        rootMargin: "-80px 0px -65% 0px",
        threshold: [0, 1],
      }
    );

    headings.forEach((h) => observer.observe(h));

    // Initialize once on mount in case the user lands mid-article (hash nav).
    pickActive();

    return () => observer.disconnect();
  }, [toc]);

  // Move the indicator bar to the active link (measured from the nav container).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const nav = navRef.current;
    const link = activeId ? linkRefs.current.get(activeId) : undefined;
    if (!nav || !link) {
      setIndicator((p) => (p.ready ? { ...p, ready: false } : p));
      return;
    }
    const update = () => {
      const navRect = nav.getBoundingClientRect();
      const linkRect = link.getBoundingClientRect();
      setIndicator({
        top: linkRect.top - navRect.top,
        height: linkRect.height,
        ready: true,
      });
    };
    update();
    // Re-measure on resize (line wraps change link heights/positions).
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [activeId, toc, reduceMotion]);

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLAnchorElement>, id: string) => {
      if (typeof document === "undefined") return;
      const target = document.getElementById(id);
      if (!target) return; // let the browser handle the bare hash as fallback
      e.preventDefault();
      setActiveId(id);
      target.scrollIntoView({
        behavior: reduceMotion ? "auto" : "smooth",
        block: "start",
      });
      // Update the hash without triggering a second hard jump.
      try {
        if (window.history?.replaceState) {
          window.history.replaceState(null, "", `#${id}`);
        } else {
          window.location.hash = id;
        }
      } catch {
        /* no-op: hash update is non-critical */
      }
      // Move focus to the heading for accessibility (without re-scrolling).
      if (target instanceof HTMLElement) {
        const hadTabindex = target.hasAttribute("tabindex");
        if (!hadTabindex) target.setAttribute("tabindex", "-1");
        target.focus({ preventScroll: true });
        if (!hadTabindex) {
          // Clean up the temporary tabindex after focus settles.
          const cleanup = () => target.removeAttribute("tabindex");
          target.addEventListener("blur", cleanup, { once: true });
        }
      }
    },
    [reduceMotion]
  );

  if (toc.length < 2) return null;

  return (
    <nav
      ref={navRef}
      aria-label="Содержание статьи"
      className="relative text-sm"
    >
      <p className="mb-3 pl-4 text-xs font-semibold uppercase tracking-wide text-muted-2">
        Содержание
      </p>

      {/* Static rail behind the links */}
      <span
        aria-hidden
        className="pointer-events-none absolute left-0 top-9 bottom-0 w-px bg-border"
      />

      {/* Moving active indicator bar (transform-only for smoothness) */}
      <span
        aria-hidden
        className="pointer-events-none absolute left-0 w-[2px] rounded-full bg-accent"
        style={{
          height: indicator.height,
          transform: `translateY(${indicator.top}px)`,
          opacity: indicator.ready ? 1 : 0,
          transition: reduceMotion
            ? "none"
            : "transform 280ms cubic-bezier(0.22,1,0.36,1), height 280ms cubic-bezier(0.22,1,0.36,1), opacity 200ms ease",
        }}
      />

      <ul className="space-y-0.5">
        {toc.map((it) => {
          const isActive = it.id === activeId;
          return (
            <li key={it.id}>
              <a
                ref={setLinkRef(it.id)}
                href={`#${it.id}`}
                aria-current={isActive ? "location" : undefined}
                onClick={(e) => handleClick(e, it.id)}
                className={[
                  "block rounded-md py-1.5 pr-2 leading-snug",
                  "outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
                  it.level === 3 ? "pl-8" : "pl-4",
                  reduceMotion ? "" : "transition-colors duration-200",
                  isActive
                    ? "font-medium text-accent-strong"
                    : "text-muted hover:text-foreground",
                ]
                  .filter(Boolean)
                  .join(" ")}
              >
                {it.text}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
