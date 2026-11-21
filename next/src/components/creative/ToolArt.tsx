import { FaFilm, FaImage, FaUserAstronaut, FaBullhorn } from "react-icons/fa6";
import type { CreativeTool } from "@/lib/creative/tools";

// Превью карточки. Пока клиент не прислал 15 превью — заглушка того же
// размера (градиент категории + значок), чтобы сетка не прыгала при замене.
// Когда превью появится: положить WebP в public/images/creative/tools/ и
// вписать путь в поле img реестра (lib/creative/tools.ts).
const ART = {
  video: { from: "#3b1d0a", to: "#0b0b0d", Icon: FaFilm },
  image: { from: "#2a1140", to: "#0b0b0d", Icon: FaImage },
  characters: { from: "#0f2a3a", to: "#0b0b0d", Icon: FaUserAstronaut },
  ads: { from: "#3a2a05", to: "#0b0b0d", Icon: FaBullhorn },
} as const;

export default function ToolArt({ tool, priority = false }: { tool: CreativeTool; priority?: boolean }) {
  if (tool.img) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={tool.img}
        alt=""
        loading={priority ? "eager" : "lazy"}
        decoding="async"
        className="absolute inset-0 size-full object-cover transition-transform duration-500 group-hover:scale-[1.03]"
      />
    );
  }
  const a = ART[tool.cat];
  return (
    <span
      aria-hidden="true"
      className="absolute inset-0 grid place-items-center"
      style={{ background: `radial-gradient(120% 90% at 70% 15%, ${a.from} 0%, ${a.to} 70%)` }}
    >
      <a.Icon className="mb-10 size-10 text-[#F5C518]/35 transition-transform duration-500 group-hover:scale-110" />
    </span>
  );
}
