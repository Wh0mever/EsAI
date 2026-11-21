import "@/assets/style.scss";
import type { Metadata } from "next";
import ChatHome from "@/components/chat/ChatHome";

// Главная пока остаётся чатом (как раньше). Тот же чат открыт на /chat.
// После замены главной (этап A6 плана Creative Studio) здесь будет хаб.
// Canonical главной живёт здесь, а не в корневом layout — иначе его
// наследовали все страницы без собственного canonical.
export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

export default function Home() {
  return <ChatHome />;
}
