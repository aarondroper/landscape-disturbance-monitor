import { createReadStream, promises as fs, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const deliveryDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../data/derived/web-delivery");
const require = createRequire(import.meta.url);
const maplibrePackageDirectory = path.dirname(require.resolve("maplibre-gl/package.json"));

function rangeAssetMiddleware(): Plugin {
  return {
    name: "dev-range-assets",
    configureServer(server) {
      server.middlewares.use(async (request, response, next) => {
        if (request.method !== "GET" && request.method !== "HEAD") {
          next();
          return;
        }

        const requestUrl = new URL(request.url ?? "/", "http://vite.local");
        const isRasterAsset = requestUrl.pathname.startsWith("/imagery/") || requestUrl.pathname.startsWith("/rasters/");
        if (!isRasterAsset || !request.headers.range) {
          next();
          return;
        }

        const relativePath = decodeURIComponent(requestUrl.pathname).replace(/^\/+/, "");
        const assetPath = path.resolve(deliveryDirectory, relativePath);
        if (!assetPath.startsWith(`${deliveryDirectory}${path.sep}`)) {
          response.statusCode = 400;
          response.end("Invalid asset path");
          return;
        }

        try {
          const stats = await fs.stat(assetPath);
          if (!stats.isFile()) {
            next();
            return;
          }

          const range = parseByteRange(request.headers.range, stats.size);
          if (!range) {
            response.statusCode = 416;
            response.setHeader("Content-Range", `bytes */${stats.size}`);
            response.end();
            return;
          }

          const { start, end } = range;
          response.statusCode = 206;
          response.setHeader("Accept-Ranges", "bytes");
          response.setHeader("Content-Length", end - start + 1);
          response.setHeader("Content-Range", `bytes ${start}-${end}/${stats.size}`);
          response.setHeader("Content-Type", "image/tiff");
          if (request.method === "HEAD") {
            response.end();
            return;
          }
          createReadStream(assetPath, { start, end }).pipe(response);
        } catch {
          next();
        }
      });
    },
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
  publicDir: deliveryDirectory,
  plugins: [react(), rangeAssetMiddleware(), emitMapLibreSharedWorker()],
  optimizeDeps: { exclude: ["maplibre-gl"] },
  server: { port: 5173, strictPort: true },
  build: { sourcemap: false },
});
