import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CCTV 이상행동 관제 대시보드",
  description: "노인시설·병원 특화 이상행동 실시간 관제 대시보드",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
