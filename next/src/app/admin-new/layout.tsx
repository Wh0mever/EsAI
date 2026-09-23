import type { Metadata } from "next";
import type { ReactNode } from "react";
import AdminShell from "./AdminShell";

// Серверный layout ради metadata: служебная панель не должна попадать в
// поиск (robots.txt её только не обходит, а noindex гарантирует, что по
// внешней ссылке она тоже не проиндексируется).
export const metadata: Metadata = {
  title: "Админка EsAI",
  robots: { index: false, follow: false },
};

export default function AdminNewLayout({ children }: { children: ReactNode }) {
  return <AdminShell>{children}</AdminShell>;
}
