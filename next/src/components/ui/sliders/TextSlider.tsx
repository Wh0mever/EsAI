'use client';

import React, { useEffect, useState } from "react";

interface TextSliderProps {
  slides: React.ReactNode[];
  delay?: number;
}

export default function TextSlider({ slides, delay = 3000 }: TextSliderProps) {
  const [currentIndex, setCurrentIndex] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentIndex((prev) => (prev + 1) % slides.length);
    }, delay);
    return () => clearInterval(interval);
  }, [slides.length, delay]);

  return (
    <div className="w-full max-w-xl mx-auto flex flex-col items-center">
      {/* Слайдер */}
      <div className="relative overflow-hidden h-32 w-full">
        <div
          className="flex transition-transform duration-700 ease-in-out"
          style={{ transform: `translateX(-${currentIndex * 100}%)` }}
        >
          {slides.map((content, index) => (
            <div
              key={index}
              className="w-full flex-shrink-0 flex items-center justify-center text-xl font-semibold"
            >
              {content}
            </div>
          ))}
        </div>
      </div>

      {/* Буллеты */}
      <div className="mt-4 flex gap-2">
        {slides.map((_, index) => (
          <div
            key={index}
            className={`w-3 h-3 transition-all duration-500 ${
              currentIndex === index ? "bg-indigo-600 px-4 rounded-xl" : "bg-gray-400 rounded-full"
            }`}
          />
        ))}
      </div>
    </div>
  );
}
