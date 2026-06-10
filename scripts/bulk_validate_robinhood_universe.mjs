import path from "node:path";

import {
  RobinhoodFastClient,
  readCsv,
  requireEnv,
  writeCsv,
} from "./rh_fast_mcp_client.mjs";

const root = process.cwd();
const account = process.env.RH_ACCOUNT_NUMBER;
const needed = Number.parseInt(process.env.RH_VALIDATION_NEEDED || "1518", 10);
const today = process.env.RH_VALIDATION_DATE || "2026-06-10";
const candidatePath =
  process.env.RH_CANDIDATES_PATH ||
  path.join(root, "data/runtime/universe-expansion-candidates.csv");
const validationPath =
  process.env.RH_VALIDATIONS_PATH ||
  path.join(root, "data/runtime/universe-expansion.validations.csv");
const rejectedPath =
  process.env.RH_REJECTIONS_PATH ||
  path.join(root, "data/runtime/universe-expansion.rejections.csv");

async function main() {
  requireEnv("RH_ACCOUNT_NUMBER");
  const client = new RobinhoodFastClient({ clientName: "codex-bulk-validator" });
  const candidates = readCsv(candidatePath);
  const valid = [];
  const rejected = [];
  let calls = 0;

  for (let index = 0; index < candidates.length && valid.length < needed; index += 10) {
    const batch = candidates.slice(index, index + 10);
    const symbols = batch.map((item) => item.symbol);
    const bySymbol = new Map(batch.map((item) => [item.symbol, item]));
    const payload = await client.tool("get_equity_tradability", {
      account_number: account,
      symbols,
    });

    calls += 1;

    for (const result of payload.data?.results || []) {
      const candidate = bySymbol.get(result.symbol) || {
        symbol: result.symbol,
        name: result.name || "",
        bucket: "",
      };
      const eligible =
        result.state === "active" &&
        result.tradeable === true &&
        result.fractional_tradability === "tradable";
      if (eligible && valid.length < needed) {
        valid.push({
          symbol: result.symbol,
          name: result.name || candidate.name,
          asset_type: "stock",
          tradable: "true",
          fractional_eligible: "true",
          active: "true",
          source: "robinhood_validated",
          updated_at: today,
        });
      } else if (!eligible) {
        rejected.push({
          symbol: result.symbol,
          name: result.name || candidate.name,
          bucket: candidate.bucket,
          state: result.state || "",
          tradeable: String(result.tradeable),
          fractional_tradability: result.fractional_tradability || "",
          reason: "not_active_tradable_fractional",
        });
      }
    }

    for (const symbol of payload.data?.not_found || []) {
      const candidate = bySymbol.get(symbol) || { symbol, name: "", bucket: "" };
      rejected.push({
        symbol,
        name: candidate.name,
        bucket: candidate.bucket,
        state: "not_found",
        tradeable: "false",
        fractional_tradability: "",
        reason: "not_found",
      });
    }

    if (calls % 25 === 0 || valid.length >= needed) {
      console.error(
        JSON.stringify({
          calls,
          checked: Math.min(index + 10, candidates.length),
          valid: valid.length,
          rejected: rejected.length,
          last: symbols.at(-1),
        }),
      );
    }
  }

  writeCsv(validationPath, valid, [
    "symbol",
    "name",
    "asset_type",
    "tradable",
    "fractional_eligible",
    "active",
    "source",
    "updated_at",
  ]);
  writeCsv(rejectedPath, rejected, [
    "symbol",
    "name",
    "bucket",
    "state",
    "tradeable",
    "fractional_tradability",
    "reason",
  ]);

  console.log(
    JSON.stringify({
      needed,
      validated: valid.length,
      rejected: rejected.length,
      calls,
      candidate_count: candidates.length,
      validationPath,
      rejectedPath,
    }),
  );
}

main().catch((error) => {
  console.error(`ERR ${error.stack || error.message}`);
  process.exit(1);
});
