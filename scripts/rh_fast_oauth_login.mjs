import crypto from "node:crypto";
import http from "node:http";
import { spawn } from "node:child_process";

import {
  DEFAULT_MCP_SERVER_URL,
  credentialPath,
  readJson,
  writeJson,
} from "./rh_fast_mcp_client.mjs";

const PROTECTED_RESOURCE_METADATA =
  "https://agent.robinhood.com/.well-known/oauth-protected-resource/mcp/trading";
const DEFAULT_SERVER_NAME = "robinhood";
const CALLBACK_PATH = "/callback";
const LOGIN_TIMEOUT_MS = 5 * 60 * 1000;

function usage() {
  console.log(`Usage:
  node scripts/rh_fast_oauth_login.mjs [--server-name robinhood] [--port 0] [--no-open]

Creates or updates the local credential file used by scripts/rh_fast.mjs:
  ${credentialPath()}

The credential file is private local state. Do not commit it.`);
}

function parseArgs(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (!item.startsWith("--")) {
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
  return options;
}

function base64Url(buffer) {
  return buffer
    .toString("base64")
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
}

function sha256Base64Url(value) {
  return base64Url(crypto.createHash("sha256").update(value).digest());
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      accept: "application/json",
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} from ${url}: ${text.slice(0, 300)}`);
  }
  return text ? JSON.parse(text) : {};
}

async function oauthMetadata() {
  const resource = await fetchJson(PROTECTED_RESOURCE_METADATA);
  const authServer = resource.authorization_servers?.[0] || DEFAULT_MCP_SERVER_URL;
  const candidates = [
    "https://agent.robinhood.com/.well-known/oauth-authorization-server/mcp/trading",
    "https://agent.robinhood.com/.well-known/oauth-authorization-server",
    `${authServer}/.well-known/oauth-authorization-server`,
  ];
  let lastError;
  for (const candidate of candidates) {
    try {
      return await fetchJson(candidate);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("Unable to discover Robinhood OAuth metadata");
}

function listenForCode({ port, state }) {
  let server;
  let resolveCode;
  let rejectCode;
  const code = new Promise((resolve, reject) => {
    resolveCode = resolve;
    rejectCode = reject;
  });
  const ready = new Promise((resolveReady, rejectReady) => {
    server = http.createServer((request, response) => {
      const url = new URL(request.url || "/", "http://127.0.0.1");
      if (url.pathname !== CALLBACK_PATH) {
        response.writeHead(404, { "content-type": "text/plain" });
        response.end("Not found");
        return;
      }
      const receivedState = url.searchParams.get("state");
      const code = url.searchParams.get("code");
      const error = url.searchParams.get("error");
      if (error) {
        response.writeHead(400, { "content-type": "text/plain" });
        response.end(`Robinhood authorization failed: ${error}`);
        rejectCode(new Error(`Robinhood authorization failed: ${error}`));
        return;
      }
      if (!code || receivedState !== state) {
        response.writeHead(400, { "content-type": "text/plain" });
        response.end("Invalid Robinhood authorization callback.");
        rejectCode(new Error("Invalid Robinhood authorization callback"));
        return;
      }
      response.writeHead(200, { "content-type": "text/html" });
      response.end("<p>Robinhood authorization completed. You can close this tab.</p>");
      resolveCode({ code });
    });
    server.once("error", (error) => {
      rejectReady(error);
      rejectCode(error);
    });
    server.listen(port, "127.0.0.1", () => {
      const address = server.address();
      resolveReady({ server, port: address.port });
    });
  });
  return {
    ready,
    code,
    close: () => server?.close(),
  };
}

function openBrowser(url) {
  const platform = process.platform;
  const command =
    platform === "win32" ? "rundll32.exe" : platform === "darwin" ? "open" : "xdg-open";
  const args = platform === "win32" ? ["url.dll,FileProtocolHandler", url] : [url];
  const child = spawn(command, args, { detached: true, stdio: "ignore" });
  child.unref();
}

async function registerClient(metadata, redirectUri) {
  const registrationEndpoint = metadata.registration_endpoint;
  if (!registrationEndpoint) {
    throw new Error("Robinhood OAuth metadata did not include a registration_endpoint");
  }
  return await fetchJson(registrationEndpoint, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      client_name: "codex-rh-fast",
      redirect_uris: [redirectUri],
      grant_types: ["authorization_code", "refresh_token"],
      response_types: ["code"],
      token_endpoint_auth_method: "none",
      scope: "internal",
    }),
  });
}

async function requestToken(metadata, params) {
  return await fetchJson(metadata.token_endpoint, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(params),
  });
}

function saveCredential({ serverName, client, token, metadata }) {
  const expiresIn = Number.parseInt(token.expires_in, 10);
  const filePath = credentialPath();
  const credentials = fsExists(filePath) ? readJson(filePath) : {};
  credentials[serverName] = {
    server_name: serverName,
    server_url: DEFAULT_MCP_SERVER_URL,
    access_token: token.access_token,
    refresh_token: token.refresh_token,
    token_type: token.token_type || "Bearer",
    scope: token.scope || "internal",
    client_id: client.client_id,
    token_endpoint: metadata.token_endpoint,
    expires_at: Number.isFinite(expiresIn)
      ? new Date(Date.now() + expiresIn * 1000).toISOString()
      : undefined,
    updated_at: new Date().toISOString(),
  };
  writeJson(filePath, credentials);
  return filePath;
}

function fsExists(filePath) {
  try {
    return Boolean(readJson(filePath));
  } catch {
    return false;
  }
}

async function main() {
  const args = process.argv.slice(2);
  if (args.includes("--help") || args.includes("help")) {
    usage();
    return;
  }
  const options = parseArgs(args);
  const serverName = options["server-name"] || DEFAULT_SERVER_NAME;
  const port = Number.parseInt(options.port || "0", 10);
  const state = base64Url(crypto.randomBytes(24));
  const codeVerifier = base64Url(crypto.randomBytes(48));
  const codeChallenge = sha256Base64Url(codeVerifier);
  const metadata = await oauthMetadata();
  const listener = listenForCode({ port: Number.isFinite(port) ? port : 0, state });
  const ready = await listener.ready;
  const redirectUri = `http://127.0.0.1:${ready.port}${CALLBACK_PATH}`;
  const client = await registerClient(metadata, redirectUri);
  if (!client.client_id) {
    throw new Error("Robinhood OAuth registration did not return client_id");
  }
  const authorizationUrl = new URL(metadata.authorization_endpoint);
  authorizationUrl.searchParams.set("response_type", "code");
  authorizationUrl.searchParams.set("client_id", client.client_id);
  authorizationUrl.searchParams.set("redirect_uri", redirectUri);
  authorizationUrl.searchParams.set("scope", "internal");
  authorizationUrl.searchParams.set("state", state);
  authorizationUrl.searchParams.set("code_challenge", codeChallenge);
  authorizationUrl.searchParams.set("code_challenge_method", "S256");
  authorizationUrl.searchParams.set("resource", DEFAULT_MCP_SERVER_URL);

  console.log(`Open this Robinhood authorization URL if a browser does not open:\n${authorizationUrl}`);
  if (options["no-open"] !== "true") {
    openBrowser(String(authorizationUrl));
  }

  const timeout = new Promise((_, reject) =>
    setTimeout(() => reject(new Error("Timed out waiting for Robinhood authorization")), LOGIN_TIMEOUT_MS),
  );
  try {
    const callback = await Promise.race([listener.code, timeout]);
    const token = await requestToken(metadata, {
      grant_type: "authorization_code",
      code: callback.code,
      redirect_uri: redirectUri,
      client_id: client.client_id,
      code_verifier: codeVerifier,
      resource: DEFAULT_MCP_SERVER_URL,
    });
    const filePath = saveCredential({ serverName, client, token, metadata });
    console.log(
      JSON.stringify({
        credential_path: filePath,
        server_name: serverName,
        expires_at: token.expires_in
          ? new Date(Date.now() + Number.parseInt(token.expires_in, 10) * 1000).toISOString()
          : null,
      }),
    );
  } finally {
    listener.close();
  }
}

main().catch((error) => {
  console.error(`ERR ${error.stack || error.message}`);
  process.exit(1);
});
