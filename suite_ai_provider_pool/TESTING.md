# Manual Testing Checklist — `suite_ai_provider_pool`

A practical, time-boxed checklist for validating the module against a
real Odoo 19 Enterprise instance. Designed to be executed top-down by
a system administrator with one terminal and one browser tab.

---

## Prerequisites

- Odoo 19 Enterprise with the `ai_app` module installed.
- `suite_ai_provider_pool` installed (`Apps` → search → install).
- Logged in as a user in the **Settings** group (`base.group_system`).
- The Odoo server must be able to reach the test endpoints over HTTP.

For convenience, keep the Odoo log tailing in another terminal so you
can see API errors as they happen:

```bash
tail -f /var/log/odoo/odoo-server.log
```

---

## How to use this checklist

- Run scenarios in order. Each `[ ]` is one observable expectation —
  tick it once you have seen the expected behaviour.
- Stop at the first failure and capture the log line that produced it.
- All scenarios except #4 take ~5 minutes. Scenario #4 takes ~15
  minutes including the Ollama install.

---

## Scenario 1 — Regression: Anthropic Claude still works

**Why first:** the refactor that introduced Self-Hosted did not touch
the Anthropic code path, but a regression test costs nothing.

**Setup**

- Have an Anthropic API key ready (from `console.anthropic.com`).

**Steps**

1. Go to **Settings → AI**.
2. In *Use your own Anthropic Claude account*, paste the key. **Save**.
3. Go to **AI → Configuration → Agents**, open any existing agent
   (or create a new one named "Test Claude").
4. Set **LLM Model** to `Claude Haiku 4.5` (fastest / cheapest).
5. In the agent's chat panel, send: `Hello, reply with exactly OK.`

**Expected**

- [ ] The Claude options appear in the model dropdown
      (`Claude Opus 4.7 / Sonnet 4.6 / Haiku 4.5`).
- [ ] The agent replies with `OK` (or close to it).
- [ ] No traceback in the Odoo log.

---

## Scenario 2 — Regression: DeepSeek still works

**Why important:** DeepSeek's helper was refactored in this release to
share OpenAI-compatible response parsing with Self-Hosted. This test
proves the refactor is behaviour-preserving.

**Setup**

- Have a DeepSeek API key ready (from `platform.deepseek.com`).

**Steps**

1. **Settings → AI**, paste the key into *Use your own DeepSeek
   account*. **Save**.
2. Open the test agent, set **LLM Model** to `DeepSeek V3 (Chat)`.
3. Send: `Reply with exactly OK.`

**Expected**

- [ ] DeepSeek options visible in the model dropdown.
- [ ] Reply is `OK`.
- [ ] No traceback.

**Tool-calling regression** (only if the agent has tools attached):

- [ ] Send a request that triggers a tool — confirm the tool call is
      executed and a final answer comes back.

---

## Scenario 3 — Self-Hosted (fastest path: DeepSeek cloud as stand-in)

**Why this works:** DeepSeek's API is OpenAI-compatible, so it can
exercise the entire Self-Hosted code path (URL normalization, optional
auth, `/v1/models` probe, request/response loop) without installing
anything locally.

**Steps**

1. **Settings → AI → Connect a Custom LLM (self-hosted or cloud)** block.
2. Fill in:
   - **Server URL**: `https://api.deepseek.com`
   - **API Key**: your DeepSeek key (paste into the *LLM API Key*
     field, not the DeepSeek field).
   - Leave **Custom Models** empty for now.
3. Click **Test Connection**.
4. Click **Fetch Available Models**.
5. **Save**.
6. Open the test agent, set **LLM Model** to one of the curated
   defaults (e.g. `Llama 3.3 70B`) — pick any that DeepSeek actually
   serves; if unsure, pick a model that was just fetched.
7. Send: `Reply with exactly OK.`

**Expected**

- [ ] Test Connection toast: `Custom LLM connection OK. Reached
      https://api.deepseek.com/v1, N model(s) available.`
- [ ] Fetch Available Models toast: `Added N new model(s) ...`.
- [ ] After Save, the fetched DeepSeek model identifiers appear in
      the agent's model dropdown alongside curated defaults.
- [ ] The agent replies normally.

---

## Scenario 4 — Self-Hosted (real path: local Ollama on a laptop)

**Why this matters:** this is the production scenario for most
customers — a local LLM with no cloud, no API key, no per-token cost.

**Setup (one-time, ~5 minutes)**

```bash
# macOS / Linux:
curl -fsSL https://ollama.com/install.sh | sh

# Pull a tiny model (~400 MB) — runs on CPU, no GPU required.
ollama pull qwen2.5:0.5b
# Or a 1B model if your machine has 8 GB+ RAM:
ollama pull llama3.2:1b

# Verify Ollama is serving:
curl http://localhost:11434/v1/models
# Should return a JSON list with the pulled model.
```

**Server URL to use in Odoo**

- If Odoo runs natively on the same machine: `http://localhost:11434`
- If Odoo runs in Docker on the same machine:
  `http://host.docker.internal:11434` (Mac/Windows) or use the
  host's LAN IP (Linux: `ip route | awk '/default/ { print $3 }'`)
- If Odoo runs on a different machine: that machine's LAN IP, and
  start Ollama with `OLLAMA_HOST=0.0.0.0 ollama serve` so it accepts
  external connections.

**Steps**

1. **Settings → AI → Connect a Custom LLM** block.
2. Fill in:
   - **Server URL**: e.g. `localhost:11434` (no `http://`, no `/v1` —
     verifies the smart normalizer).
   - **API Key**: leave empty (verifies the optional-auth path).
   - **Custom Models**: leave empty.
3. Click **Test Connection** → expect green toast.
4. Click **Fetch Available Models** → expect the textarea to
   auto-populate with `qwen2.5:0.5b` (or whatever is installed).
5. **Save**.
6. Open the test agent, set **LLM Model** to `qwen2.5:0.5b`
   (now in the dropdown).
7. Send: `Reply with exactly OK.`

**Expected**

- [ ] URL `localhost:11434` is accepted and resolved to
      `http://localhost:11434/v1` internally (no error).
- [ ] Test Connection succeeds without an API key.
- [ ] Fetched models appear in the textarea, one per line.
- [ ] After Save, the custom model is selectable in the agent's
      model dropdown.
- [ ] The reply comes back (small models are not very smart but they
      should respond — `OK` or close to it).
- [ ] Ollama log shows the request hitting `/v1/chat/completions`.

**Bonus: tool calling on a small model**

Most ≤ 3B models are unreliable at tool calling. Skip this on
`qwen2.5:0.5b`. If you have `qwen2.5:14b` or `llama3.3:70b`, attach
a tool to the agent and confirm the tool runs end-to-end.

---

## Scenario 5 — Self-Hosted (no-install alternative: Groq free tier)

**Use when:** you cannot run anything locally but want to verify the
Self-Hosted path against a real OpenAI-compatible cloud that hosts
open-source models.

**Setup**

- Sign up at `console.groq.com` (free tier, no card required).
- Generate an API key.

**Steps**

1. **Settings → AI → Connect a Custom LLM** block.
2. Fill in:
   - **Server URL**: `https://api.groq.com/openai/v1`
     (note: Groq's path is `/openai/v1`, not just `/v1` — type the
     full path including `/v1` and the normalizer will leave it alone).
   - **API Key**: your Groq key.
3. Test Connection → Fetch Available Models → Save.
4. Pick e.g. `llama-3.3-70b-versatile` from the agent dropdown.
5. Send: `Reply with exactly OK.`

**Expected**

- [ ] All four steps succeed; reply comes back fast (Groq is famous
      for low latency).

---

## Scenario 6 — UX edge cases

Quick smoke tests of the polish details — each should take under a
minute.

### URL normalization

In **Settings → AI**, type these into Server URL one at a time and
click **Test Connection** (against any reachable endpoint, e.g. the
Ollama from Scenario 4):

- [ ] `localhost:11434` → works
- [ ] `http://localhost:11434` → works
- [ ] `http://localhost:11434/` → works
- [ ] `http://localhost:11434/v1` → works
- [ ] `http://localhost:11434/v1/` → works
- [ ] empty string → button raises a clear `Fill in the
      LLM Server URL first.` error

### Bad endpoint

- [ ] Set Server URL to `http://localhost:65000` (nothing listening) →
      Test Connection raises `Could not reach ...: <connection refused>`,
      no traceback.
- [ ] Set Server URL to `https://example.com` (returns HTML, not JSON) →
      Test Connection raises `Server at ... returned a non-JSON
      response — is this an OpenAI-compatible endpoint?`.

### Custom Models textarea

- [ ] Type a line like `qwen2.5:7b | Qwen 2.5 7B (production)` →
      Save → the agent dropdown shows `Qwen 2.5 7B (production)` as
      the label, with `qwen2.5:7b` as the underlying model id.
- [ ] Add a comment line `# this is ignored` → Save → no error,
      no extra entry in the dropdown.
- [ ] Re-click Fetch Available Models on a server you have already
      fetched from → toast says `No new models — all N model(s) ...
      are already in the list.`

### Custom LLM without configuration

- [ ] Clear the Server URL field, Save. Open an agent that was using
      a Custom LLM model and try to chat → expect the user-facing
      error: `Custom LLM server URL is not configured. Open
      Settings → AI and fill in the Server URL.`

---

## Recovery: where to look when something fails

| Symptom                                         | Where to look                                           |
| ----------------------------------------------- | ------------------------------------------------------- |
| Settings buttons do nothing                     | Browser devtools → Network tab; check the XML-RPC call. |
| Models from Fetch do not appear in the dropdown | Confirm you clicked **Save** after fetching.            |
| Custom model in dropdown but request 404s       | Server actually serving that model? Check `ollama list` |
| `No API key set for provider 'selfhosted'`      | The `optional` flag did not propagate — file an issue.  |
| Anything raising a Python traceback             | Odoo log: copy the full traceback into the issue.       |

---

## When all scenarios pass

The module is ready to publish to the Apps Store. Before submitting,
also verify:

- [ ] `__manifest__.py` description is pure ASCII (Apps Store
      rendering bug #37364).
- [ ] `static/description/banner.png` exists and has the new
      Self-Hosted positioning visible.
- [ ] Screenshots are 16:9 at 1920x1080 with margin at top-right.
