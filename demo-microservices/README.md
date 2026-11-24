# TraceMind Demo Microservices

These three FastAPI services form a small distributed e-commerce system used to generate realistic request telemetry for TraceMind.

## Services

| Service | Port | Main role |
|---|---:|---|
| Order Service | 8001 | Checkout orchestration |
| Payment Service | 8002 | Payment processing and payment fault injection |
| Inventory Service | 8003 | Stock reservation |

Each service uses the shared observability middleware and telemetry client to emit metrics, structured logs, and distributed spans to the TraceMind backend at `http://localhost:8000/api/v1`.

## Start

Start PostgreSQL and the TraceMind backend first. Then, from the repository root:

```powershell
backend\.venv\Scripts\python.exe demo-microservices\run_all.py
```

The full-stack launcher in `scripts/start_demo.bat` starts the backend, all three services, and the frontend together.

## Payment failure demonstration

Use the browser-based Swagger UI at `http://localhost:8002/docs`.

1. Check `GET /faults` and confirm `fault_type` is `none`.
2. Establish a healthy baseline with successful `POST /payments/charge` requests if this is a fresh project.
3. Use `POST /faults` to inject a controlled fault. For example:

```json
{
  "fault_type": "error_rate",
  "latency_delay_ms": 0,
  "error_rate_pct": 100,
  "error_status_code": 502,
  "error_message": "TraceMind live demo - simulated payment gateway failure"
}
```

4. Submit several `POST /payments/charge` requests and confirm HTTP 502 responses.
5. Wait a few seconds for asynchronous telemetry to flush, then inspect Logs and Traces in TraceMind.
6. Verify that fresh anomaly events exist before triggering **Correlate Incidents** from the TraceMind Services page.

The correlation engine evaluates the last five minutes by default and requires at least two related anomaly events per group. Logs and spans do not automatically count as anomaly events.

## Reset

Use `POST /faults/reset`, then confirm `GET /health` returns a healthy status and `GET /faults` reports `fault_type: "none"`.

For the full setup, recruiter walkthrough, and test commands, see the repository root `README.md`.
