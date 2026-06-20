import fs from "node:fs";
import path from "node:path";

import {
  RobinhoodFastClient,
  readCsv,
  writeCsv,
  writeJson,
} from "./rh_fast_mcp_client.mjs";

const NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt";
const OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt";
const UNIVERSE_FIELDS = [
  "symbol",
  "name",
  "asset_type",
  "tradable",
  "fractional_eligible",
  "active",
  "source",
  "updated_at",
];
const CANDIDATE_FIELDS = [
  "symbol",
  "name",
  "bucket",
  "source_file",
  "exchange",
  "market_category",
  "source_updated_at",
];
const LOCAL_REJECTION_FIELDS = [...CANDIDATE_FIELDS, "reason"];
const BROKER_REJECTION_FIELDS = [
  "symbol",
  "name",
  "bucket",
  "state",
  "tradeable",
  "fractional_tradability",
  "reason",
];

const root = process.cwd();

function mainOptions(argv) {
  const options = {
    account: process.env.RH_ACCOUNT_NUMBER || "",
    asOf: todayPacific(),
    batchSize: 10,
    candidateLimit: 0,
    dryRun: false,
    pauseMs: 250,
    run: false,
    runtimeRoot: path.join(root, "data/runtime/monthly-universe-discovery"),
    universePath: path.join(root, "data/universe.csv"),
    validationLimit: 0,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const value = argv[index + 1];
    if (arg === "--account") {
      options.account = value || "";
      index += 1;
    } else if (arg === "--as-of") {
      options.asOf = value || "";
      index += 1;
    } else if (arg === "--batch-size") {
      options.batchSize = Number.parseInt(value || "", 10);
      index += 1;
    } else if (arg === "--candidate-limit") {
      options.candidateLimit = Number.parseInt(value || "", 10);
      index += 1;
    } else if (arg === "--dry-run") {
      options.dryRun = true;
    } else if (arg === "--pause-ms") {
      options.pauseMs = Number.parseInt(value || "", 10);
      index += 1;
    } else if (arg === "--run") {
      options.run = true;
    } else if (arg === "--runtime-root") {
      options.runtimeRoot = path.resolve(value || "");
      index += 1;
    } else if (arg === "--universe") {
      options.universePath = path.resolve(value || "");
      index += 1;
    } else if (arg === "--validation-limit") {
      options.validationLimit = Number.parseInt(value || "", 10);
      index += 1;
    } else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  if (!options.run && !options.dryRun) {
    throw new Error("Pass --run to merge results, or --dry-run to build candidates only.");
  }
  if (!options.dryRun && !options.account) {
    throw new Error("--account or RH_ACCOUNT_NUMBER is required with --run.");
  }
  if (!Number.isFinite(options.batchSize) || options.batchSize < 1 || options.batchSize > 25) {
    throw new Error("--batch-size must be between 1 and 25.");
  }
  if (!Number.isFinite(options.pauseMs) || options.pauseMs < 0) {
    throw new Error("--pause-ms must be zero or greater.");
  }
  return options;
}

function printHelp() {
  console.log(`Usage:
  node scripts/monthly_universe_discovery.mjs --run --account 878067701
  node scripts/monthly_universe_discovery.mjs --dry-run --candidate-limit 25

Fetches current Nasdaq Trader symbol directories, filters likely common-stock
candidates not already in data/universe.csv, validates them through Robinhood
when --run is provided, writes evidence under data/runtime/monthly-universe-discovery,
and merges only active/tradable/fractional symbols into data/universe.csv.`);
}

async function main() {
  const options = mainOptions(process.argv.slice(2));
  const runDir = path.join(options.runtimeRoot, options.asOf);
  fs.mkdirSync(runDir, { recursive: true });

  const existingRows = fs.existsSync(options.universePath) ? readCsv(options.universePath) : [];
  const existingSymbols = new Set(existingRows.map((row) => normalizeSymbol(row.symbol)).filter(Boolean));
  const sources = await fetchSources(runDir);
  const parsedRows = [
    ...parseNasdaqRows(sources.nasdaq, "nasdaqlisted"),
    ...parseNasdaqRows(sources.other, "otherlisted"),
  ];
  const { candidates, localRejections } = buildCandidates(parsedRows, existingSymbols, options.asOf);
  const limitedCandidates =
    options.candidateLimit > 0 ? candidates.slice(0, options.candidateLimit) : candidates;

  const candidatesPath = path.join(runDir, "candidates.csv");
  const localRejectionsPath = path.join(runDir, "local-filter-rejections.csv");
  writeCsv(candidatesPath, limitedCandidates, CANDIDATE_FIELDS);
  writeCsv(localRejectionsPath, localRejections, LOCAL_REJECTION_FIELDS);

  const validation = options.dryRun
    ? { accepted: [], rejected: [], calls: 0, checked: 0, skipped: true }
    : await validateThroughRobinhood(limitedCandidates, options);

  const validationsPath = path.join(runDir, "validations.csv");
  const rejectionsPath = path.join(runDir, "rejections.csv");
  writeCsv(validationsPath, validation.accepted, UNIVERSE_FIELDS);
  writeCsv(rejectionsPath, validation.rejected, BROKER_REJECTION_FIELDS);

  const merge = options.dryRun
    ? summarizeUniverse(existingRows, options.universePath)
    : mergeUniverse(options.universePath, existingRows, validation.accepted);
  const summary = {
    as_of: options.asOf,
    mode: options.dryRun ? "dry_run" : "run",
    source_rows: parsedRows.length,
    existing_universe_rows: existingRows.length,
    candidates: candidates.length,
    candidates_written: limitedCandidates.length,
    local_rejections: localRejections.length,
    broker_checked: validation.checked,
    broker_calls: validation.calls,
    accepted: validation.accepted.length,
    rejected: validation.rejected.length,
    universe_before: merge.before,
    universe_after: merge.after,
    universe_added: merge.added,
    universe_refreshed: merge.refreshed,
    universe_usable: merge.usable,
    paths: {
      run_dir: runDir,
      candidates: candidatesPath,
      local_filter_rejections: localRejectionsPath,
      validations: validationsPath,
      rejections: rejectionsPath,
      summary_json: path.join(runDir, "summary.json"),
      summary_md: path.join(runDir, "summary.md"),
      universe: options.universePath,
    },
  };

  writeJson(summary.paths.summary_json, summary);
  writeSummary(summary.paths.summary_md, summary);
  console.log(JSON.stringify(summary, null, 2));
}

async function fetchSources(runDir) {
  const [nasdaq, other] = await Promise.all([
    fetchText(NASDAQ_LISTED_URL),
    fetchText(OTHER_LISTED_URL),
  ]);
  fs.writeFileSync(path.join(runDir, "nasdaqlisted.txt"), nasdaq);
  fs.writeFileSync(path.join(runDir, "otherlisted.txt"), other);
  return { nasdaq, other };
}

async function fetchText(url) {
  const response = await fetch(url, {
    headers: { "user-agent": "codex-robinhood-universe-discovery/1.0" },
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}: HTTP ${response.status}`);
  }
  return response.text();
}

function parseNasdaqRows(text, sourceFile) {
  const lines = text.split(/\r?\n/).filter(Boolean);
  const headerLine = lines.find((line) => line.includes("|") && !line.startsWith("File Creation"));
  if (!headerLine) {
    throw new Error(`No header found in ${sourceFile}`);
  }
  const header = headerLine.split("|");
  const rows = [];
  for (const line of lines.slice(lines.indexOf(headerLine) + 1)) {
    if (!line.includes("|") || line.startsWith("File Creation")) {
      continue;
    }
    const columns = line.split("|");
    if (columns.length < header.length) {
      continue;
    }
    const raw = Object.fromEntries(header.map((key, index) => [key, columns[index] || ""]));
    const symbol = normalizeSymbol(raw.Symbol || raw["ACT Symbol"]);
    const name = (raw["Security Name"] || raw["Security Name"] || "").trim();
    rows.push({
      symbol,
      name,
      source_file: sourceFile,
      exchange: (raw.Exchange || "").trim(),
      market_category: (raw["Market Category"] || "").trim(),
      etf: (raw.ETF || "").trim().toUpperCase(),
      test_issue: (raw["Test Issue"] || "").trim().toUpperCase(),
    });
  }
  return rows;
}

function buildCandidates(rows, existingSymbols, asOf) {
  const seen = new Set();
  const candidates = [];
  const localRejections = [];
  const sortedRows = rows
    .map((row) => ({ ...row, bucket: bucketFor(row), priority: priorityFor(row) }))
    .sort((left, right) => left.priority - right.priority || left.symbol.localeCompare(right.symbol));

  for (const row of sortedRows) {
    const base = candidateRow(row, asOf);
    const reason = localRejectionReason(row, existingSymbols, seen);
    if (reason) {
      localRejections.push({ ...base, reason });
      continue;
    }
    seen.add(row.symbol);
    candidates.push(base);
  }
  return { candidates, localRejections };
}

function candidateRow(row, asOf) {
  return {
    symbol: row.symbol,
    name: row.name,
    bucket: row.bucket,
    source_file: row.source_file,
    exchange: row.exchange,
    market_category: row.market_category,
    source_updated_at: asOf,
  };
}

function localRejectionReason(row, existingSymbols, seen) {
  if (!row.symbol) {
    return "blank_symbol";
  }
  if (seen.has(row.symbol)) {
    return "duplicate_source_symbol";
  }
  if (existingSymbols.has(row.symbol)) {
    return "existing_universe";
  }
  if (row.test_issue === "Y") {
    return "test_issue";
  }
  if (row.etf === "Y") {
    return "etf";
  }
  if (/[$^+/=]/.test(row.symbol)) {
    return "symbol_suffix_non_common";
  }
  if (nonCommonName(row.name)) {
    return "name_excluded_non_common";
  }
  if (!commonStockName(row.name)) {
    return "name_not_common_stock_candidate";
  }
  return "";
}

function commonStockName(name) {
  const text = name.toLowerCase();
  return [
    /\bcommon stock\b/,
    /\bcommon shares?\b/,
    /\bordinary shares?\b/,
    /\bamerican depositary\b/,
    /\bdepositary shares?\b/,
    /\bads\b/,
  ].some((pattern) => pattern.test(text));
}

function nonCommonName(name) {
  const text = name.toLowerCase();
  return [
    /\bwarrants?\b/,
    /\bright to purchase\b/,
    /\brights\b/,
    /\bunits?\b/,
    /\bpreferred\b/,
    /\bpreference\b/,
    /\bnotes? due\b/,
    /\bsenior notes?\b/,
    /\bdebentures?\b/,
    /\bbonds?\b/,
    /\betn\b/,
    /\bexchange traded fund\b/,
    /\bclosed end fund\b/,
  ].some((pattern) => pattern.test(text));
}

function bucketFor(row) {
  if (row.source_file === "nasdaqlisted") {
    if (row.market_category === "Q") {
      return "nasdaq_global_select_common";
    }
    if (row.market_category === "G") {
      return "nasdaq_global_market_common";
    }
    if (row.market_category === "S") {
      return "nasdaq_capital_market_common";
    }
    return "nasdaq_common";
  }
  if (row.exchange === "N") {
    return "nyse_common";
  }
  if (row.exchange === "A") {
    return "nyse_american_common";
  }
  if (row.exchange === "P") {
    return "nyse_arca_common";
  }
  if (row.exchange === "Z") {
    return "cboe_common";
  }
  return "other_listed_common";
}

function priorityFor(row) {
  return {
    nasdaq_global_select_common: 10,
    nasdaq_global_market_common: 20,
    nasdaq_capital_market_common: 30,
    nyse_common: 40,
    nyse_american_common: 50,
    other_listed_common: 60,
    cboe_common: 70,
    nyse_arca_common: 80,
    nasdaq_common: 90,
  }[bucketFor(row)] ?? 100;
}

async function validateThroughRobinhood(candidates, options) {
  const client = new RobinhoodFastClient({ clientName: "codex-monthly-universe-discovery" });
  const accepted = [];
  const rejected = [];
  let calls = 0;
  let checked = 0;
  const limit =
    options.validationLimit > 0 ? Math.min(options.validationLimit, candidates.length) : candidates.length;

  for (let index = 0; index < limit; index += options.batchSize) {
    const batch = candidates.slice(index, Math.min(index + options.batchSize, limit));
    const symbols = batch.map((item) => item.symbol);
    const bySymbol = new Map(batch.map((item) => [item.symbol, item]));
    const payload = await client.tool("get_equity_tradability", {
      account_number: options.account,
      symbols,
    });
    calls += 1;
    checked += batch.length;

    const seen = new Set();
    for (const result of payload.data?.results || []) {
      const symbol = normalizeSymbol(result.symbol);
      const candidate = bySymbol.get(symbol) || { symbol, name: result.name || "", bucket: "" };
      seen.add(symbol);
      const eligible =
        result.state === "active" &&
        result.tradeable === true &&
        result.fractional_tradability === "tradable";
      if (eligible) {
        accepted.push({
          symbol,
          name: result.name || candidate.name,
          asset_type: "stock",
          tradable: "true",
          fractional_eligible: "true",
          active: "true",
          source: "robinhood_validated",
          updated_at: options.asOf,
        });
      } else {
        rejected.push({
          symbol,
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
      const normalized = normalizeSymbol(symbol);
      const candidate = bySymbol.get(normalized) || { symbol: normalized, name: "", bucket: "" };
      seen.add(normalized);
      rejected.push({
        symbol: normalized,
        name: candidate.name,
        bucket: candidate.bucket,
        state: "not_found",
        tradeable: "false",
        fractional_tradability: "",
        reason: "not_found",
      });
    }

    for (const symbol of symbols.filter((item) => !seen.has(item))) {
      const candidate = bySymbol.get(symbol) || { symbol, name: "", bucket: "" };
      rejected.push({
        symbol,
        name: candidate.name,
        bucket: candidate.bucket,
        state: "missing_result",
        tradeable: "false",
        fractional_tradability: "",
        reason: "missing_broker_result",
      });
    }

    if (calls % 10 === 0 || checked >= limit) {
      console.error(JSON.stringify({ calls, checked, accepted: accepted.length, rejected: rejected.length }));
    }
    if (options.pauseMs > 0 && checked < limit) {
      await new Promise((resolve) => setTimeout(resolve, options.pauseMs));
    }
  }

  return { accepted, rejected, calls, checked, skipped: false };
}

function mergeUniverse(universePath, existingRows, validations) {
  const bySymbol = new Map();
  for (const row of existingRows) {
    const symbol = normalizeSymbol(row.symbol);
    if (symbol) {
      bySymbol.set(symbol, normalizeUniverseRow({ ...row, symbol }));
    }
  }

  let added = 0;
  let refreshed = 0;
  for (const validation of validations) {
    const symbol = normalizeSymbol(validation.symbol);
    if (!symbol) {
      continue;
    }
    if (bySymbol.has(symbol)) {
      refreshed += 1;
    } else {
      added += 1;
    }
    bySymbol.set(symbol, normalizeUniverseRow({ ...validation, symbol }));
  }

  const merged = Array.from(bySymbol.values()).sort((left, right) =>
    left.symbol.localeCompare(right.symbol),
  );
  writeCsv(universePath, merged, UNIVERSE_FIELDS);
  return { before: existingRows.length, after: merged.length, added, refreshed, usable: usableCount(merged) };
}

function summarizeUniverse(rows, universePath) {
  return {
    before: rows.length,
    after: rows.length,
    added: 0,
    refreshed: 0,
    usable: usableCount(rows),
    path: universePath,
  };
}

function normalizeUniverseRow(row) {
  return {
    symbol: normalizeSymbol(row.symbol),
    name: row.name || "",
    asset_type: row.asset_type || "stock",
    tradable: boolText(row.tradable),
    fractional_eligible: boolText(row.fractional_eligible),
    active: boolText(row.active),
    source: row.source || "robinhood_validated",
    updated_at: row.updated_at || "",
  };
}

function usableCount(rows) {
  return rows.filter(
    (row) =>
      normalizeBool(row.active) &&
      normalizeBool(row.tradable) &&
      normalizeBool(row.fractional_eligible),
  ).length;
}

function writeSummary(filePath, summary) {
  const lines = [
    "# Monthly Universe Discovery",
    "",
    `- as_of: ${summary.as_of}`,
    `- mode: ${summary.mode}`,
    `- source_rows: ${summary.source_rows}`,
    `- existing_universe_rows: ${summary.existing_universe_rows}`,
    `- candidates: ${summary.candidates}`,
    `- candidates_written: ${summary.candidates_written}`,
    `- local_rejections: ${summary.local_rejections}`,
    `- broker_checked: ${summary.broker_checked}`,
    `- broker_calls: ${summary.broker_calls}`,
    `- accepted: ${summary.accepted}`,
    `- rejected: ${summary.rejected}`,
    `- universe_before: ${summary.universe_before}`,
    `- universe_after: ${summary.universe_after}`,
    `- universe_added: ${summary.universe_added}`,
    `- universe_refreshed: ${summary.universe_refreshed}`,
    `- universe_usable: ${summary.universe_usable}`,
    "",
    "## Artifacts",
    "",
    ...Object.entries(summary.paths).map(([key, value]) => `- ${key}: ${value}`),
    "",
  ];
  fs.writeFileSync(filePath, lines.join("\n"));
}

function normalizeSymbol(symbol) {
  return String(symbol || "").trim().toUpperCase();
}

function normalizeBool(value) {
  return ["1", "true", "yes", "y"].includes(String(value || "").trim().toLowerCase());
}

function boolText(value) {
  return normalizeBool(value) ? "true" : "false";
}

function todayPacific() {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${byType.year}-${byType.month}-${byType.day}`;
}

main().catch((error) => {
  console.error(`ERR ${error.stack || error.message}`);
  process.exit(1);
});
