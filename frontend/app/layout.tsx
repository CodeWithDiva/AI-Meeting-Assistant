import "./globals.css";

export const metadata = { title: "AI Meeting Assistant", description: "Meeting notes, transcripts, and action items" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
