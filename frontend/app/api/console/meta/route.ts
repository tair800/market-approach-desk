import { proxy } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return proxy("meta");
}
