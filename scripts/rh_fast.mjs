import fs from "node:fs";

import {
  RobinhoodFastClient,
  readCsv,
  requireEnv,
  writeCsv,
  writeJson,
} from "./rh_fast_mcp_client.mjs";

const ACTIVE_ORDER_STATES = ["new", "queued", "unconfirmed", "confirmed", "partially_filled"];
const MARKET_OPEN_MINUTE_PT = 6 * 60 + 30;
const MARKET_CLOSE_MINUTE_PT = 13 * 60;

function usage() {
  console.log(`Usage:
  node scripts/rh_fast.mjs quotes SYMBOL... [--file path] [--output path]
  node scripts/rh_fast.mjs orders --account <account> [--state queued] [--all] [--since ISO] [--output path]
  node scripts/rh_fast.mjs positions --account <account> [--with-quotes] [--output path] [--summary-output path]
  node scripts/rh_fast.mjs open-plan --account <account> [--limit 100] [--universe data/universe.csv] [--symbol-policy data/symbol-policy.csv] [--output path]
  node scripts/rh_fast.mjs watch --account <account> [--mode both|sell|dd] [--output path]

All commands are read-only. Set RH_ACCOUNT_NUMBER instead of --account if preferred.`);
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

function accountNumber(options) {
  return options.account || process.env.RH_ACCOUNT_NUMBER || requireEnv("RH_ACCOUNT_NUMBER");
}

function boolOption(options, name) {
  return options[name] === true || options[name] === "true";
}

function numberOption(options, name, fallback) {
  const raw = options[name];
  if (raw === undefined) {
    return fallback;
  }
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed)) {
    throw new Error(`invalid --${name}: ${raw}`);
  }
  return parsed;
}

function text(value) {
  return String(value ?? "").trim();
}

function symbolOf(row) {
  return text(row.symbol).toUpperCase();
}

function boolField(value, fallback = true) {
  const normalized = text(value).toLowerCase();
  if (!normalized) {
    return fallback;
  }
  return ["1", "true", "yes", "y"].includes(normalized);
}

function decimal(value) {
  const parsed = Number.parseFloat(String(value ?? "").trim());
  return Number.isFinite(parsed) ? parsed : 0;
}

function isRegularMarketOpenPacific(now = new Date()) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      weekday: "short",
      hour: "numeric",
      minute: "numeric",
      hourCycle: "h23",
    })
      .formatToParts(now)
      .map((part) => [part.type, part.value]),
  );
  const weekday = parts.weekday;
  const minuteOfDay = decimal(parts.hour) * 60 + decimal(parts.minute);
  return (
    weekday !== "Sat" &&
    weekday !== "Sun" &&
    minuteOfDay >= MARKET_OPEN_MINUTE_PT &&
    minuteOfDay < MARKET_CLOSE_MINUTE_PT
  );
}

function priceFromQuote(row) {
  const quote = row.quote || row;
  return {
    symbol: symbolOf(quote),
    bid: decimal(quote.bid_price),
    ask: decimal(quote.ask_price),
    last: decimal(quote.last_trade_price || quote.last_non_reg_trade_price),
    updated_at: text(quote.venue_last_trade_time || quote.venue_last_non_reg_trade_time),
    raw: row,
  };
}

function positionRows(payload) {
  const data = payload?.data || payload || {};
  const rows = data.positions || data.results || [];
  return rows.filter((row) => symbolOf(row) && decimal(row.quantity) > 0 && row.type !== "empty");
}

function orderRows(payload) {
  const data = payload?.data || payload || {};
  return data.orders || data.results || (data.order ? [data.order] : []);
}

function activeOrderRows(rows) {
  return rows.filter((row) => ACTIVE_ORDER_STATES.includes(text(row.state).toLowerCase()));
}

function readSymbols({ positional, options }) {
  const symbols = new Set(positional.map((item) => item.toUpperCase()));
  if (options.symbols) {
    for (const symbol of String(options.symbols).split(",")) {
      if (symbol.trim()) {
        symbols.add(symbol.trim().toUpperCase());
      }
    }
  }
  if (options.file) {
    const rows = readCsv(options.file);
    for (const row of rows) {
      const symbol = symbolOf(row);
      if (symbol) {
        symbols.add(symbol);
      }
    }
  }
  return [...symbols];
}

async function quoteSymbols(client, symbols) {
  const results = [];
  for (let index = 0; index < symbols.length; index += 20) {
    const batch = symbols.slice(index, index + 20);
    if (batch.length === 0) {
      continue;
    }
    const payload = await client.tool("get_equity_quotes", { symbols: batch });
    const rows = payload?.data?.results || payload?.results || [];
    results.push(...rows.map(priceFromQuote));
  }
  return results;
}

async function fetchPositions(client, account) {
  const { rows, payloads } = await client.pages(
    "get_equity_positions",
    { account_number: account },
    ["positions", "results"],
  );
  return { rows: rows.length ? rows : payloads.flatMap(positionRows), payloads };
}

async function fetchOrders(client, account, options) {
  const base = {
    account_number: account,
    ...(options.since ? { created_at_gte: options.since } : {}),
    ...(options["placed-agent"] ? { placed_agent: options["placed-agent"] } : {}),
  };
  if (boolOption(options, "all")) {
    const { rows, payloads } = await client.pages("get_equity_orders", base, [
      "orders",
      "results",
    ]);
    return { rows: rows.length ? rows : payloads.flatMap(orderRows), payloads };
  }
  if (options.state) {
    const { rows, payloads } = await client.pages(
      "get_equity_orders",
      { ...base, state: options.state },
      ["orders", "results"],
    );
    return { rows: rows.length ? rows : payloads.flatMap(orderRows), payloads };
  }

  const allRows = [];
  const payloads = [];
  for (const state of ACTIVE_ORDER_STATES) {
    const page = await client.pages(
      "get_equity_orders",
      { ...base, state },
      ["orders", "results"],
    );
    allRows.push(...(page.rows.length ? page.rows : page.payloads.flatMap(orderRows)));
    payloads.push(...page.payloads);
  }
  return { rows: allRows, payloads };
}

function summarizePositions(positions, quotes, { marketClosed = false } = {}) {
  const quotesBySymbol = new Map(quotes.map((quote) => [quote.symbol, quote]));
  return positions
    .filter((position) => symbolOf(position) && decimal(position.quantity) > 0)
    .map((position) => {
      const symbol = symbolOf(position);
      const quantity = decimal(position.quantity);
      const averageBuyPrice = decimal(position.average_buy_price);
      const quote = quotesBySymbol.get(symbol);
      const markPrice = quote?.bid || quote?.last || 0;
      const ddMarkPrice = marketClosed ? quote?.last || markPrice : markPrice;
      const ddPriceBasis =
        marketClosed && quote?.last
          ? "last_when_market_closed"
          : marketClosed
            ? "market_hours_estimate_fallback_missing_last"
            : "market_hours_estimate";
      const cost = quantity * averageBuyPrice;
      const value = quantity * markPrice;
      const ddValue = quantity * ddMarkPrice;
      const returnPct = cost > 0 ? ((value - cost) / cost) * 100 : 0;
      const ddReturnPct = cost > 0 ? ((ddValue - cost) / cost) * 100 : 0;
      return {
        symbol,
        quantity: String(position.quantity ?? ""),
        sellable_quantity: String(position.shares_available_for_sells ?? ""),
        average_buy_price: String(position.average_buy_price ?? ""),
        bid_price: quote?.bid ? quote.bid.toFixed(6) : "",
        last_price: quote?.last ? quote.last.toFixed(6) : "",
        dd_mark_price: ddMarkPrice ? ddMarkPrice.toFixed(6) : "",
        dd_price_basis: ddPriceBasis,
        estimated_cost: cost ? cost.toFixed(6) : "",
        estimated_value: value ? value.toFixed(6) : "",
        estimated_return_pct: Number.isFinite(returnPct) ? returnPct.toFixed(4) : "",
        estimated_dd_return_pct: Number.isFinite(ddReturnPct) ? ddReturnPct.toFixed(4) : "",
      };
    })
    .sort((left, right) => symbolOf(left).localeCompare(symbolOf(right)));
}

function readSymbolPolicies(policyPath) {
  if (!policyPath || !fs.existsSync(policyPath)) {
    return new Map();
  }
  return new Map(
    readCsv(policyPath)
      .map((row) => [symbolOf(row), row])
      .filter(([symbol]) => symbol),
  );
}

function openAllowed(row, policies) {
  const policy = policies.get(symbolOf(row));
  return !policy || boolField(policy.allow_open, true);
}

function selectOpenPlan(universePath, positions, orders, limit, policyPath) {
  const blocked = new Set([
    ...positions.map(symbolOf).filter(Boolean),
    ...activeOrderRows(orders).map(symbolOf).filter(Boolean),
  ]);
  const policies = readSymbolPolicies(policyPath);
  const rows = readCsv(universePath);
  return rows
    .filter((row) => row.active === "true")
    .filter((row) => row.tradable === "true")
    .filter((row) => row.fractional_eligible === "true")
    .filter((row) => !blocked.has(symbolOf(row)))
    .filter((row) => openAllowed(row, policies))
    .slice(0, limit)
    .map((row) => ({
      symbol: symbolOf(row),
      name: row.name,
      source: row.source,
      updated_at: row.updated_at,
    }));
}

async function commandQuotes(args) {
  const { options, positional } = parseArgs(args);
  const symbols = readSymbols({ positional, options });
  if (symbols.length === 0) {
    throw new Error("quotes requires symbols, --symbols, or --file");
  }
  const client = new RobinhoodFastClient({ clientName: "codex-rh-fast-quotes" });
  const quotes = await quoteSymbols(client, symbols);
  const output = options.output || "data/runtime/rh-fast-quotes.json";
  writeJson(output, { generated_at: new Date().toISOString(), count: quotes.length, quotes });
  console.log(JSON.stringify({ output, requested: symbols.length, returned: quotes.length }));
}

async function commandPositions(args) {
  const { options } = parseArgs(args);
  const account = accountNumber(options);
  const client = new RobinhoodFastClient({ clientName: "codex-rh-fast-positions" });
  const { rows: positions, payloads } = await fetchPositions(client, account);
  let quotes = [];
  let summary = [];
  if (boolOption(options, "with-quotes")) {
    quotes = await quoteSymbols(client, positions.map(symbolOf).filter(Boolean));
    summary = summarizePositions(positions, quotes);
  }
  const output = options.output || "data/runtime/rh-fast-positions.json";
  writeJson(output, {
    generated_at: new Date().toISOString(),
    positions_count: positions.length,
    positions,
    quotes,
    payloads,
  });
  if (summary.length > 0) {
    const summaryOutput = options["summary-output"] || "data/runtime/rh-fast-positions-summary.csv";
    writeCsv(summaryOutput, summary, [
      "symbol",
      "quantity",
      "sellable_quantity",
      "average_buy_price",
      "bid_price",
      "last_price",
      "estimated_cost",
      "estimated_value",
      "estimated_return_pct",
    ]);
  }
  console.log(JSON.stringify({ output, positions: positions.length, quotes: quotes.length }));
}

async function commandOrders(args) {
  const { options } = parseArgs(args);
  const account = accountNumber(options);
  const client = new RobinhoodFastClient({ clientName: "codex-rh-fast-orders" });
  const { rows: orders, payloads } = await fetchOrders(client, account, options);
  const output = options.output || "data/runtime/rh-fast-orders.json";
  writeJson(output, {
    generated_at: new Date().toISOString(),
    states: boolOption(options, "all") ? ["all"] : options.state ? [options.state] : ACTIVE_ORDER_STATES,
    orders_count: orders.length,
    orders,
    payloads,
  });
  console.log(JSON.stringify({ output, orders: orders.length }));
}

async function commandOpenPlan(args) {
  const { options } = parseArgs(args);
  const account = accountNumber(options);
  const limit = numberOption(options, "limit", 100);
  const universe = options.universe || "data/universe.csv";
  const symbolPolicy = options["symbol-policy"] || "data/symbol-policy.csv";
  const client = new RobinhoodFastClient({ clientName: "codex-rh-fast-open-plan" });
  const { rows: positions } = await fetchPositions(client, account);
  const { rows: orders } = await fetchOrders(client, account, {});
  const plan = selectOpenPlan(universe, positions, orders, limit, symbolPolicy);
  const output = options.output || "data/runtime/rh-fast-open-plan.csv";
  writeCsv(output, plan, ["symbol", "name", "source", "updated_at"]);
  console.log(
    JSON.stringify({
      output,
      candidates: plan.length,
      owned_symbols: positions.length,
      active_orders: activeOrderRows(orders).length,
    }),
  );
}

async function commandWatch(args) {
  const { options } = parseArgs(args);
  const account = accountNumber(options);
  const mode = options.mode || "both";
  const marketClosed = !isRegularMarketOpenPacific();
  const client = new RobinhoodFastClient({ clientName: "codex-rh-fast-watch" });
  const { rows: positions } = await fetchPositions(client, account);
  const quotes = await quoteSymbols(client, positions.map(symbolOf).filter(Boolean));
  const summary = summarizePositions(positions, quotes, { marketClosed });
  const sellWatch = mode === "dd" ? [] : summary.filter((row) => decimal(row.estimated_return_pct) >= 10);
  const ddWatch =
    mode === "sell" ? [] : summary.filter((row) => decimal(row.estimated_dd_return_pct) <= -10);
  sellWatch.sort((left, right) => decimal(right.estimated_return_pct) - decimal(left.estimated_return_pct));
  ddWatch.sort(
    (left, right) => decimal(left.estimated_dd_return_pct) - decimal(right.estimated_dd_return_pct),
  );
  const output = options.output || "data/runtime/rh-fast-watch.json";
  writeJson(output, {
    generated_at: new Date().toISOString(),
    warning:
      "Read-only speed scan. Confirm sell targets and double-down ladder state with broker review before placing any order.",
    price_basis: {
      regular_market_open: !marketClosed,
      sell_watch: "bid_price, falling back to last_trade_price",
      dd_watch: marketClosed
        ? "last_trade_price because regular market is closed"
        : "unchanged market-hours estimate: bid_price, falling back to last_trade_price",
    },
    counts: {
      positions: positions.length,
      quotes: quotes.length,
      sell_watch: sellWatch.length,
      dd_watch: ddWatch.length,
    },
    sell_watch: sellWatch,
    dd_watch: ddWatch,
  });
  console.log(
    JSON.stringify({
      output,
      positions: positions.length,
      sell_watch: sellWatch.length,
      dd_watch: ddWatch.length,
    }),
  );
}

async function main() {
  const [command, ...args] = process.argv.slice(2);
  if (!command || command === "--help" || command === "help") {
    usage();
    return;
  }
  if (command === "quotes") {
    await commandQuotes(args);
  } else if (command === "positions") {
    await commandPositions(args);
  } else if (command === "orders") {
    await commandOrders(args);
  } else if (command === "open-plan") {
    await commandOpenPlan(args);
  } else if (command === "watch") {
    await commandWatch(args);
  } else {
    throw new Error(`unknown command: ${command}`);
  }
}

main().catch((error) => {
  console.error(`ERR ${error.stack || error.message}`);
  process.exit(1);
});
