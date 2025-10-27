import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";

export const metadata: Metadata = {
  title: "Privacy Policy | Vokalo",
  description: "Privacy Policy for the Vokalo AI content platform.",
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

