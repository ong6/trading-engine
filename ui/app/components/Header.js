import Link from "next/link";
import { apiFetch } from "../lib/api";
import { fmtTime } from "../lib/format";
import RegimeBadge from "./RegimeBadge";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/league", label: "League" },
  { href: "/positions", label: "Positions" },
  { href: "/journal", label: "Journal" },
];

// Persistent header on every page: unmissable MOCK banner, regime badge, and
// data-freshness stamps from /meta. Rendered server-side so the banner and real
// values are present in the initial HTML.
export default async function Header() {
  const res = await apiFetch("/meta");
  const meta = (res.ok && res.data && res.data.meta) || {};
  const regime = meta.regime || null;

  return (
    <header className="header">
      <div className="mock-banner">
        ★ MOCK — paper only · no real orders, no broker, no money ★
      </div>
      <div className="header-row">
        <span className="brand">Trading Engine</span>
        <nav className="nav">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href}>
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="header-meta">
          <span>
            <span className="k">regime </span>
            <RegimeBadge regime={regime} />
          </span>
          <span>
            <span className="k">last run </span>
            {res.busy ? "db busy" : fmtTime(meta.last_run)}
          </span>
          <span>
            <span className="k">last screen </span>
            {res.busy ? "db busy" : fmtTime(meta.last_screen)}
          </span>
        </div>
      </div>
    </header>
  );
}
