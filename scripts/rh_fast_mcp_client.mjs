import fs from "node:fs";
import path from "node:path";

export const DEFAULT_MCP_SERVER_URL = "https://agent.robinhood.com/mcp/trading";
const DEFAULT_CREDENTIAL_SERVER_NAMES = ["robinhood", "robinhood_agentic"];

export function credentialPath() {
  return (
    process.env.CODEX_CREDENTIALS_PATH ||
    path.join(process.env.USERPROFILE || process.env.HOME || "", ".codex/.credentials.json")
  );
}

export function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
}

export function ensureParent(filePath) {
  fs.mkdirSync(path.dirname(path.resolve(filePath)), { recursive: true });
}

export function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

export function writeJson(filePath, value) {
  ensureParent(filePath);
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

export function readCsv(filePath) {
  const text = fs.readFileSync(filePath, "utf8");
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (quoted) {
      if (char === "\"" && next === "\"") {
        field += "\"";
        index += 1;
      } else if (char === "\"") {
        quoted = false;
      } else {
        field += char;
      }
    } else if (char === "\"") {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else if (char !== "\r") {
      field += char;
    }
  }

  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }

  const header = rows.shift();
  if (!header) {
    return [];
  }
  return rows
    .filter((item) => item.length > 0 && item.some(Boolean))
    .map((item) => Object.fromEntries(header.map((key, index) => [key, item[index] || ""])));
}

export function writeCsv(filePath, rows, header) {
  ensureParent(filePath);
  fs.writeFileSync(
    filePath,
    `${header.join(",")}\n${rows.map((row) => header.map((key) => csvValue(row[key])).join(",")).join("\n")}\n`,
  );
}

export function csvValue(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, "\"\"")}"` : text;
}

function readRobinhoodCredential() {
  const filePath = credentialPath();
  if (!fs.existsSync(filePath)) {
    throw new Error(
      `Robinhood MCP credentials not found at ${filePath}. Run: node scripts/rh_fast_oauth_login.mjs`,
    );
  }
  const credentials = readJson(filePath);
  const names = (process.env.RH_MCP_SERVER_NAME || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const acceptedNames = names.length > 0 ? names : DEFAULT_CREDENTIAL_SERVER_NAMES;
  const entry = Object.entries(credentials).find(
    ([, item]) => item && acceptedNames.includes(item.server_name),
  );
  if (!entry) {
    throw new Error(
      `Robinhood MCP credential not found in ${filePath}; expected server_name one of: ${acceptedNames.join(", ")}`,
    );
  }
  const [key, credential] = entry;
  return { credentials, credential: { server_url: DEFAULT_MCP_SERVER_URL, ...credential }, filePath, key };
}

function tokenExpiresSoon(credential) {
  if (!credential.expires_at) {
    return false;
  }
  const expiresAt = Date.parse(credential.expires_at);
  if (!Number.isFinite(expiresAt)) {
    return false;
  }
  return expiresAt <= Date.now() + 60_000;
}

async function refreshCredential(source, { force = false } = {}) {
  if (!source?.credential?.refresh_token || !source?.credential?.client_id) {
    return false;
  }
  if (!force && !tokenExpiresSoon(source.credential)) {
    return false;
  }

  const tokenEndpoint = source.credential.token_endpoint || "https://api.robinhood.com/oauth2/token/";
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    refresh_token: source.credential.refresh_token,
    client_id: source.credential.client_id,
    resource: source.credential.server_url || DEFAULT_MCP_SERVER_URL,
  });
  const response = await fetch(tokenEndpoint, {
    method: "POST",
    headers: {
      accept: "application/json",
      "content-type": "application/x-www-form-urlencoded",
    },
    body,
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`Robinhood MCP token refresh failed: HTTP ${response.status} ${text.slice(0, 200)}`);
  }
  const payload = JSON.parse(text);
  const expiresIn = Number.parseInt(payload.expires_in, 10);
  const updated = {
    ...source.credential,
    access_token: payload.access_token || source.credential.access_token,
    refresh_token: payload.refresh_token || source.credential.refresh_token,
    token_type: payload.token_type || source.credential.token_type || "Bearer",
    scope: payload.scope || source.credential.scope || "internal",
    expires_at: Number.isFinite(expiresIn)
      ? new Date(Date.now() + expiresIn * 1000).toISOString()
      : source.credential.expires_at,
    updated_at: new Date().toISOString(),
  };
  source.credentials[source.key] = updated;
  writeJson(source.filePath, source.credentials);
  source.credential = updated;
  return true;
}

function parseMcpResponse(text, contentType) {
  if ((contentType || "").includes("text/event-stream")) {
    return text
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim())
      .filter(Boolean)
      .map((line) => JSON.parse(line));
  }
  return [JSON.parse(text)];
}

function cursorFromNext(next) {
  if (!next) {
    return undefined;
  }
  try {
    return new URL(next).searchParams.get("cursor") || undefined;
  } catch {
    const match = String(next).match(/[?&]cursor=([^&]+)/);
    return match ? decodeURIComponent(match[1]) : undefined;
  }
}

function payloadData(payload) {
  return payload?.data && typeof payload.data === "object" ? payload.data : payload;
}

export function extractRows(payload, keys) {
  const data = payloadData(payload);
  for (const key of keys) {
    if (Array.isArray(data?.[key])) {
      return data[key];
    }
  }
  if (Array.isArray(data?.results)) {
    return data.results;
  }
  return [];
}

export function nextCursor(payload) {
  return cursorFromNext(payloadData(payload)?.next);
}

export class RobinhoodFastClient {
  constructor({ credential, clientName = "codex-rh-fast" } = {}) {
    this.credentialSource = credential
      ? { credential: { server_url: DEFAULT_MCP_SERVER_URL, ...credential } }
      : readRobinhoodCredential();
    this.credential = this.credentialSource.credential;
    this.clientName = clientName;
    this.session = undefined;
    this.nextId = 1;
  }

  async initialize() {
    if (this.session) {
      return;
    }
    await this.#refreshCredentialIfNeeded();
    const response = await this.#mcpCall({
      jsonrpc: "2.0",
      id: this.nextId,
      method: "initialize",
      params: {
        protocolVersion: "2024-11-05",
        capabilities: {},
        clientInfo: { name: this.clientName, version: "1.0.0" },
      },
    });
    this.nextId += 1;
    if (response.status !== 200 || !response.session) {
      throw new Error("Robinhood MCP initialize failed");
    }
    this.session = response.session;
    try {
      await this.#mcpCall({
        jsonrpc: "2.0",
        method: "notifications/initialized",
        params: {},
      });
    } catch {
      // Some MCP transports do not require a response for initialized notifications.
    }
  }

  async tool(name, args, { retries = 1 } = {}) {
    await this.initialize();
    let lastError;
    for (let attempt = 0; attempt <= retries; attempt += 1) {
      try {
        const response = await this.#mcpCall({
          jsonrpc: "2.0",
          id: this.nextId,
          method: "tools/call",
          params: { name, arguments: args },
        });
        this.nextId += 1;
        if (response.status !== 200) {
          throw new Error(`HTTP ${response.status}`);
        }
        const item = response.payloads[0];
        if (item.error) {
          throw new Error(item.error.message || JSON.stringify(item.error));
        }
        const content = item.result?.content?.[0]?.text;
        return content ? JSON.parse(content) : item.result;
      } catch (error) {
        lastError = error;
        if (attempt < retries) {
          await new Promise((resolve) => setTimeout(resolve, 1000));
        }
      }
    }
    throw lastError;
  }

  async pages(name, args, keys, { maxPages = 100 } = {}) {
    const rows = [];
    const payloads = [];
    let cursor = args.cursor;
    for (let page = 0; page < maxPages; page += 1) {
      const payload = await this.tool(name, { ...args, ...(cursor ? { cursor } : {}) });
      payloads.push(payload);
      rows.push(...extractRows(payload, keys));
      cursor = nextCursor(payload);
      if (!cursor) {
        break;
      }
    }
    return { rows, payloads };
  }

  async #mcpCall(body, { retryAuth = true } = {}) {
    const headers = {
      authorization: `Bearer ${this.credential.access_token}`,
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
    };
    if (this.session) {
      headers["mcp-session-id"] = this.session;
    }
    const response = await fetch(this.credential.server_url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    const text = await response.text();
    if (response.status === 401 && retryAuth && this.credentialSource?.credential?.refresh_token) {
      await this.#refreshCredentialIfNeeded({ force: true });
      return this.#mcpCall(body, { retryAuth: false });
    }
    let payloads;
    try {
      payloads = parseMcpResponse(text, response.headers.get("content-type"));
    } catch (error) {
      if (response.status >= 400) {
        payloads = [{ error: { message: text || error.message } }];
      } else {
        throw error;
      }
    }
    return {
      status: response.status,
      session: response.headers.get("mcp-session-id") || this.session,
      payloads,
    };
  }

  async #refreshCredentialIfNeeded(options = {}) {
    const refreshed = await refreshCredential(this.credentialSource, options);
    if (refreshed) {
      this.credential = this.credentialSource.credential;
      this.session = undefined;
    }
  }
}
