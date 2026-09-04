// Proxies browser requests to the API with the server-held key, so the key never reaches the
// client. Both verbs are forwarded: reads for the pages, writes for recording a decision and
// starting an investigation.
import { NextRequest, NextResponse } from "next/server";

const RAW_BASE = process.env.SIGNALALPHA_API_BASE ?? "http://localhost:8000";
const BASE = /^https?:\/\//.test(RAW_BASE) ? RAW_BASE : `http://${RAW_BASE}`;
const KEY = process.env.SIGNALALPHA_API_KEY ?? "";
const DATASET = process.env.SIGNALALPHA_DATASET ?? "mock";

function target(req: NextRequest, path: string[]): URL {
  const url = new URL(`/api/v1/${path.join("/")}`, BASE);
  req.nextUrl.searchParams.forEach((v, k) => url.searchParams.set(k, v));
  url.searchParams.set("dataset", DATASET);
  return url;
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return KEY ? { ...extra, "X-API-Key": KEY } : extra;
}

async function relay(res: Response): Promise<NextResponse> {
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
  });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return relay(await fetch(target(req, path), { headers: headers(), cache: "no-store" }));
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const body = await req.text();
  return relay(
    await fetch(target(req, path), {
      method: "POST",
      headers: headers({ "content-type": req.headers.get("content-type") ?? "application/json" }),
      body: body || undefined,
      cache: "no-store",
    }),
  );
}
