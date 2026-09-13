import HeaderOperationalStatus from "./HeaderOperationalStatus";
import HeaderResearchStatus from "./HeaderResearchStatus";

export default function HeaderStatus({ res }) {
  const data = res.ok && res.data ? res.data : {};
  return (
    <div className="header-meta">
      <HeaderOperationalStatus res={res} data={data} />
      <HeaderResearchStatus res={res} data={data} />
    </div>
  );
}
