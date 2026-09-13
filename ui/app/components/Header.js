import Link from "next/link";
import { getMeta } from "../lib/server-api";
import HeaderStatus from "./HeaderStatus";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/league", label: "League" },
  { href: "/positions", label: "Positions" },
  { href: "/journal", label: "Journal" },
];

// Persistent header on every page: unmissable MOCK banner, navigation, and
// fail-visible status from the request-memoized /meta projection.
export default async function Header() {
  const res = await getMeta();
  return (
    <header className="header">
      <div className="mock-banner">
        ★ MOCK — paper only · no real orders, no broker, no money ★
      </div>
      <div className="header-row">
        <span className="brand">Trading Engine</span>
        <nav className="nav">
          {NAV.map((item) => (
            <Link key={item.href} href={item.href}>
              {item.label}
            </Link>
          ))}
        </nav>
        <HeaderStatus res={res} />
      </div>
    </header>
  );
}
