import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "WenClips | Gerador gratuito de Shorts",
  description: "Transforme vídeos longos em clipes verticais com legendas, cortes inteligentes e sem marca-d'água.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="pt-BR"><body>{children}</body></html>;
}