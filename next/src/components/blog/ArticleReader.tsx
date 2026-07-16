"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import "./article-reader.scss";

/**
 * ArticleReader — wraps the rendered article and adds a premium, Apple/Google-style
 * scroll reading experience:
 *
 *  1) A fixed top reading-progress bar that fills 0→100% based on how far the user
 *     has scrolled THROUGH the article wrapper (not the whole page). It is hidden
 *     when the article is out of view (progress ~0) and uses rAF-throttled
 *     scroll/resize listeners.
 *
 *  2) A tasteful reveal-on-scroll for each top-level markdown block inside
 *     `.esai-md` — blocks start slightly translated + transparent and animate in
 *     once, with a small stagger, via IntersectionObserver.
 *
 * Honors `prefers-reduced-motion: reduce` (content shown immediately, no motion),
 * is SSR-safe (all DOM work in effects), and degrades gracefully if `.esai-md`
 * is missing.
 */
export default function ArticleReader({ children }: { children: ReactNode }) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const [progress, setProgress] = useState(0);
  const [active, setActive] = useState(false);

  /* ---- Reading progress bar -------------------------------------- */
  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper || typeof window === "undefined") return;

    let frame = 0;

    const compute = () => {
      frame = 0;
      const el = wrapperRef.current;
      if (!el) return;

      const rect = el.getBoundingClientRect();
      const viewport = window.innerHeight || document.documentElement.clientHeight;

      // Total scrollable distance through the article: from the moment its top
      // reaches the viewport top until its bottom reaches the viewport top.
      // `-rect.top` is how far the article top has scrolled past the viewport top.
      const total = rect.height - viewport;

      let ratio: number;
      if (total <= 0) {
        // Article shorter than viewport: full once its top passes the top edge.
        ratio = rect.top <= 0 ? 1 : 0;
      } else {
        ratio = (-rect.top) / total;
      }

      const clamped = Math.min(1, Math.max(0, ratio));

      // Visible if any part of the article overlaps the viewport.
      const inView = rect.bottom > 0 && rect.top < viewport;

      setActive(inView && clamped > 0.001);
      setProgress(clamped);
    };

    const onScroll = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(compute);
    };

    compute();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });

    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);

  /* ---- Reveal-on-scroll for markdown blocks ---------------------- */
  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper || typeof window === "undefined") return;

    const md = wrapper.querySelector<HTMLElement>(".esai-md");
    if (!md) return;

    const blocks = Array.from(md.children) as HTMLElement[];
    if (!blocks.length) return;

    const prefersReduced =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Reduced motion (or no IntersectionObserver): show everything immediately.
    if (prefersReduced || typeof IntersectionObserver === "undefined") {
      blocks.forEach((b) => {
        b.classList.add("reveal", "reveal-in");
      });
      return;
    }

    // Prime each block in the "hidden" pre-reveal state.
    blocks.forEach((b) => b.classList.add("reveal"));

    let revealed = 0;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const el = entry.target as HTMLElement;
          // Small, capped stagger so a screenful doesn't cascade too long.
          const delay = Math.min(revealed * 60, 240);
          el.style.setProperty("--reveal-delay", `${delay}ms`);
          el.classList.add("reveal-in");
          revealed += 1;
          observer.unobserve(el);
        }
      },
      {
        // Trigger a bit before the block is fully in view.
        rootMargin: "0px 0px -12% 0px",
        threshold: 0.05,
      }
    );

    blocks.forEach((b) => observer.observe(b));

    return () => observer.disconnect();
  }, []);

  return (
    <>
      <div
        className="article-progress"
        data-active={active ? "true" : "false"}
        aria-hidden="true"
        role="presentation"
      >
        <div
          className="article-progress__fill"
          style={{ width: `${(progress * 100).toFixed(2)}%` }}
        />
      </div>

      <div ref={wrapperRef}>{children}</div>
    </>
  );
}
