import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";

// Метаданные — в page.tsx: им нужен номер страницы (?page=), а searchParams есть только у страницы.
export default function AcademyLayout({ children }: { children: React.ReactNode }) {
  return (
    // Страница следует выбранной теме: цвета внутри — на токенах.
    <div className="min-h-[100dvh] bg-background text-foreground">
      <Header />
      {children}
      <Footer />
    </div>
  );
}
