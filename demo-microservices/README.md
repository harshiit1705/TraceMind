# TraceMind Demo Microservices

An independent sample distributed e-commerce system designed to generate realistic customer traffic, service-to-service latency, cascading errors, and telemetry streams for **TraceMind** observability and root-cause investigation.

## Architecture & Ports

| Service | Port | Description |
| :--- | :--- | :--- |
| **Order Service** | `8001` | Checkout orchestrator (`POST /orders`). Calls Inventory & Payment services. |
| **Payment Service** | `8002` | Payment processor (`POST /payments/charge`). Supports latency & error injection. |
| **Inventory Service** | `8003` | Warehouse stock manager (`POST /inventory/reserve`). Supports lock contention & outages. |

TraceMind continues running independently on its standard ports (`8000` backend, `5173` frontend). Telemetry flows asynchronously via HTTP `POST /api/v1/anomalies/evaluate`.

## Running the Services

From `D:\TraceMind\demo-microservices` (or using TraceMind's virtual environment):

```bash
# Start all three services concurrently
..\backend\.venv\Scripts\python.exe run_all.py
```

## Traffic & Fault Injection CLI

Once the microservices (and TraceMind backend) are running, use the CLI to execute repeatable scenarios:

```bash
# 1. Inspect service health & active faults
..\backend\.venv\Scripts\python.exe -m simulator.cli status

# 2. Run normal steady-state traffic (establishes statistical baselines in TraceMind)
..\backend\.venv\Scripts\python.exe -m simulator.cli scenario normal --count 10

# 3. Trigger Inventory Latency Spike (+650ms) + controlled correlation evaluation
..\backend\.venv\Scripts\python.exe -m simulator.cli scenario inventory-latency --delay-ms 650 --requests 5

# 4. Trigger Payment Gateway Error Spike (100% HTTP 502) + controlled correlation evaluation
..\backend\.venv\Scripts\python.exe -m simulator.cli scenario payment-errors --error-pct 100 --requests 5

# 5. Reset faults and verify healthy recovery
..\backend\.venv\Scripts\python.exe -m simulator.cli scenario recover --count 5
```

