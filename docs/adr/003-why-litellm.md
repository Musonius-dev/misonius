# ADR-003: Why LiteLLM for Model Routing

## Status

Accepted

## Context

Musonius needs to call multiple LLM providers (Anthropic, Google, xAI, OpenAI, local models via Ollama) across different operational roles — scouting, planning, verification, and summarization. The routing solution must:

- Support 100+ providers with a unified API
- Handle BYOK (bring your own key) — users supply their own API keys
- Provide retry logic with exponential backoff and fallback support
- Track token usage and costs per model
- Support custom model definitions (provider, api_base, api_key_env)
- Integrate with local models (Ollama, vLLM) for offline/free-tier operation

## Decision

Use **LiteLLM** as the model routing layer, wrapped by `ModelRouter` in `musonius/orchestration/router.py`.

## Rationale

### Advantages

1. **Universal Provider Support**
   - 100+ providers (Anthropic, Google, xAI, OpenAI, Mistral, Cohere, etc.)
   - Unified OpenAI-compatible API surface
   - Local model support (Ollama, vLLM)

2. **BYOK Model**
   - Users provide their own API keys via environment variables
   - No Musonius-managed accounts or API proxies
   - No markup on API costs

3. **Built-in Features**
   - Token counting per response
   - Cost estimation via `litellm.completion_cost()`
   - Streaming support
   - Provider-specific parameter handling

4. **Configuration Flexibility**
   - Standard LiteLLM model identifiers pass through directly (e.g., `gemini/gemini-2.0-flash`)
   - Custom model definitions via YAML config with `provider`, `model`, `api_base`, `api_key_env`
   - Environment variable resolution for API keys

5. **Active Maintenance**
   - Regular updates tracking new provider APIs
   - Large community and good documentation

### Alternatives Considered

#### Direct API Calls
- No external dependency
- Must implement retry logic, fallback, cost tracking, and provider-specific APIs manually
- Significant ongoing maintenance burden as providers evolve

#### LangChain
- Comprehensive framework with broad provider support
- Heavy dependency graph (100+ transitive packages)
- Opinionated architecture conflicts with Musonius's lean design
- Explicitly prohibited in CLAUDE.md anti-patterns

#### Custom Abstraction Layer
- Full control over API surface
- Significant development effort to reach LiteLLM's provider coverage
- Reinvents well-solved problems (retries, cost tracking, provider normalization)

## Consequences

### Positive

- Works with any LLM provider via a single `litellm.completion()` call
- Users control their own API costs and provider selection
- Built-in cost estimation reduces custom accounting code
- Role-based model routing (scout, planner, verifier, summarizer) maps cleanly onto config

### Negative

- Additional runtime dependency (~50MB installed)
- Tied to LiteLLM's API surface — breaking changes require updates
- Some providers may lag behind their official SDKs

### Mitigation

- LiteLLM version pinned in `pyproject.toml` (`>=1.50`)
- `litellm.suppress_debug_info = True` silences verbose internal logging
- Cost calculation wrapped in try/except — gracefully falls back to `$0.00` for unknown models
- Custom model definitions provide an escape hatch for any provider LiteLLM doesn't natively support

## Implementation

### ModelRouter (`musonius/orchestration/router.py`)

The `ModelRouter` class wraps LiteLLM with:

- **Custom model resolution** — maps short names (e.g., `local-llama`) to full `provider/model` strings with optional `api_base` and `api_key` injection
- **Retry with exponential backoff** — `2^attempt` seconds between retries
- **Fallback model support** — if the primary model exhausts retries, a fallback model is tried once
- **Usage tracking** — every call records prompt tokens, completion tokens, and cost via `UsageTracker`
- **Role-based convenience methods** — `call_scout()`, `call_planner()`, `call_verifier()` resolve the configured model for each role

```python
from musonius.orchestration.router import ModelRouter

router = ModelRouter(config)

# Role-based calls
response = router.call_scout(messages=[{"role": "user", "content": "Analyze this"}])
response = router.call_planner(messages=[{"role": "user", "content": "Plan this"}])

# Direct call with retry and fallback
response = router.call(
    model="anthropic/claude-sonnet-4-20250514",
    messages=messages,
    retries=2,
    fallback_model="gemini/gemini-2.0-flash",
)

# Usage report
print(router.usage_tracker.report())
```

### UsageTracker (`musonius/orchestration/usage.py`)

Accumulates token usage and cost across all model calls. Provides:
- Per-model breakdown via `by_model()`
- Formatted report via `report()`
- Properties: `total_tokens`, `total_cost`, `call_count`

### Default Model Configuration (`musonius/config/defaults.py`)

| Role | Default Model | Cost Tier |
|------|--------------|-----------|
| Scout | `gemini/gemini-2.0-flash` | Free |
| Planner | `anthropic/claude-sonnet-4-20250514` | Premium |
| Verifier | `gemini/gemini-2.0-flash` | Free |
| Summarizer | `ollama/llama3.2` | Free (local) |

### Configuration Example

```yaml
# .musonius/config.yaml
models:
  scout: "gemini/gemini-2.0-flash"
  planner: "anthropic/claude-sonnet-4-20250514"
  verifier: "xai/grok-3"

  custom:
    - name: "local-llama"
      provider: "ollama"
      model: "llama3.2"
    - name: "deepseek-r1"
      provider: "openai"
      model: "deepseek-reasoner"
      api_base: "https://api.deepseek.com/v1"
      api_key_env: "DEEPSEEK_API_KEY"
```

## References

- LiteLLM documentation: https://docs.litellm.ai/
- Supported providers: https://docs.litellm.ai/docs/providers
- Implementation: `musonius/orchestration/router.py`
- Usage tracking: `musonius/orchestration/usage.py`
- Tests: `tests/test_router.py`
