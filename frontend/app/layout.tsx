import "./globals.css";
import Navbar from "./components/Navbar";
import { DEMO_MODE } from "@/lib/demo";

export const metadata = {
  title: "AI Meeting Assistant — Real-time Notes, Transcripts & Action Items",
  description: "Next-generation AI meeting copilot with automated transcription, smart summaries, decisions, and action item tracking.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <Navbar />
        {DEMO_MODE && (
          <div style={{ textAlign: "center", fontSize: 12.5, padding: "7px 16px", background: "var(--bg-subtle)", color: "var(--text-secondary)", borderBottom: "1px solid var(--border-subtle, rgba(0,0,0,0.06))" }}>
            Demo with sample data. Joining live meetings, transcription and voice run on the assistant&apos;s local backend.
          </div>
        )}
        <div className="page-wrapper">{children}</div>
      </body>
    </html>
  );
}
