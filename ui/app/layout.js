import "./globals.css";
import Header from "./components/Header";

export const metadata = {
  title: "Trading Engine — MOCK",
  description: "Local paper-trading and prospective research dashboard.",
};

// Header pulls live /meta; never cache the shell.
export const dynamic = "force-dynamic";

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <Header />
        <main className="page">{children}</main>
      </body>
    </html>
  );
}
