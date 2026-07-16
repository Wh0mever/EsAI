import type { CSSProperties } from "react";

type Tone = "auto" | "ondark" | "onlight";

/**
 * EsaiLogo — брендовый логотип EsAI, подстраивающийся под тему.
 *
 * «Es» берёт цвет текущей темы через currentColor (класс text-foreground:
 * тёмный в светлой теме, светлый в тёмной — следует data-theme, и ручному, и
 * системному). «AI» и звезда — золотые (#F5C518), видны на любом фоне.
 *
 * tone:
 *  - "auto"   — «Es» = currentColor (по теме). По умолчанию.
 *  - "ondark" — «Es» принудительно белое (для всегда-тёмных поверхностей,
 *               напр. левая панель экрана входа).
 *  - "onlight"— «Es» принудительно тёмное.
 *
 * Размер задаётся через className (как у <img>): напр. className="h-8 w-auto".
 */
export default function EsaiLogo({
  className = "",
  tone = "auto",
  style,
}: {
  className?: string;
  tone?: Tone;
  style?: CSSProperties;
}) {
  const es = tone === "ondark" ? "#ffffff" : tone === "onlight" ? "#141414" : "currentColor";
  const cls = (tone === "auto" ? `text-foreground ${className}` : className).trim();
  return (
    <svg
      viewBox="0 0 400 170"
      role="img"
      aria-label="EsAI"
      className={cls}
      style={style}
      xmlns="http://www.w3.org/2000/svg"
    >
      <text
        x="8"
        y="132"
        fontFamily="'Inter','Helvetica Neue',Arial,sans-serif"
        fontWeight="800"
        letterSpacing="-6"
      >
        <tspan fontSize="155" fill={es}>E</tspan>
        <tspan fontSize="98" fill={es}>s</tspan>
        <tspan fontSize="155" fill="#F5C518">A</tspan>
        <tspan fontSize="155" fill="#F5C518">I</tspan>
      </text>
      {/* 4-конечная золотая звезда-искра над I */}
      <path d="M348 6 Q348 40 384 40 Q348 40 348 74 Q348 40 312 40 Q348 40 348 6 Z" fill="#F5C518" />
    </svg>
  );
}
