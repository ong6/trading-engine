import "server-only";

import { cache } from "react";
import { apiFetch, validateApiResponse } from "./api";
import { isMetaProjection } from "./meta-contracts";

// Request-scoped only: Header and Dashboard share one fresh /meta projection,
// while a later page request still re-reads current operational state.
export const getMeta = cache(async () =>
  validateApiResponse(await apiFetch("/meta"), "meta", isMetaProjection),
);
