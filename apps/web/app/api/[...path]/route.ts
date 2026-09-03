// Proxies browser requests to the API with the server-held key (client components only).
import { NextRequest, NextResponse } from "next/server";

const RAW_BASE = process.env.SIGNALALPHA_API_BASE ?? "http://localhost:8000";
const BASE = /^https?:\/\//.test(RAW_BASE) ? RAW_BASE : `http://${RAW_BASE}`;
const KEY = process.env.SIGNALALPHA_API_KEY ?? "";
const DATASET = process.env.SIGNALALPHA_DATASET ?? "mock";

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const url = new URL(`/api/v1/${path.join("/")}`, BASE);
  req.nextUrl.searchParams.forEach((v, k) => url.searchParams.set(k, v));
  url.searchParams.set("dataset", DATASET);
  const res = await fetch(url, { headers: KEY ? { "X-API-Key": KEY } : {}, cache: "no-store" });
  return new NextResponse(await res.text(), { status: res.status, headers: { "content-type": "application/json" } });
}
