"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

/** ===== Utils ===== **/
type LangList = Record<string, string[]>;

function useDefaultTextList(): string[] {
  // i18n strings may contain multi-byte chars; Array.from handles this later
  const { i18n } = useTranslation();
  const lang = i18n.language ?? "ru";
  const list: LangList = {
    ru: ["Текст", "Песни", "Голоса", "Музыка", "Обложки"],
    en: ["Text", "Songs", "Voices", "Music", "Covers"],
    kg: ["Текст", "Ырлар", "Үндөр", "Музыка", "Капкактар"],
  };
  return list[lang] || list.kg;
}

/** ===== Core: per-letter animated word ===== **/
function AnimatedWord({
  text,
  className = "",
  letterClassName = "",
  staggerMs = 120,
  letterTransitionMs = 500,
  easing = "cubic-bezier(0.22, 1, 0.36, 1)",
}: {
  text: string;
  className?: string;
  letterClassName?: string;
  staggerMs?: number;         // delay between letters
  letterTransitionMs?: number; // per-letter transition duration
  easing?: string;            // CSS timing function
}) {
  const [play, setPlay] = useState(false);

  // Re-run entrance on text change by remounting letters key + toggling play
  useEffect(() => {
    // next tick -> allow transition from initial state
    const id = requestAnimationFrame(() => setPlay(true));
    return () => {
      cancelAnimationFrame(id);
      setPlay(false);
    };
  }, [text]);

  const chars = useMemo(() => Array.from(text), [text]);

  return (
    <span
      className={[
        "inline-flex items-baseline gap-[0.02em] will-change-transform will-change-opacity select-none",
        className,
      ].join(" ")}
      aria-label={text}
    >
      {chars.map((ch, i) => (
        <span
          key={`${ch}-${i}`}
          className={[
            "inline-block transition",
            // start state (before play)
            play ? "opacity-100 translate-y-0" : "opacity-0 translate-y-[0.35em]",
            letterClassName,
          ].join(" ")}
          style={{
            transitionProperty: "opacity, transform",
            transitionDuration: `${letterTransitionMs}ms`,
            transitionTimingFunction: easing,
            transitionDelay: `${i * staggerMs}ms`,
          }}
        >
          {ch === " " ? "\u00A0" : ch}
        </span>
      ))}
    </span>
  );
}

/** ===== Tag wrapper (chip-like background) ===== **/
export function TextTag({
  text = "Текст",
  className = "",
}: {
  text?: string;
  className?: string;
}) {
  return (
    <div className="px-6 py-3 rounded-xl bg-indigo-600/20 w-fit">
      <span className={["text-sm font-bold", className].join(" ")}>{text}</span>
    </div>
  );
}

/** ===== Simple big headline, cycling by delay ===== **/
export function TextChanging({
  textList,
  delay = 3000,
  outDuration = 200, // word fade-out before switch
  staggerMs = 40,
  letterTransitionMs = 300,
}: {
  textList?: string[];
  delay?: number;
  outDuration?: number;       // must be < delay
  staggerMs?: number;
  letterTransitionMs?: number;
}) {
  const list = textList ?? useDefaultTextList();
  const safeDelay = Math.max(delay, outDuration + 50);
  const [idx, setIdx] = useState(0);
  const [show, setShow] = useState(true);
  const timerRef = useRef<number | null>(null);
  const outRef = useRef<number | null>(null);

  useEffect(() => {
    // schedule fade-out a bit before switch
    timerRef.current = window.setInterval(() => {
      setShow(false);
      outRef.current = window.setTimeout(() => {
        setIdx((p) => (p + 1) % list.length);
        setShow(true);
      }, outDuration);
    }, safeDelay) as unknown as number;

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (outRef.current) clearTimeout(outRef.current);
    };
  }, [list.length, safeDelay, outDuration]);

  return (
    <p
      className={[
        "text-5xl font-bold text-center text-rose-500 transition-opacity duration-200",
        show ? "opacity-100" : "opacity-0",
      ].join(" ")}
    >
      <AnimatedWord
        text={list[idx]}
        staggerMs={staggerMs}
        letterTransitionMs={letterTransitionMs}
      />
    </p>
  );
}

/** ===== Chip-style cycling tag ===== **/
export function TextChangingTag({
  textList,
  className = "",
  delay = 3000,
  outDuration = 200,
  staggerMs = 30,
  letterTransitionMs = 260,
}: {
  textList?: string[];
  delay?: number;
  outDuration?: number;
  className?: string;
  staggerMs?: number;
  letterTransitionMs?: number;
}) {
  const list = textList ?? useDefaultTextList();
  const safeDelay = Math.max(delay, outDuration + 50);
  const [idx, setIdx] = useState(0);
  const [show, setShow] = useState(true);
  const timerRef = useRef<number | null>(null);
  const outRef = useRef<number | null>(null);

  useEffect(() => {
    timerRef.current = window.setInterval(() => {
      setShow(false);
      outRef.current = window.setTimeout(() => {
        setIdx((p) => (p + 1) % list.length);
        setShow(true);
      }, outDuration);
    }, safeDelay) as unknown as number;

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (outRef.current) clearTimeout(outRef.current);
    };
  }, [list.length, safeDelay, outDuration]);

  return (
    <div
      className={[
        "px-7 py-3 rounded-xl bg-indigo-600/20 w-fit overflow-hidden flex items-center justify-center",
        "transition-opacity duration-200",
        show ? "opacity-100" : "opacity-0",
        className,
      ].join(" ")}
    >
      <AnimatedWord
        text={list[idx]}
        letterClassName="text-sm font-bold"
        staggerMs={staggerMs}
        letterTransitionMs={letterTransitionMs}
      />
    </div>
  );
}
