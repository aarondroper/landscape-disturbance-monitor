const DEFAULT_GEO_ASSET_BASE_URL = "/geo/";

function runtimeOrigin(): string {
  if (typeof window !== "undefined" && window.location.origin) return window.location.origin;
  return "http://vite.local";
}

function normalizedPath(path: string): string {
  if (typeof path !== "string" || path.trim() === "") {
    throw new Error("Geospatial asset path must be a non-empty relative path.");
  }
  if (path.includes("?") || path.includes("#") || path.includes("\\")) {
    throw new Error(`Geospatial asset path must not contain a query, fragment, or backslash: ${path}`);
  }

  const cleanPath = path.trim().replace(/^\/+/, "").replace(/\/{2,}/g, "/");
  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(cleanPath);
  } catch {
    throw new Error(`Geospatial asset path contains invalid escaping: ${path}`);
  }
  if (decodedPath.split("/").some((segment) => segment === "." || segment === "..")) {
    throw new Error(`Geospatial asset path must not traverse directories: ${path}`);
  }
  return cleanPath;
}

/** Normalize the configured root-relative or external geospatial asset base. */
export function resolveGeoAssetBaseUrl(rawValue: string | undefined = import.meta.env.VITE_GEO_ASSET_BASE_URL): string {
  const value = rawValue?.trim() || DEFAULT_GEO_ASSET_BASE_URL;
  if (value.includes("?") || value.includes("#") || value.includes("\\")) {
    throw new Error("VITE_GEO_ASSET_BASE_URL must not contain a query, fragment, or backslash.");
  }

  if (value.startsWith("/")) {
    if (value.startsWith("//")) {
      throw new Error("VITE_GEO_ASSET_BASE_URL must be a root-relative path, not a protocol-relative URL.");
    }
    const path = value.replace(/^\/+|\/+$/g, "").replace(/\/{2,}/g, "/");
    if (!path || path.split("/").some((segment) => segment === "." || segment === "..")) {
      throw new Error("VITE_GEO_ASSET_BASE_URL must be a valid root-relative path.");
    }
    return `/${path}/`;
  }

  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`VITE_GEO_ASSET_BASE_URL is not a valid URL or root-relative path: ${value}`);
  }
  if (url.protocol !== "https:" || !url.hostname || url.username || url.password) {
    throw new Error("VITE_GEO_ASSET_BASE_URL must be an absolute HTTPS URL without credentials.");
  }
  const path = url.pathname.replace(/^\/+|\/+$/g, "").replace(/\/{2,}/g, "/");
  url.pathname = path ? `/${path}/` : "/";
  return url.toString();
}

/** Resolve a generated web-delivery path against the configured asset origin. */
export function assetUrl(
  path: string,
  baseUrl: string | undefined = import.meta.env.VITE_GEO_ASSET_BASE_URL,
  origin: string = runtimeOrigin(),
): string {
  const base = resolveGeoAssetBaseUrl(baseUrl);
  const cleanPath = normalizedPath(path);
  try {
    return new URL(`${base}${cleanPath}`, origin).toString();
  } catch {
    throw new Error(`Could not resolve geospatial asset URL for path: ${path}`);
  }
}
