# Implement SQLite-backed Rate Limiting

Develop a persistent rate-limiting system integrated with the existing MemoryStore and apply it to the public-facing MCP server.

## Files

- **modify** `musonius/memory/store.py`: Extend MemoryStore to support persistent request tracking.
  - Add 'rate_limits' table in 'initialize()' (key, window_start, count).
  - Implement 'get_rate_limit(key, window_start)' to retrieve current hit count.
  - Implement 'increment_rate_limit(key, window_start)' to record new hits.
  - Add periodic cleanup logic for expired rate limit windows.
- **create** `musonius/orchestration/rate_limiter.py`: Core logic for the Fixed Window rate limiting algorithm.
  - Define 'RateLimiter' class accepting a 'MemoryStore'.
  - Implement 'check_limit(key, limit, window_seconds)' returning a boolean and current state.
  - Logic to calculate current window bucket based on system time.
- **modify** `musonius/config/defaults.py`: Define default rate limit configurations.
  - Add 'DEFAULT_RATE_LIMIT' (e.g., 100 requests) and 'DEFAULT_RATE_WINDOW' (e.g., 3600 seconds) to the configuration.
- **modify** `musonius/mcp/server.py`: Integrate rate limiting into the MCP server request handling loop.
  - Initialize 'RateLimiter' during server startup.
  - Intercept incoming JSON-RPC calls to check 'RateLimiter.check_limit'.
  - Return a standardized error response (Error Code -32001 or similar) when limit is exceeded.

## Acceptance Criteria

- [ ] Concurrent requests from the same identifier are throttled once the limit is reached.
- [ ] Rate limit state is preserved after restarting the server.
- [ ] The system identifies users by IP or API key (if provided).
- [ ] A clear error message and appropriate headers/response codes are returned on failure.

## Test Strategy

Unit tests in 'tests/test_rate_limiter.py' using a temporary SQLite database to verify windowing logic. Integration test in 'tests/test_mcp.py' using a mock client to fire rapid requests and verify the error state.

## Estimates

Estimated tokens: 4320
