import { NextResponse } from "next/server";

import { isAllowedUiHost } from "./host-policy.mjs";

export function proxy(request) {
  if (!isAllowedUiHost(request.headers.get("host"))) {
    return new NextResponse("Invalid host header", { status: 400 });
  }
  return NextResponse.next();
}
