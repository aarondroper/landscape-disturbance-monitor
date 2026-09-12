import { PassThrough, Readable } from "node:stream";
import type { IncomingMessage, ServerResponse } from "node:http";
import { describe, expect, it, vi } from "vitest";
import { createGeoAssetMiddleware, deliveryDirectory } from "../vite.config";

class TestResponse extends PassThrough {
  statusCode = 200;
  readonly headers = new Map<string, string | number>();

  setHeader(name: string, value: string | number): this {
    this.headers.set(name.toLowerCase(), value);
    return this;
  }
}

function makeRequest(method: "GET" | "HEAD", url: string, range?: string): IncomingMessage {
  const request = new Readable({ read() { this.push(null); } }) as IncomingMessage;
  Object.assign(request, { method, url, headers: range ? { range } : {} });
  return request;
}

async function requestAsset(
  method: "GET" | "HEAD",
  url: string,
  range?: string,
): Promise<{ response: TestResponse; body: Buffer }> {
  const response = new TestResponse();
  const chunks: Buffer[] = [];
  response.on("data", (chunk: Buffer) => chunks.push(chunk));
  const complete = new Promise<void>((resolve, reject) => {
    response.once("finish", resolve);
    response.once("error", reject);
  });
  const next = vi.fn();
  await createGeoAssetMiddleware(deliveryDirectory)(
    makeRequest(method, url, range),
    response as unknown as ServerResponse,
    next,
  );
  if (!next.mock.calls.length && !response.writableEnded && response.statusCode < 400) await complete;
  expect(next).not.toHaveBeenCalled();
  return { response, body: Buffer.concat(chunks) };
}

describe("generated /geo delivery package", () => {
  it("serves the generated summary JSON", async () => {
    const { response, body } = await requestAsset("GET", "/geo/data/summary.json");
    expect(response.statusCode).toBe(200);
    expect(response.headers.get("content-type")).toMatch(/^application\/json/);
    expect(body.toString("utf8")).toContain('"project"');
  });

  it("returns a byte range for generated imagery", async () => {
    const { response, body } = await requestAsset("GET", "/geo/imagery/2018/rgb.tif", "bytes=0-99");
    expect(response.statusCode).toBe(206);
    expect(response.headers.get("accept-ranges")).toBe("bytes");
    expect(response.headers.get("content-range")).toMatch(/^bytes 0-99\/\d+$/);
    expect(response.headers.get("content-length")).toBe(100);
    expect(body).toHaveLength(100);
  });

  it("returns a byte range for a generated recovery COG", async () => {
    const { response, body } = await requestAsset("GET", "/geo/rasters/recovery/2026.tif", "bytes=0-99");
    expect(response.statusCode).toBe(206);
    expect(response.headers.get("content-range")).toMatch(/^bytes 0-99\/\d+$/);
    expect(body).toHaveLength(100);
  });

  it("supports HEAD for generated JSON without sending a body", async () => {
    const { response, body } = await requestAsset("HEAD", "/geo/data/summary.json");
    expect(response.statusCode).toBe(200);
    expect(response.headers.get("content-length")).toBeGreaterThan(0);
    expect(body).toHaveLength(0);
  });
});
