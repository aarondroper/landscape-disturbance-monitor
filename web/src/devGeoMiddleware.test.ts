import { PassThrough, Readable } from "node:stream";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { IncomingMessage, ServerResponse } from "node:http";
import { describe, expect, it, vi } from "vitest";
import { createGeoAssetMiddleware, parseByteRange } from "../vite.config";

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

function makeSyntheticDelivery(): string {
  const root = mkdtempSync(join(tmpdir(), "landscape-delivery-test-"));
  mkdirSync(join(root, "data"), { recursive: true });
  mkdirSync(join(root, "imagery", "2018"), { recursive: true });
  mkdirSync(join(root, "rasters", "recovery"), { recursive: true });
  writeFileSync(join(root, "data", "summary.json"), '{"project":{}}');
  writeFileSync(join(root, "imagery", "2018", "rgb.tif"), Buffer.alloc(256, 7));
  writeFileSync(join(root, "rasters", "recovery", "2026.tif"), Buffer.alloc(256, 9));
  return root;
}

async function requestAsset(root: string, method: "GET" | "HEAD", url: string, range?: string): Promise<{ response: TestResponse; body: Buffer }> {
  const response = new TestResponse();
  const chunks: Buffer[] = [];
  response.on("data", (chunk: Buffer) => chunks.push(chunk));
  const complete = new Promise<void>((resolve, reject) => {
    response.once("finish", resolve);
    response.once("error", reject);
  });
  const next = vi.fn();
  await createGeoAssetMiddleware(root)(
    makeRequest(method, url, range),
    response as unknown as ServerResponse,
    next,
  );
  if (!next.mock.calls.length && !response.writableEnded && response.statusCode < 400) await complete;
  expect(next).not.toHaveBeenCalled();
  return { response, body: Buffer.concat(chunks) };
}

describe("local /geo delivery middleware", () => {
  it("serves an ordinary JSON request", async () => {
    const { response, body } = await requestAsset(makeSyntheticDelivery(), "GET", "/geo/data/summary.json");
    expect(response.statusCode).toBe(200);
    expect(response.headers.get("content-type")).toMatch(/^application\/json/);
    expect(body.toString("utf8")).toContain('"project"');
  });

  it("returns a 206 byte range for an imagery COG", async () => {
    const { response, body } = await requestAsset(makeSyntheticDelivery(), "GET", "/geo/imagery/2018/rgb.tif", "bytes=0-99");
    expect(response.statusCode).toBe(206);
    expect(response.headers.get("accept-ranges")).toBe("bytes");
    expect(response.headers.get("content-range")).toMatch(/^bytes 0-99\/\d+$/);
    expect(response.headers.get("content-length")).toBe(100);
    expect(body).toHaveLength(100);
  });

  it("returns a 206 byte range for a recovery COG", async () => {
    const { response, body } = await requestAsset(makeSyntheticDelivery(), "GET", "/geo/rasters/recovery/2026.tif", "bytes=0-99");
    expect(response.statusCode).toBe(206);
    expect(response.headers.get("content-range")).toMatch(/^bytes 0-99\/\d+$/);
    expect(body).toHaveLength(100);
  });

  it("rejects invalid ranges and traversal, and returns 404 for missing assets", async () => {
    expect(parseByteRange("bytes=999999999999-", 1000)).toBeUndefined();
    const root = makeSyntheticDelivery();

    const traversal = await requestAsset(root, "GET", "/geo/%2e%2e/%2e%2e/web/src/data/assetUrl.ts");
    expect(traversal.response.statusCode).toBe(400);

    const missing = await requestAsset(root, "GET", "/geo/data/not-present.json");
    expect(missing.response.statusCode).toBe(404);
  });

  it("supports HEAD without sending a response body", async () => {
    const { response, body } = await requestAsset(makeSyntheticDelivery(), "HEAD", "/geo/data/summary.json");
    expect(response.statusCode).toBe(200);
    expect(response.headers.get("content-length")).toBeGreaterThan(0);
    expect(body).toHaveLength(0);
  });
});
