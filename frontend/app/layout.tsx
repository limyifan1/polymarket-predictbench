import type { Metadata } from "next";
import "../styles/globals.css";

export const metadata: Metadata = {
  title: "PredictBench Markets",
  description: "Forecast Polymarket events with LLM experiments",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="app-shell">{children}</body>
    </html>
  );
}
