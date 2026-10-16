import CartoonStudio from "@/components/studio/CartoonStudio";

// Та же студия, что на /studio, но внутри Telegram: вход по данным Mini App
// делает обёртка /tg. Раскладка — всегда одна колонка, как на телефоне, без
// ссылок на страницы сайта (variant="tg").
export default function TgStudioPage() {
  return <CartoonStudio variant="tg" />;
}
