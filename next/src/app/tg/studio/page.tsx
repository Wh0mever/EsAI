import CartoonStudio from "@/components/studio/CartoonStudio";

// Та же студия, что на /studio, но внутри Telegram: вход по данным Mini App
// делает обёртка /tg, а компонент не отличает, откуда его открыли.
export default function TgStudioPage() {
  return <CartoonStudio />;
}
