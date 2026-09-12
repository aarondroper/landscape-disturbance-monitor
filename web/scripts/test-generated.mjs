import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";

const packageDirectory = "../data/derived/web-delivery";
if (!existsSync(packageDirectory)) {
  console.log(`Generated-data integration skipped: ${packageDirectory} is absent.`);
  process.exit(0);
}

const result = spawnSync("vitest", ["run", "--config", "vitest.generated.config.ts"], {
  stdio: "inherit",
  shell: process.platform === "win32",
});
process.exit(result.status ?? 1);
