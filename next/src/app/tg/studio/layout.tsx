import type { Viewport } from "next";
import VsThemeScope from "@/components/vstudio/ui/VsThemeScope";

// Как у /studio: страница сжимается под клавиатуру, и док остаётся над ней.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
};

/**
 * Мультстудия внутри Telegram: та же оболочка и палитра студии, что на сайте
 * (vs-root + VsThemeScope). Вход и индексацию решает родитель /tg.
 */
export default function TgStudioLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="vs-root min-h-[100dvh] bg-background text-foreground">
      <VsThemeScope />
      {children}
    </div>
  );
}
