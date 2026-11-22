import { FaFilm, FaImage, FaUserAstronaut, FaBullhorn } from "react-icons/fa6";
import type { CreativeTool } from "@/lib/creative/tools";

// Превью карточки: WebP 16:9 из public/images/creative/tools/<id>-320|480|960.webp
// (картинки клиента от 22.11, конвертация — creative-studio/work/img_1122.py).
// Без картинки — заглушка того же размера (градиент категории + значок).
const ART = {
  video: { from: "#3b1d0a", to: "#0b0b0d", Icon: FaFilm },
  image: { from: "#2a1140", to: "#0b0b0d", Icon: FaImage },
  characters: { from: "#0f2a3a", to: "#0b0b0d", Icon: FaUserAstronaut },
  ads: { from: "#3a2a05", to: "#0b0b0d", Icon: FaBullhorn },
} as const;

// Ширина картинки в карточке. Телефон: 2 колонки, превью 16:9 целиком (~50vw).
// От 640 px карточка 4:3, и 16:9 при object-cover рисуется в 1,33 раза шире
// карточки: 2 колонки → 67vw, 3 колонки → 45vw, 5 колонок по ~240 px → 320 px.
const CARD_SIZES = "(min-width: 1280px) 320px, (min-width: 768px) 45vw, (min-width: 640px) 67vw, 50vw";

// fetchPriority="high" — только для главной картинки страницы инструмента (LCP);
// в каталоге первые карточки грузятся сразу (priority), но без высокого приоритета:
// там LCP — первый экран.
export default function ToolArt({
  tool,
  priority = false,
  sizes = CARD_SIZES,
  fetchPriority,
}: {
  tool: CreativeTool;
  priority?: boolean;
  sizes?: string;
  fetchPriority?: "high" | "low" | "auto";
}) {
  if (tool.img) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={`${tool.img}-960.webp`}
        srcSet={`${tool.img}-320.webp 320w, ${tool.img}-480.webp 480w, ${tool.img}-960.webp 960w`}
        sizes={sizes}
        alt=""
        loading={priority || fetchPriority === "high" ? "eager" : "lazy"}
        fetchPriority={fetchPriority}
        decoding={fetchPriority === "high" ? "sync" : "async"}
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
