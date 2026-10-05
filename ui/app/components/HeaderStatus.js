import HeaderOperationalStatus from "./HeaderOperationalStatus";
import HeaderResearchStatus from "./HeaderResearchStatus";

export default function HeaderStatus({ res }) {
  const data = res.ok && res.data ? res.data : {};
  return (
    <div className="header-meta" role="region" aria-label="Operational and research status (scroll horizontally for more)" tabIndex={0}>
      <HeaderOperationalStatus res={res} data={data} />
      <HeaderResearchStatus res={res} data={data} />
    </div>
  );
}
