import "./globals.css";
import Navbar from "./components/Navbar";

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
        <div className="page-wrapper">{children}</div>
      </body>
    </html>
  );
}
