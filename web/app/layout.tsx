import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "知链",
  description: "连接 LangGraph 多智能体协作链的简洁学习前端",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
