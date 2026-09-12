import { createReadStream, promises as fs, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import type { IncomingMessage, ServerResponse } from "node:http";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

export const deliveryDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../data/derived/web-delivery");
const require = createRequire(import.meta.url);
const maplibrePackageDirectory = path.dirname(require.resolve("maplibre-gl/package.json"));

type Middleware = (request: IncomingMessage, response: ServerResponse, next: () => void) => void | Promise<void>;

const contentTypes: Record<string, string> = {
  ".geojson": "application/geo+json; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".tif": "image/tiff",
  ".tiff": "image/tiff",
};

function isWithinDirectory(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return relative !== "" && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}

function sendText(response: ServerResponse, statusCode: number, message: string): void {
  response.statusCode = statusCode;
  response.setHeader("Content-Type", "text/plain; charset=utf-8");
  response.end(message);
}

export function createGeoAssetMiddleware(rootDirectory: string = deliveryDirectory): Middleware {
  const root = path.resolve(rootDirectory);
  return async (request, response, next) => {
    if (request.method !== "GET" && request.method !== "HEAD") {
      next();
      return;
    }
    const rawPathname = (request.url ?? "/").split("?", 1)[0];
    if (rawPathname !== "/geo" && !rawPathname.startsWith("/geo/")) {
      next();
      return;
    }

    let relativePath: string;
    try {
      relativePath = decodeURIComponent(rawPathname.slice("/geo/".length));
    } catch {
      sendText(response, 400, "Invalid asset path");
      return;
    }
    const assetPath = path.resolve(root, relativePath);
    if (!isWithinDirectory(root, assetPath)) {
      sendText(response, 400, "Invalid asset path");
      return;
    }

    let realRoot: string;
    let realAssetPath: string;
    try {
      [realRoot, realAssetPath] = await Promise.all([fs.realpath(root), fs.realpath(assetPath)]);
    } catch {
      sendText(response, 404, "Asset not found");
      return;
    }
    if (!isWithinDirectory(realRoot, realAssetPath)) {
      sendText(response, 400, "Invalid asset path");
      return;
    }

    let stats;
    try {
      stats = await fs.stat(realAssetPath);
    } catch {
      sendText(response, 404, "Asset not found");
      return;
    }
    if (!stats.isFile()) {
      sendText(response, 404, "Asset not found");
      return;
    }

    response.setHeader("Accept-Ranges", "bytes");
    response.setHeader("Content-Type", contentTypes[path.extname(realAssetPath).toLowerCase()] ?? "application/octet-stream");
    const rangeHeader = request.headers.range;
    if (typeof rangeHeader === "string") {
      const range = parseByteRange(rangeHeader, stats.size);
      if (!range) {
        response.statusCode = 416;
        response.setHeader("Content-Range", `bytes */${stats.size}`);
        response.end();
        return;
      }

      const { start, end } = range;
      response.statusCode = 206;
      response.setHeader("Content-Length", end - start + 1);
      response.setHeader("Content-Range", `bytes ${start}-${end}/${stats.size}`);
      if (request.method === "HEAD") {
        response.end();
        return;
      }
      createReadStream(realAssetPath, { start, end }).pipe(response);
      return;
    }

    response.statusCode = 200;
    response.setHeader("Content-Length", stats.size);
    if (request.method === "HEAD") {
      response.end();
      return;
    }
    createReadStream(realAssetPath).pipe(response);
  };
}

function rangeAssetMiddleware(): Plugin {
  const configure = (server: { middlewares: { use: (middleware: Middleware) => void } }): void => {
    server.middlewares.use(createGeoAssetMiddleware());
  };
  return {
    name: "geo-range-assets",
    configureServer: configure,
    configurePreviewServer: configure,
  };
}

function emitMapLibreSharedWorker(): Plugin {
  return {
    name: "emit-maplibre-shared-worker",
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "assets/maplibre-gl-shared.mjs",
        source: readFileSync(path.join(maplibrePackageDirectory, "dist/maplibre-gl-shared.mjs")),
      });
    },
  };
}

export function parseByteRange(
  header: string,
  size: number,
): { start: number; end: number } | undefined {
  const match = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (!match) return undefined;

  const [, startText, endText] = match;
  let start: number;
  let end: number;
  if (startText === "") {
    const suffixLength = Number(endText);
    if (!Number.isInteger(suffixLength) || suffixLength <= 0) return undefined;
    start = Math.max(size - suffixLength, 0);
    end = size - 1;
  } else {
    start = Number(startText);
    end = endText === "" ? size - 1 : Number(endText);
  }

  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || start > end || start >= size) {
    return undefined;
  }
  return { start, end: Math.min(end, size - 1) };
}

export default defineConfig({
  publicDir: false,
  plugins: [react(), rangeAssetMiddleware(), emitMapLibreSharedWorker()],
  optimizeDeps: { exclude: ["maplibre-gl"] },
  server: { port: 5173, strictPort: true },
  build: { sourcemap: false },
});
