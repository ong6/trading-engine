"use client";

import { useRouter, useSearchParams, usePathname } from "next/navigation";

// A dropdown that rewrites one query-string param and navigates. Server pages
// re-render with the new filter — keeps everything SSR (data present in HTML).
export default function FilterSelect({ param, label, options, value }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  function onChange(e) {
    const v = e.target.value;
    const sp = new URLSearchParams(searchParams.toString());
    if (v === "") sp.delete(param);
    else sp.set(param, v);
    const qs = sp.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname);
  }

  return (
    <div className="field">
      <label>{label}</label>
      <select value={value || ""} onChange={onChange}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}
