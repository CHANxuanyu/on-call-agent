# Observability & Operations Guide

## Scope

This guide describes the repository's MVP observability baseline and the recommended production operating model.

## MVP Baseline

### What is included

- JSON application logs with `request_id` and `trace_id`
- Per-request middleware logging with latency and status code
- Global unhandled-exception capture with structured context
- Prometheus metrics at `/metrics`
- Liveness probe at `/healthz`
- Readiness probe at `/readyz`
- Docker `HEALTHCHECK`
- Local Prometheus + Grafana stack via `docker-compose.observability.yml`

### Key endpoints

- `GET /healthz`
  Returns 200 when the process is alive.
- `GET /readyz`
  Returns 200 when startup initialization completed and critical local checks passed.
- `GET /metrics`
  Exposes Prometheus metrics.

### Log fields

Every application log line is JSON and includes:

- `timestamp`
- `level`
- `logger`
- `message`
- `request_id`
- `trace_id`

Request-completion logs also include:

- `method`
- `route`
- `path`
- `status_code`
- `duration_ms`

Unhandled exceptions also include:

- `exception_type`
- `stack_trace`

## Local Development

### App only

```bash
cd question-1
source venv/bin/activate
uvicorn app.main:app --reload
```

### App + Prometheus + Grafana

```bash
cd question-1
docker compose -f docker-compose.observability.yml up --build
```

Endpoints:

- App: `http://127.0.0.1:8000`
- Prometheus: `http://127.0.0.1:9090`
- Grafana: `http://127.0.0.1:3000`

Grafana defaults:

- username: `admin`
- password: `admin`

## Production Notes

### Logging

- Ship stdout logs to your platform collector.
- Index `request_id` and `trace_id` so incident timelines can be reconstructed quickly.
- Preserve JSON log format end to end.

### Health checks

- Point the orchestrator liveness probe at `/healthz`.
- Point the readiness probe at `/readyz`.
- Do not route traffic to instances that fail readiness.

### Metrics

- Scrape `/metrics` every 15 seconds.
- Build dashboards for request rate, p95 latency, 4xx/5xx split, and dependency latency.
- Alert on sustained 5xx error rate, readiness failure, and high p95 latency.

### Secrets

- Inject `OPENAI_API_KEY` via the runtime secret manager.
- Never bake API keys into images or compose files.

## PromQL Examples

### Is the service alive?

```promql
up{job="oncall-agent"}
```

### Is the service ready to receive traffic?

```bash
curl -fsS http://127.0.0.1:8000/readyz
```

### What is the 5-minute error rate?

```promql
sum(rate(oncall_agent_http_request_errors_total{status_code=~"5.."}[5m]))
/
clamp_min(sum(rate(oncall_agent_http_requests_total[5m])), 1)
```

### Which endpoint is the slowest?

```promql
topk(
  5,
  histogram_quantile(
    0.95,
    sum(rate(oncall_agent_http_request_duration_seconds_bucket{route!="/metrics"}[5m])) by (le, route)
  )
)
```

### Which dependency is slow?

```promql
histogram_quantile(
  0.95,
  sum(rate(oncall_agent_dependency_request_duration_seconds_bucket[5m])) by (le, dependency, operation)
)
```

## Verification Checklist

1. Start the app and confirm `/healthz` returns 200.
2. Confirm `/readyz` returns 200 after startup.
3. Hit `/v1/search`, `/v2/search`, and `/v3/chat`.
4. Confirm `/metrics` contains `oncall_agent_http_requests_total`.
5. Trigger an error path and confirm a structured `unhandled_exception` log is emitted.
6. Send a request with `X-Request-ID` and confirm the same value is returned in the response header.
