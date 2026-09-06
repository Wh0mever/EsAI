import type { Metadata } from "next";
import TgShell from "@/components/tg/TgShell";

// Страницы Mini App: открываются внутри Telegram, поэтому без шапки и
// подвала сайта и без индексации — снаружи они не нужны.
export const metadata: Metadata = {
  title: "EsAI в Telegram",
  robots: { index: false, follow: false },
};

export default function TgLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <TgShell>{children}</TgShell>;
}
