import { cp, mkdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");

const sourceDir = path.join(
  projectRoot,
  "node_modules",
  "soaring-symbols",
  "dist",
  "assets"
);
const airlinesJsonPath = path.join(
  projectRoot,
  "node_modules",
  "soaring-symbols",
  "dist",
  "airlines.json"
);
const targetDir = path.join(projectRoot, "public", "airlines");
const generatedDir = path.join(projectRoot, "src", "generated");
const generatedAirlinesPath = path.join(generatedDir, "airlines.ts");

function buildAirlinesModule(airlines) {
  const airlineMap = {};

  for (const airline of airlines) {
    addAirline(airlineMap, airline, airline.slug);

    for (const subsidiary of airline.subsidiaries ?? []) {
      addAirline(airlineMap, subsidiary, airline.slug);
    }
  }

  return `export interface AirlineInfo {
  name: string
  slug?: string
}

export const AIRLINES_BY_CODE: Record<string, AirlineInfo> = ${JSON.stringify(airlineMap, null, 2)} as const
`;
}

function addAirline(airlineMap, airline, fallbackSlug) {
  if (!airline?.iata) {
    return;
  }

  airlineMap[airline.iata] = {
    name: airline.name ?? airline.iata,
    ...(airline.slug || fallbackSlug ? { slug: airline.slug ?? fallbackSlug } : {}),
  };
}

async function main() {
  try {
    const sourceStats = await stat(sourceDir);
    if (!sourceStats.isDirectory()) {
      return;
    }
  } catch {
    return;
  }

  await mkdir(targetDir, { recursive: true });
  await mkdir(generatedDir, { recursive: true });

  await cp(sourceDir, targetDir, { recursive: true, force: true });

  const airlinesJson = await readFile(airlinesJsonPath, "utf8");
  const airlines = JSON.parse(airlinesJson);
  const moduleSource = buildAirlinesModule(airlines);
  await writeFile(generatedAirlinesPath, moduleSource, "utf8");
}

main().catch((error) => {
  console.error("postinstall failed:", error);
  process.exitCode = 1;
});
