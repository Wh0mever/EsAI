"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import Radar from "@/components/global/Radar";
import { TextChangingTag } from "@/components/ui/text/Text";

const IMAGE_WIDTH = 120;     // px
const IMAGE_HEIGHT = 100;    // px
const GAP = 8;               // px (tailwind gap-2)
const IMAGE_COUNT = 23;

const getImagePath = (i: number) => `/images/decorations/aigenerated/${i}.webp`;
const range = (n: number) => Array.from({ length: n }, (_, i) => i);
const shuffle = <T,>(arr: T[]) => [...arr].sort(() => Math.random() - 0.5);

function ImageItem({ src, index }: { src: string; index: number }) {
  return (
    <div
      className="relative flex-none"
      style={{ width: IMAGE_WIDTH, height: IMAGE_HEIGHT, marginRight: GAP }}
    >
      <Image
        src={src}
        alt={`AI ${index + 1}`}
        fill
        sizes={`${IMAGE_WIDTH}px`}
        className="object-cover rounded-md"
        draggable={false}
        priority={index < 6}
      />
    </div>
  );
}

function MarqueeRow({
  images,
  pxPerSec = 30,
  reverse = false,
}: {
  images: string[];
  pxPerSec?: number;
  reverse?: boolean;
}) {
  const totalPx = images.length * (IMAGE_WIDTH + GAP);
  const duration = Math.max(8, totalPx / pxPerSec); // s
  const doubled = useMemo(() => [...images, ...images], [images]);

  return (
    <div className="overflow-hidden w-full" style={{ height: IMAGE_HEIGHT }}>
      <div
        className="flex will-change-transform"
        style={{
          width: "max-content",
          animation: `${reverse ? "marquee-rev" : "marquee"} ${duration}s linear infinite`,
        }}
      >
        {doubled.map((src, i) => (
          <ImageItem key={i} src={src} index={i} />
        ))}
      </div>
    </div>
  );
}

/** Bounce-ряд: один замер ширины, потом CSS-анимация с alternate. */
function BounceRow({
  images,
  pxPerSec = 50,
}: {
  images: string[];
  pxPerSec?: number;
}) {
  const outerRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);
  const [vars, setVars] = useState<{ shiftPx: number; duration: number }>({ shiftPx: 0, duration: 10 });

  useEffect(() => {
    const measure = () => {
      const outer = outerRef.current;
      const inner = innerRef.current;
      if (!outer || !inner) return;

      const outerW = outer.clientWidth;
      const innerW = inner.scrollWidth;
      const shiftPx = Math.max(0, innerW - outerW); // насколько уезжаем влево
      const duration = Math.max(6, shiftPx / pxPerSec);
      setVars({ shiftPx, duration });
    };

    measure();
    const ro = new ResizeObserver(measure);
    if (outerRef.current) ro.observe(outerRef.current);
    return () => ro.disconnect();
  }, [images, pxPerSec]);

  return (
    <div ref={outerRef} className="overflow-hidden w-full" style={{ height: IMAGE_HEIGHT }}>
      <div
        ref={innerRef}
        className="flex will-change-transform"
        style={{
          width: "max-content",
          animation: `bounce ${vars.duration}s ease-in-out infinite alternate`,
          // CSS var для амплитуды
          ["--shift" as any]: `${vars.shiftPx}px`,
        }}
      >
        {images.map((src, i) => (
          <ImageItem key={i} src={src} index={i} />
        ))}
      </div>
    </div>
  );
}

export default function AIGalleryStrips() {
  const [rows, setRows] = useState<string[][]>([]);

  useEffect(() => {
    const indices = range(IMAGE_COUNT).map((i) => i + 1);
    setRows([
      shuffle(indices).map(getImagePath),
      shuffle(indices).map(getImagePath),
      shuffle(indices).map(getImagePath),
    ]);
  }, []);

  if (rows.length < 3) return null;

  return (
    <div className="flex flex-col gap-4 relative">
      <style jsx global>{`
        @keyframes marquee {
          from { transform: translate3d(0, 0, 0); }
          to   { transform: translate3d(-50%, 0, 0); } /* уезжаем на ширину первой половины */
        }
        @keyframes marquee-rev {
          from { transform: translate3d(-50%, 0, 0); }
          to   { transform: translate3d(0, 0, 0); }
        }
        @keyframes bounce {
          from { transform: translate3d(0, 0, 0); }
          to   { transform: translate3d(calc(var(--shift) * -1), 0, 0); }
        }
        /* Мелкие улучшения стабильности верстки */
        img { backface-visibility: hidden; }
      `}</style>

      <div className="absolute z-50 inset-0 flex items-center justify-center pointer-events-none">
        <div className="px-4 py-2 min-w-22 absolute top-5">
          <TextChangingTag className="text-white" />
        </div>
        <Radar />
      </div>

      <MarqueeRow images={rows[0]} pxPerSec={55} />
      <MarqueeRow images={rows[1]} pxPerSec={60} reverse />
      <BounceRow images={rows[2]} pxPerSec={45} />
    </div>
  );
}
