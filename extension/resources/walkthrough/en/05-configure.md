## Configure LLM and Backend

**Open a project folder first.** API keys are written to that folder's `.env`; settings cannot be saved without a folder.

Suggested order: **open folder → save Simulation LLM → initialize workspace → start backend**.

Open the config page and follow the **setup wizard** on first use:

1. **Web import** (optional) — one-click import of the API key, default model, and related settings from AgentSociety Web
2. **Simulation LLM** — API base, key, and model; optional reasoning (thinking) on/off
3. **Save** — write workspace `.env`
4. **Start backend** — save and start the local service
5. **Literature MCP** (optional)
6. **EasyPaper** (optional) — LLM and optional VLM for paper generation
7. **CLI gateway** (optional) — Claude Code / Codex

Use **All settings** for the full tabbed view.

The simulation LLM reasoning dropdown writes `AGENTSOCIETY_LLM_THINKING` (`on` / `off`); leave it empty to omit that parameter (same behavior as older builds). The advanced section next to it also selects the API protocol (OpenAI Chat Completions / Anthropic Messages, `AGENTSOCIETY_LLM_API_TYPE`) and the reasoning control field (`AGENTSOCIETY_LLM_THINKING_FORMAT`); the exact parameter sent depends on the protocol. In full settings, the **Coder** tab can set `AGENTSOCIETY_CODER_LLM_THINKING` and these options independently.

### Required fields

| Field | Meaning | Example |
|-------|---------|---------|
| **API Key** | Provider secret | `sk-...` |
| **API Base** | Service URL | `https://api.openai.com/v1` |

Fiblab users can pick the **Fiblab LLM API** preset (`https://llmapi.fiblab.net/v1`). **Validate**, then **Save**.

### Keep the three connection layers separate

| Layer | Controls | Does not control |
|-------|----------|------------------|
| **Simulation LLM** | AgentSociety simulation and backend model calls; saved in workspace `.env` | Claude Code / Codex provider routing |
| **CLI provider / local Gateway** | Direct or gateway-routed Claude Code / Codex model traffic | Simulation LLM settings |
| **Outbound proxy** | Network egress for the Gateway and newly restarted Codex terminals, including login started in that terminal | Provider selection or local Gateway routing |

The outbound proxy is not the local Gateway. With Codex Gateway routing **off**, official Codex model traffic does not pass through the AgentSociety Gateway. If an outbound proxy is configured and Codex is restarted from this page, the new terminal inherits proxy environment variables; the browser opened for sign-in follows its own system/browser network settings.

### Backend

The backend is a local FastAPI service used by skill management, module discovery, replay APIs, and docs. Without it, you can still edit config, browse the tree, or run experiments via CLI / Claude Code.

| Entry | Action |
|-------|--------|
| Status bar | AI Social Scientist status → Start / Restart / Show Logs |
| Config page | The **Save and Start Backend** button in the page header |
| Command Palette | `Start Backend` |
| Setup wizard | Step 4 |

Default port is usually `localhost:8001`. Restart after changing `.env`.

[Open Config](command:aiSocialScientist.openConfigPage) · [Start Backend](command:aiSocialScientist.startBackend) · [Show Logs](command:aiSocialScientist.showBackendLogs)
