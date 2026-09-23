import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";

export const metadata: Metadata = {
  title: "Public Offer | EsAI",
  description: "Public offer for access to the EsAI platform.",
  alternates: { canonical: "/public-offer" },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <>
      <Header />
      {children}
      <Footer />
    </>
  );
}

