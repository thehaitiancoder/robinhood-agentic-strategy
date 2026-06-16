#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

import {
  RobinhoodFastClient,
  csvValue,
  readCsv,
} from "./rh_fast_mcp_client.mjs";

const POLICY_FIELDS = [
  "symbol",
  "policy",
  "allow_open",
  "allow_reopen",
  "allow_double_down",
  "allow_sell",
  "reason",
  "evidence_source",
  "review_after",
  "updated_at",
];

const GENERATED_EVIDENCE_PATTERNS = [
  /^weekly_intraday_range_/,
  /^yahoo_intraday_range_/,
];

const DEFAULTS = {
  account: "878067701",
  universe: "data/universe.csv",
  policy: "data/symbol-policy.csv",
  outputDir: "data/runtime/weekly-symbol-policy-refresh",
  batchSize: 100,
  sleepMs: 60000,
  symbolPauseMs: 250,
  minSuccessRate: 0.95,
  months: 6,
};

async function main() {
  const { options } = parseArgs(process.argv.slice(2));
  if (optionBool(options, "help")) {
    printUsage();
    return;
  }
  if (optionBool(options, "self-test")) {
    await runSelfTest();
    return;
  }

  const config = buildConfig(options);
  ensureWeekendOrAllowed(config);

  fs.mkdirSync(config.outputDir, { recursive: true });
  const universeRows = readUniverseRows(config.universe);
  const symbols = uniqueSorted(universeRows.map((row) => symbolOf(row)).filter(Boolean));
  const ownedSymbols = await readOwnedSymbols(config);
  const state = loadOrCreateState(config, symbols);

  await refreshMetrics({ config, state, symbols });
  const finalState = writeStateArtifacts(config, state, symbols, ownedSymbols, universeRows);

  const policyResult = await maybeWritePolicy({
    config,
    state: finalState,
    ownedSymbols,
  });
  const summaryPath = writeSummary(config, finalState, symbols, ownedSymbols, policyResult);

  console.log(JSON.stringify({
    summary: summaryPath,
    metrics: config.metricsPath,
    policy: config.policy,
    universe_symbols: symbols.length,
    successful_symbols: finalState.results.length,
    failed_symbols: finalState.failures.length,
    success_rate: Number(policyResult.successRate.toFixed(6)),
    policy_written: policyResult.written,
    policy_rows_before: policyResult.beforeTotal,
    policy_rows_after: policyResult.afterTotal,
    newly_filtered: policyResult.newlyFiltered.length,
    restored_to_eligible: policyResult.restoredToEligible.length,
    no_reopen: policyResult.noReopenCount,
    no_new_open: policyResult.noNewOpenCount,
    dry_run: config.dryRun,
  }));

  if (policyResult.aborted) {
    throw new Error(policyResult.abortReason);
  }
}

function buildConfig(options) {
  const asOfDate = options["as-of"] || pacificDate();
  const months = lastCalendarMonths(asOfDate, numberOption(options, "months", DEFAULTS.months));
  const outputDir = options["output-dir"] || DEFAULTS.outputDir;
  const basename = `weekly-symbol-policy-refresh-${asOfDate}`;
  return {
    account: options.account || process.env.RH_ACCOUNT_NUMBER || DEFAULTS.account,
    universe: options.universe || DEFAULTS.universe,
    policy: options.policy || DEFAULTS.policy,
    outputDir,
    batchSize: numberOption(options, "batch-size", DEFAULTS.batchSize),
    sleepMs: numberOption(options, "sleep-ms", DEFAULTS.sleepMs),
    symbolPauseMs: numberOption(options, "symbol-pause-ms", DEFAULTS.symbolPauseMs),
    minSuccessRate: numberOption(options, "min-success-rate", DEFAULTS.minSuccessRate),
    limit: options.limit === undefined ? undefined : numberOption(options, "limit", undefined),
    asOfDate,
    months,
    run: optionBool(options, "run"),
    once: optionBool(options, "once"),
    noSleep: optionBool(options, "no-sleep"),
    reset: optionBool(options, "reset"),
    dryRun: optionBool(options, "dry-run"),
    allowWeekday: optionBool(options, "allow-weekday"),
    ownedSymbolsFile: options["owned-symbols-file"],
    statePath: path.join(outputDir, `${basename}.state.json`),
    metricsPath: path.join(outputDir, `${basename}.metrics.csv`),
    diffPath: path.join(outputDir, `${basename}.policy-diff.csv`),
    summaryPath: path.join(outputDir, `${basename}.summary.md`),
    backupDir: path.join("data", "runtime", "symbol-policy-backups"),
  };
}

function printUsage() {
  console.log(`Usage:
  node scripts/weekly_symbol_policy_refresh.mjs --run [--account 878067701]
  node scripts/weekly_symbol_policy_refresh.mjs --once --dry-run --limit 5 --allow-weekday
  node scripts/weekly_symbol_policy_refresh.mjs --self-test

Refreshes generated rows in data/symbol-policy.csv from six-month monthly
intraday high/low ranges. Yahoo Finance is the primary historical source;
Robinhood historical bars are used as a per-symbol fallback when Yahoo fails.
Read-only broker access is used for owned symbol classification and fallback
historical bars only.`);
}

function parseArgs(argv) {
  const options = {};
  const positional = [];
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (!item.startsWith("--")) {
      positional.push(item);
      continue;
    }
    const body = item.slice(2);
    const equals = body.indexOf("=");
    if (equals >= 0) {
      options[body.slice(0, equals)] = body.slice(equals + 1);
      continue;
    }
    const next = argv[index + 1];
    if (next && !next.startsWith("--")) {
      options[body] = next;
      index += 1;
    } else {
      options[body] = "true";
    }
  }
  return { options, positional };
}

function numberOption(options, name, fallback) {
  if (options[name] === undefined) {
    return fallback;
  }
  const raw = options[name];
  const value = name === "min-success-rate" ? Number.parseFloat(raw) : Number.parseInt(raw, 10);
  if (!Number.isFinite(value)) {
    throw new Error(`invalid --${name}: ${raw}`);
  }
  return value;
}

function optionBool(options, name) {
  return options[name] === true || options[name] === "true";
}

function ensureWeekendOrAllowed(config) {
  if (config.allowWeekday) {
    return;
  }
  const day = pacificWeekday();
  if (day !== "Sat" && day !== "Sun") {
    throw new Error(`weekly policy refresh is weekend-only; current PT day is ${day}`);
  }
}

function readUniverseRows(universePath) {
  return readCsv(universePath)
    .filter((row) => symbolOf(row))
    .sort((left, right) => symbolOf(left).localeCompare(symbolOf(right)));
}

async function readOwnedSymbols(config) {
  if (config.ownedSymbolsFile) {
    const rows = readCsv(config.ownedSymbolsFile);
    return new Set(rows.map(symbolOf).filter(Boolean));
  }

  const client = new RobinhoodFastClient({ clientName: "codex-weekly-symbol-policy-refresh" });
  const { rows, payloads } = await client.pages(
    "get_equity_positions",
    { account_number: config.account },
    ["positions", "results"],
  );
  const sourceRows = rows.length ? rows : payloads.flatMap(positionRows);
  return new Set(
    sourceRows
      .filter((row) => symbolOf(row) && decimal(row.quantity) > 0 && row.type !== "empty")
      .map(symbolOf),
  );
}

function positionRows(payload) {
  const data = payload?.data || payload || {};
  return data.positions || data.results || [];
}

function loadOrCreateState(config, symbols) {
  if (config.reset && fs.existsSync(config.statePath)) {
    fs.unlinkSync(config.statePath);
  }
  if (fs.existsSync(config.statePath)) {
    const state = JSON.parse(fs.readFileSync(config.statePath, "utf8"));
    state.results = state.results || [];
    state.failures = state.failures || [];
    state.universe_symbols = symbols.length;
    return state;
  }
  return {
    as_of_date: config.asOfDate,
    months: config.months,
    formula: "((monthly_intraday_high - monthly_intraday_low) / monthly_intraday_low) * 100",
    universe_symbols: symbols.length,
    started_at: new Date().toISOString(),
    updated_at: null,
    complete: false,
    results: [],
    failures: [],
  };
}

async function refreshMetrics({ config, state, symbols }) {
  const targetSymbols = config.limit === undefined ? symbols : symbols.slice(0, config.limit);
  while (true) {
    const remaining = nextSymbols(state, targetSymbols, config.batchSize);
    if (remaining.length === 0) {
      state.complete = true;
      state.updated_at = new Date().toISOString();
      writeStateJson(config, state);
      return;
    }

    for (const symbol of remaining) {
      try {
        const result = await fetchMonthlyRange(symbol, config);
        state.results.push(result);
      } catch (error) {
        state.failures.push({
          symbol,
          error: error.message,
          attempted_at: new Date().toISOString(),
        });
      }
      state.updated_at = new Date().toISOString();
      writeStateJson(config, state);
      if (config.symbolPauseMs > 0) {
        await sleep(config.symbolPauseMs);
      }
    }

    if (config.once || !config.run) {
      writeStateJson(config, state);
      return;
    }

    if (!config.noSleep && nextSymbols(state, targetSymbols, 1).length > 0) {
      await sleep(config.sleepMs);
    }
  }
}

function nextSymbols(state, symbols, count) {
  const done = new Set([
    ...state.results.map((row) => row.symbol),
    ...state.failures.map((row) => row.symbol),
  ]);
  return symbols.filter((symbol) => !done.has(symbol)).slice(0, count);
}

async function fetchMonthlyRange(symbol, config) {
  const yahooFetcher = config.yahooFetcher || fetchYahooMonthlyRange;
  const robinhoodFetcher = config.robinhoodFetcher || fetchRobinhoodMonthlyRange;
  try {
    return await yahooFetcher(symbol, config);
  } catch (yahooError) {
    try {
      const result = await robinhoodFetcher(symbol, config);
      return {
        ...result,
        source: "robinhood_historical_fallback",
        primary_error: errorMessage(yahooError),
      };
    } catch (robinhoodError) {
      throw new Error(
        `Yahoo failed: ${errorMessage(yahooError)}; Robinhood fallback failed: ${errorMessage(robinhoodError)}`,
      );
    }
  }
}

async function fetchYahooMonthlyRange(symbol, config) {
  const yahooSymbol = toYahooSymbol(symbol);
  const startDate = `${config.months[0]}-01`;
  const period1 = Math.floor(Date.parse(`${startDate}T00:00:00Z`) / 1000);
  const period2 = Math.floor(Date.parse(`${addUtcDays(config.asOfDate, 1)}T00:00:00Z`) / 1000);
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(yahooSymbol)}?period1=${period1}&period2=${period2}&interval=1d&events=history&includeAdjustedClose=true`;
  const json = await fetchJsonWithRetry(url, 3);
  if (json.chart?.error) {
    throw new Error(`Yahoo error: ${JSON.stringify(json.chart.error)}`);
  }

  const result = json.chart?.result?.[0];
  const quote = result?.indicators?.quote?.[0];
  const timestamps = result?.timestamp;
  if (!result || !quote || !timestamps) {
    throw new Error("Yahoo returned no daily quote rows");
  }

  const dailyRows = [];
  for (let index = 0; index < timestamps.length; index += 1) {
    dailyRows.push({
      date: new Date(Number(timestamps[index]) * 1000).toISOString().slice(0, 10),
      high: quote.high?.[index],
      low: quote.low?.[index],
    });
  }

  return monthlyRangeFromDailyRows({
    symbol,
    name: result.meta?.longName || result.meta?.shortName || "",
    dailyRows,
    config,
    source: "yahoo_chart_api",
    extra: { yahoo_symbol: yahooSymbol },
  });
}

async function fetchRobinhoodMonthlyRange(symbol, config) {
  const client = await historicalClient(config);
  const payload = await client.tool(
    "get_equity_historicals",
    {
      symbols: [symbol],
      start_time: `${config.months[0]}-01T00:00:00Z`,
      end_time: `${addUtcDays(config.asOfDate, 1)}T00:00:00Z`,
      interval: "day",
      bounds: "regular",
      adjustment_type: "split",
    },
    { retries: 1 },
  );
  const result = robinhoodHistoricalResult(payload, symbol);
  if (!result) {
    throw new Error("Robinhood returned no historical result");
  }
  const bars = Array.isArray(result.bars) ? result.bars : [];
  const dailyRows = bars
    .filter((bar) => !bar.interpolated)
    .map((bar) => ({
      date: text(bar.begins_at || bar.date || bar.timestamp).slice(0, 10),
      high: bar.high_price ?? bar.high,
      low: bar.low_price ?? bar.low,
    }));
  if (dailyRows.length === 0) {
    throw new Error("Robinhood returned no non-interpolated daily bars");
  }

  return monthlyRangeFromDailyRows({
    symbol,
    name: result.name || "",
    dailyRows,
    config,
    source: "robinhood_historical_fallback",
    extra: { robinhood_symbol: text(result.symbol) || symbol },
  });
}

async function historicalClient(config) {
  if (!config.robinhoodHistoricalClient) {
    config.robinhoodHistoricalClient = new RobinhoodFastClient({
      clientName: "codex-weekly-symbol-policy-historical",
    });
  }
  return config.robinhoodHistoricalClient;
}

function robinhoodHistoricalResult(payload, symbol) {
  const data = payload?.data || payload || {};
  const results = Array.isArray(data.results) ? data.results : [];
  return results.find((row) => symbolOf(row) === symbol) || results[0];
}

function monthlyRangeFromDailyRows({ symbol, name, dailyRows, config, source, extra = {} }) {
  const buckets = new Map(config.months.map((month) => [month, { high: -Infinity, low: Infinity, days: 0 }]));
  for (const row of dailyRows) {
    const high = finiteNumber(row.high);
    const low = finiteNumber(row.low);
    if (high == null || low == null || low <= 0) {
      continue;
    }
    const month = monthFromDate(row.date);
    const bucket = buckets.get(month);
    if (!bucket) {
      continue;
    }
    bucket.high = Math.max(bucket.high, high);
    bucket.low = Math.min(bucket.low, low);
    bucket.days += 1;
  }

  const monthly = {};
  for (const month of config.months) {
    const bucket = buckets.get(month);
    if (!bucket || bucket.days === 0 || !Number.isFinite(bucket.high) || !Number.isFinite(bucket.low)) {
      monthly[month] = { low: null, high: null, range_pct: null, trading_days: 0 };
      continue;
    }
    monthly[month] = {
      low: bucket.low,
      high: bucket.high,
      range_pct: ((bucket.high - bucket.low) / bucket.low) * 100,
      trading_days: bucket.days,
    };
  }

  const valid = config.months.filter((month) => monthly[month].range_pct != null);
  if (valid.length === 0) {
    throw new Error("No valid monthly high/low data");
  }
  const avg = valid.reduce((sum, month) => sum + monthly[month].range_pct, 0) / valid.length;
  return {
    ...extra,
    symbol,
    name,
    valid_months: valid.length,
    avg_monthly_range_pct: avg,
    monthly,
    source,
  };
}

async function fetchJsonWithRetry(url, attempts) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: { "User-Agent": "Mozilla/5.0" },
      });
      const text = await response.text();
      if (response.status >= 400) {
        throw new Error(`HTTP ${response.status}: ${text.slice(0, 200)}`);
      }
      return JSON.parse(text);
    } catch (error) {
      lastError = error;
      if (attempt < attempts) {
        await sleep(attempt * 5000);
      }
    }
  }
  throw lastError;
}

function writeStateArtifacts(config, state, symbols, ownedSymbols, universeRows) {
  const normalized = normalizeState(state);
  writeStateJson(config, normalized);
  writeMetricsCsv(config, normalized, universeRows, ownedSymbols);
  return normalized;
}

function writeStateJson(config, state) {
  fs.mkdirSync(config.outputDir, { recursive: true });
  fs.writeFileSync(config.statePath, `${JSON.stringify(normalizeState(state), null, 2)}\n`);
}

function normalizeState(state) {
  const resultsBySymbol = new Map();
  for (const row of state.results || []) {
    resultsBySymbol.set(row.symbol, row);
  }
  const failuresBySymbol = new Map();
  for (const row of state.failures || []) {
    failuresBySymbol.set(row.symbol, row);
  }
  return {
    ...state,
    results: [...resultsBySymbol.values()].sort((left, right) => left.symbol.localeCompare(right.symbol)),
    failures: [...failuresBySymbol.values()].sort((left, right) => left.symbol.localeCompare(right.symbol)),
  };
}

function writeMetricsCsv(config, state, universeRows, ownedSymbols) {
  const universeBySymbol = new Map(universeRows.map((row) => [symbolOf(row), row]));
  const columns = [
    "symbol",
    "name",
    "owned",
    "universe_active",
    "universe_tradable",
    ...config.months.flatMap((month) => [`${month}_low`, `${month}_high`, `${month}_range_pct`]),
    "avg_monthly_range_pct",
    "valid_months",
    "source",
    "primary_error",
  ];
  const lines = [columns.map(csvValue).join(",")];
  for (const row of [...state.results].sort(compareMetricsRows)) {
    const universeRow = universeBySymbol.get(row.symbol) || {};
    lines.push([
      row.symbol,
      row.name,
      ownedSymbols.has(row.symbol) ? "true" : "false",
      text(universeRow.active),
      text(universeRow.tradable),
      ...config.months.flatMap((month) => [
        numberText(row.monthly?.[month]?.low),
        numberText(row.monthly?.[month]?.high),
        numberText(row.monthly?.[month]?.range_pct),
      ]),
      numberText(row.avg_monthly_range_pct),
      String(row.valid_months),
      row.source,
      text(row.primary_error),
    ].map(csvValue).join(","));
  }
  fs.writeFileSync(config.metricsPath, `${lines.join("\n")}\n`);
}

function compareMetricsRows(left, right) {
  if (left.valid_months !== right.valid_months) {
    return right.valid_months - left.valid_months;
  }
  if (left.avg_monthly_range_pct !== right.avg_monthly_range_pct) {
    return left.avg_monthly_range_pct - right.avg_monthly_range_pct;
  }
  return left.symbol.localeCompare(right.symbol);
}

async function maybeWritePolicy({ config, state, ownedSymbols }) {
  const policyRowsBefore = fs.existsSync(config.policy) ? readCsv(config.policy) : [];
  validatePolicyRows(policyRowsBefore);

  const autoBefore = policyRowsBefore.filter(isAutoManagedPolicy);
  const manualRows = policyRowsBefore.filter((row) => !isAutoManagedPolicy(row));
  const manualSymbols = new Set(manualRows.map(symbolOf));
  const generatedRows = buildGeneratedPolicyRows({ config, state, ownedSymbols })
    .filter((row) => !manualSymbols.has(symbolOf(row)));
  const policyRowsAfter = mergePolicyRows(manualRows, generatedRows);
  validatePolicyRows(policyRowsAfter);

  const diffRows = diffPolicyRows(autoBefore, generatedRows);
  writePolicyDiff(config, diffRows);

  const successRate = state.universe_symbols === 0 ? 0 : state.results.length / state.universe_symbols;
  const result = {
    successRate,
    aborted: false,
    abortReason: "",
    written: false,
    beforeTotal: policyRowsBefore.length,
    afterTotal: policyRowsAfter.length,
    newlyFiltered: diffRows.filter((row) => row.change === "added").map((row) => row.symbol),
    restoredToEligible: diffRows.filter((row) => row.change === "removed").map((row) => row.symbol),
    changed: diffRows.filter((row) => row.change === "changed").map((row) => row.symbol),
    noReopenCount: generatedRows.filter((row) => row.policy === "no_reopen").length,
    noNewOpenCount: generatedRows.filter((row) => row.policy === "no_new_open").length,
    manualCount: manualRows.length,
    generatedCount: generatedRows.length,
  };

  if (successRate < config.minSuccessRate) {
    result.aborted = true;
    result.abortReason = `success rate ${(successRate * 100).toFixed(2)}% is below ${(config.minSuccessRate * 100).toFixed(2)}%; policy not replaced`;
    return result;
  }
  if (config.dryRun) {
    return result;
  }

  writePolicyAtomically(config, policyRowsAfter);
  validatePolicyRows(readCsv(config.policy));
  result.written = true;
  return result;
}

function buildGeneratedPolicyRows({ config, state, ownedSymbols }) {
  const evidence = `weekly_intraday_range_${config.months[0]}_to_${config.months[config.months.length - 1]}`;
  return state.results
    .filter((row) => row.valid_months === 6 && Number(row.avg_monthly_range_pct) < 10)
    .map((row) => {
      const owned = ownedSymbols.has(row.symbol);
      return {
        symbol: row.symbol,
        policy: owned ? "no_reopen" : "no_new_open",
        allow_open: "false",
        allow_reopen: "false",
        allow_double_down: "true",
        allow_sell: "true",
        reason: `valid_months=6 avg_monthly_range_pct=${Number(row.avg_monthly_range_pct).toFixed(4)} below 10`,
        evidence_source: evidence,
        review_after: "",
        updated_at: config.asOfDate,
      };
    })
    .sort((left, right) => left.symbol.localeCompare(right.symbol));
}

function mergePolicyRows(manualRows, generatedRows) {
  const bySymbol = new Map();
  for (const row of [...manualRows, ...generatedRows]) {
    bySymbol.set(symbolOf(row), normalizePolicyRow(row));
  }
  return [...bySymbol.values()].sort((left, right) => symbolOf(left).localeCompare(symbolOf(right)));
}

function diffPolicyRows(beforeRows, afterRows) {
  const before = new Map(beforeRows.map((row) => [symbolOf(row), normalizePolicyRow(row)]));
  const after = new Map(afterRows.map((row) => [symbolOf(row), normalizePolicyRow(row)]));
  const symbols = uniqueSorted([...before.keys(), ...after.keys()]);
  const rows = [];
  for (const symbol of symbols) {
    if (!before.has(symbol)) {
      rows.push({ change: "added", symbol, before_policy: "", after_policy: after.get(symbol).policy });
    } else if (!after.has(symbol)) {
      rows.push({ change: "removed", symbol, before_policy: before.get(symbol).policy, after_policy: "" });
    } else if (JSON.stringify(before.get(symbol)) !== JSON.stringify(after.get(symbol))) {
      rows.push({
        change: "changed",
        symbol,
        before_policy: before.get(symbol).policy,
        after_policy: after.get(symbol).policy,
      });
    }
  }
  return rows;
}

function writePolicyDiff(config, diffRows) {
  const fields = ["change", "symbol", "before_policy", "after_policy"];
  const lines = [fields.map(csvValue).join(",")];
  for (const row of diffRows) {
    lines.push(fields.map((field) => csvValue(row[field])).join(","));
  }
  fs.writeFileSync(config.diffPath, `${lines.join("\n")}\n`);
}

function writePolicyAtomically(config, rows) {
  fs.mkdirSync(path.dirname(config.policy), { recursive: true });
  fs.mkdirSync(config.backupDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const backupPath = path.join(config.backupDir, `symbol-policy-${stamp}.csv`);
  if (fs.existsSync(config.policy)) {
    fs.copyFileSync(config.policy, backupPath);
  }

  const tempPath = `${config.policy}.tmp`;
  fs.writeFileSync(tempPath, renderPolicyCsv(rows));
  validatePolicyRows(readCsv(tempPath));
  fs.renameSync(tempPath, config.policy);
}

function renderPolicyCsv(rows) {
  return `${POLICY_FIELDS.join(",")}\n${rows.map((row) => POLICY_FIELDS.map((field) => csvValue(row[field])).join(",")).join("\n")}\n`;
}

function validatePolicyRows(rows) {
  for (const row of rows) {
    const missing = POLICY_FIELDS.filter((field) => !(field in row));
    if (missing.length > 0) {
      throw new Error(`policy row ${symbolOf(row) || "(blank)"} missing fields: ${missing.join(", ")}`);
    }
    if (!symbolOf(row)) {
      throw new Error("policy row has blank symbol");
    }
  }
}

function isAutoManagedPolicy(row) {
  return (
    GENERATED_EVIDENCE_PATTERNS.some((pattern) => pattern.test(text(row.evidence_source))) &&
    ["no_new_open", "no_reopen"].includes(text(row.policy)) &&
    boolText(row.allow_open) === false &&
    boolText(row.allow_reopen) === false &&
    boolText(row.allow_double_down) === true &&
    boolText(row.allow_sell) === true
  );
}

function normalizePolicyRow(row) {
  return Object.fromEntries(POLICY_FIELDS.map((field) => [field, text(row[field])]));
}

function writeSummary(config, state, symbols, ownedSymbols, policyResult) {
  const lines = [
    "# Weekly Symbol Policy Refresh",
    "",
    `As of: ${config.asOfDate}`,
    `Months: ${config.months[0]} to ${config.months[config.months.length - 1]}`,
    `Universe symbols: ${symbols.length}`,
    `Successful symbols: ${state.results.length}`,
    `Failed/skipped symbols: ${state.failures.length}`,
    `Robinhood fallback symbols: ${robinhoodFallbackCount(state)}`,
    `Success rate: ${(policyResult.successRate * 100).toFixed(2)}%`,
    `Policy written: ${policyResult.written ? "yes" : "no"}`,
    `Dry run: ${config.dryRun ? "yes" : "no"}`,
    "",
    "## Policy Summary",
    "",
    `- Policy rows before: ${policyResult.beforeTotal}`,
    `- Policy rows after: ${policyResult.afterTotal}`,
    `- Manual rows preserved: ${policyResult.manualCount}`,
    `- Generated rows after refresh: ${policyResult.generatedCount}`,
    `- Newly filtered: ${policyResult.newlyFiltered.length}`,
    `- Restored to eligible: ${policyResult.restoredToEligible.length}`,
    `- Changed generated rows: ${policyResult.changed.length}`,
    `- Owned no_reopen: ${policyResult.noReopenCount}`,
    `- Unowned no_new_open: ${policyResult.noNewOpenCount}`,
    "",
    "## Files",
    "",
    `- Metrics CSV: \`${config.metricsPath}\``,
    `- Policy diff CSV: \`${config.diffPath}\``,
    `- State JSON: \`${config.statePath}\``,
  ];
  if (policyResult.aborted) {
    lines.push("", "## Abort", "", policyResult.abortReason);
  }
  if (state.failures.length > 0) {
    lines.push("", "## Failed Or Skipped Symbols", "", "| Symbol | Error |", "|---|---|");
    for (const failure of state.failures.slice(0, 100)) {
      lines.push(`| ${failure.symbol} | ${escapeMarkdown(failure.error)} |`);
    }
    if (state.failures.length > 100) {
      lines.push(`| ... | ${state.failures.length - 100} more failures omitted |`);
    }
  }
  fs.writeFileSync(config.summaryPath, `${lines.join("\n")}\n`);
  return config.summaryPath;
}

async function runSelfTest() {
  const config = {
    asOfDate: "2026-06-13",
    months: ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"],
  };
  const state = {
    results: [
      { symbol: "FLAT", valid_months: 6, avg_monthly_range_pct: 5.5 },
      { symbol: "HOT", valid_months: 6, avg_monthly_range_pct: 5.0 },
      { symbol: "OLD", valid_months: 6, avg_monthly_range_pct: 12.0 },
    ],
  };
  const ownedSymbols = new Set(["FLAT"]);
  const manualRows = [
    {
      symbol: "HOT",
      policy: "exit_only",
      allow_open: "false",
      allow_reopen: "false",
      allow_double_down: "false",
      allow_sell: "true",
      reason: "manual",
      evidence_source: "manual",
      review_after: "",
      updated_at: "2026-06-12",
    },
  ];
  const oldAutoRows = [
    {
      symbol: "OLD",
      policy: "no_new_open",
      allow_open: "false",
      allow_reopen: "false",
      allow_double_down: "true",
      allow_sell: "true",
      reason: "old auto",
      evidence_source: "weekly_intraday_range_2025-12_to_2026-05",
      review_after: "",
      updated_at: "2026-06-06",
    },
  ];
  const generated = buildGeneratedPolicyRows({ config, state, ownedSymbols })
    .filter((row) => !new Set(manualRows.map(symbolOf)).has(symbolOf(row)));
  const merged = mergePolicyRows(manualRows, generated);
  const diff = diffPolicyRows(oldAutoRows, generated);

  assert(generated.length === 1, "manual HOT should suppress generated HOT and OLD should be restored");
  assert(generated[0].symbol === "FLAT", "FLAT should be the only generated row");
  assert(generated[0].policy === "no_reopen", "owned FLAT should be no_reopen");
  assert(merged.length === 2, "manual HOT plus generated FLAT should remain");
  assert(merged.some((row) => row.symbol === "HOT" && row.policy === "exit_only"), "manual HOT preserved");
  assert(diff.some((row) => row.symbol === "OLD" && row.change === "removed"), "OLD should be restored");
  validatePolicyRows(merged);

  const fallback = await fetchMonthlyRange("FALL", {
    ...config,
    yahooFetcher: async () => {
      throw new Error("forced Yahoo failure");
    },
    robinhoodFetcher: async (symbol) => ({
      symbol,
      name: "",
      valid_months: 6,
      avg_monthly_range_pct: 11.5,
      monthly: {},
      source: "robinhood_historical_fallback",
    }),
  });
  assert(fallback.source === "robinhood_historical_fallback", "fallback source should be Robinhood");
  assert(fallback.primary_error === "forced Yahoo failure", "fallback should retain the Yahoo failure");

  let doubleFailure = false;
  try {
    await fetchMonthlyRange("FAIL", {
      ...config,
      yahooFetcher: async () => {
        throw new Error("Yahoo down");
      },
      robinhoodFetcher: async () => {
        throw new Error("Robinhood down");
      },
    });
  } catch (error) {
    doubleFailure = true;
    assert(
      error.message.includes("Yahoo failed: Yahoo down; Robinhood fallback failed: Robinhood down"),
      "combined failure should report both sources",
    );
  }
  assert(doubleFailure, "double failure should throw");
  console.log("self-test ok");
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function symbolOf(row) {
  return text(row?.symbol).toUpperCase();
}

function text(value) {
  return String(value ?? "").trim();
}

function decimal(value) {
  const parsed = Number.parseFloat(text(value));
  return Number.isFinite(parsed) ? parsed : 0;
}

function finiteNumber(value) {
  const parsed = Number.parseFloat(text(value));
  return Number.isFinite(parsed) ? parsed : null;
}

function boolText(value) {
  return ["1", "true", "yes", "y"].includes(text(value).toLowerCase());
}

function uniqueSorted(values) {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right));
}

function toYahooSymbol(symbol) {
  return symbol.replace(/\./g, "-").trim().toUpperCase();
}

function numberText(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "";
  }
  return Number(value).toFixed(4);
}

function monthFromDate(value) {
  const raw = text(value);
  if (/^\d{4}-\d{2}/.test(raw)) {
    return raw.slice(0, 7);
  }
  const parsed = Date.parse(raw);
  return Number.isNaN(parsed) ? "" : new Date(parsed).toISOString().slice(0, 7);
}

function pacificDate() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function pacificWeekday() {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles",
    weekday: "short",
  }).format(new Date());
}

function lastCalendarMonths(asOfDate, count) {
  const [year, month] = asOfDate.split("-").map(Number);
  const months = [];
  for (let offset = count - 1; offset >= 0; offset -= 1) {
    const date = new Date(Date.UTC(year, month - 1 - offset, 1));
    months.push(date.toISOString().slice(0, 7));
  }
  return months;
}

function addUtcDays(dateText, days) {
  return new Date(Date.parse(`${dateText}T00:00:00Z`) + days * 24 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 10);
}

function robinhoodFallbackCount(state) {
  return (state.results || []).filter((row) => row.source === "robinhood_historical_fallback").length;
}

function errorMessage(error) {
  return error?.message || String(error);
}

function escapeMarkdown(value) {
  return text(value).replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

main().catch((error) => {
  console.error(`ERR ${error.stack || error.message}`);
  process.exit(1);
});
