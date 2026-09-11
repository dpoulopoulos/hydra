# MCP server

An [MCP](https://modelcontextprotocol.io) server that hands an AI agent a set of
read-only tools over one hydra household: accounts, balances, and what a month
came to. It runs beside the backend, speaks MCP to the agent and REST to hydra,
and holds no credential of its own.

## How a client authenticates

Every client presents its own hydra API token, minted in hydra at
`/api/v1/api-tokens`, as an ordinary bearer token:

```
Authorization: Bearer hyd_...
```

The SDK hands that string to `HydraTokenVerifier` before any tool runs, which
checks it by asking hydra — the only place that can answer. A checked token is
trusted for `TOKEN_CACHE_SECONDS`, because an agent turn makes several tool
calls and checking each separately would be several identical round trips. That
window is also how long a revoked token keeps getting past the door, which is
why it is short; the tool call behind it still reaches hydra, which refuses it.

The token is then carried on the request, and each tool reads it back with
`get_access_token()` and presents it to hydra. Nothing in this process holds a
credential in a global, and the household a request can reach is decided by
hydra from that token.

The server holds no credential of its own, and is not configured with one.
A token in the environment would make the whole deployment act as one person:
every client that connected would read that household, whoever they were.

## Connecting

```bash
claude mcp add --transport http hydra http://localhost:8002/mcp \
  --header "Authorization: Bearer hyd_..."
```

Or, in Claude Desktop's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "hydra": {
      "type": "http",
      "url": "http://localhost:8002/mcp",
      "headers": { "Authorization": "Bearer hyd_..." }
    }
  }
}
```

## What the tools do about money

Hydra stores money as an integer count of minor units, and a transaction is
always a positive magnitude whose direction lives in its `kind`. Handing that
to a model unchanged is how a report ends up off by a factor of a hundred, or
with a sign nobody put there. Three things keep it straight, all in code rather
than only in the instructions:

- **Nothing is named `*_minor` on the way out.** `money.py` renders an amount
  three ways: `amount` is what a person would write, `display` is that with its
  currency and sign, and `amount_minor` is the exact integer for arithmetic.
  Every amount states its currency.
- **The sign is applied once, from what the amount means.** A transaction never
  comes back negative; `display` carries the direction. A total is the
  exception and keeps its own sign, because a month that spent more than it
  earned genuinely has a negative net.
- **More precision than a currency has is refused, not rounded.** A caller that
  writes `10.005` has made a mistake, and saying so puts it where it can be
  corrected rather than hiding it until somebody reconciles a statement.
  Currencies without two decimals are listed rather than assumed.

## Errors

The SDK draws a line this server follows. `ToolError` reaches the model, which
can act on it; `MCPError` reaches the host, and the model never sees it.

| From hydra | Raised as | Why |
|---|---|---|
| 401, 403 | `MCPError` | No rewording of the arguments makes a revoked token work. |
| 404, 409 | `ToolError` | hydra's own message already says what to do. |
| 400, 422 | `ToolError` | Nearly always an argument the model can fix. |
| unreachable | `ToolError` | Told apart from a 4xx, so the model waits rather than rewrites. |

## Working on it

```bash
make mcp-lint       # mypy and ruff
make mcp-format     # format
make mcp-test-unit  # tests with coverage
```

The tests stand in for hydra with an `httpx.MockTransport`, so none of them
needs a backend or a database.

`make dev` from the repository root runs this as a container beside the
backend, reaching it over the compose network.

To run it outside Docker, against a backend on port 8000:

```bash
uv run python -m hydra_mcp.server
```

## What is deliberately not exposed

- **Everything under `/income`.** Client names are encrypted in the browser
  under each person's own PIN and are ciphertext to the server. An agent would
  receive base64 and report it as a name.
- **Household members and invitations.** Adding or removing a member grants or
  revokes access to an entire financial history. That is a decision for a
  person at a keyboard, not a tool call an agent can be talked into by a
  document it read. hydra refuses these to an API token anyway.
- **Anything that writes.** Every tool here is read-only and says so, through
  `read_only_hint`, so a client can tell its user as much. The API tokens it
  uses are read scoped, so hydra enforces it too rather than trusting this
  server's word for it.
