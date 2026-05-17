# EmergencyResponse-gym

Event-driven gym environment for simulating fire/EMS emergency response dispatch in Davidson County (Nashville, TN). Ported from a C++ fire simulator into Python, using the architecture patterns from [MultiModal-DVRP-gym](https://github.com/your-org/MultiModal-DVRP-gym).

## Quick start

### Simulation (standalone)

```bash
# Install dependencies
uv sync --dev

# Run simulation (first run downloads OSM network + computes shortest paths, cached after)
uv run python -m emergency_response.app

# Run tests
uv run pytest
```
Simulation results are written into CSV files under `/output`.

### FastAPI backend

***Ensure the `Memory Limit` allocated in `Docker > Settings > Resources` is adequate (~24 GB).***

#### Steps
- Start Docker. ([Docker](https://www.docker.com/), [Get started](https://docs.docker.com/get-started/), [Get Docker](https://docs.docker.com/get-started/get-docker/))
    ```bash
    # Set up from 'docker-compose.yml'.
    docker-compose up
    # Trigger a new build.
    docker-compose up --build
    ```
- In your browser, go to one of the following URLs (same funcionality, slightly different UI):
    - http://127.0.0.1:8000/docs
    - http://127.0.0.1:8000/redoc
- Now you can:
    - Register a user.
    - Log in a user with a valid `username` and `password` combination.
    - Submit a job. Use the following `string` values (or a valid directory and name of a configuration file) for `config_dir` and `config_name`.
        ```python
        {
            config_dir = "/app/configs",
            config_name = "config"
        }
        ```
    - List all the jobs belonging to a user. 
    - Get (retrieve) the details of a specific job of a user.
    - Run a simulation (no authenication required). This is intended for development purposes. Avoid using it as part of the application. It will be removed eventually.
    - Check the health of the backend. (Currently returns `"ok"` at all times.)
- Job details are stored locally under
    - `/storage/jobs/{job_id}/configs` for configurations,
    - `/storage/jobs/{job_id}/data` for data (input),
    - `/storage/jobs/{job_id}/output` for output.

## How the environment works

`EmergencyEnv` is an event-driven simulation. Time jumps from incident to incident (not fixed time steps). Each `step()` processes one incident and advances the world to the next.

### The loop

```
state = env.reset()                    # load stations, apparatus, first incident

while not done:
    action = policy.dispatch(state)    # policy decides which apparatus to send
    state, reward, done, info = env.step(action)

env.drain()                            # wait for all apparatus to return home
```

### What happens inside `step(action)`

```
1. DISPATCH ── apply the action (list of DispatchActions)
   │  - Mark each apparatus as EN_ROUTE
   │  - Set arrival_time = now + 60s (turnout) + travel_time
   │  - Set incident.resolved_at = first_arrival + resolution_time_by_category
   │  - Compute reward = -(60s + min_travel_time)
   │
2. NEXT INCIDENT ── pull the next incident from the demand model
   │  - If exhausted → done = True
   │
3. SIMULATE FORWARD ── advance all apparatus to the next incident's report_time
   │  - Each apparatus transitions through its state machine (see below)
   │  - Resolved incidents are cleaned up once all their apparatus return
   │
4. RETURN ── (state, reward, done, info)
```

### Apparatus state machine

Each apparatus cycles through these states. Transitions happen in `_simulate_time_step()` and can chain in a single call when the time gap is large enough:

```
                    dispatch
AVAILABLE ─────────────────────► EN_ROUTE
    ▲                                │
    │                                │ arrival_time <= now
    │                                ▼
    │                           AT_INCIDENT
    │                                │
    │                                │ incident.resolved_at <= now
    │                                ▼
    └─────────────────────────── RETURNING
              return_time <= now
```

| Transition | Trigger | What happens |
|---|---|---|
| AVAILABLE → EN_ROUTE | `_execute_dispatch()` | Apparatus assigned to incident, 60s turnout + travel_time |
| EN_ROUTE → AT_INCIDENT | `arrival_time <= end_time` | Apparatus on scene, incident.arrived_apparatus updated |
| AT_INCIDENT → RETURNING | `incident.resolved_at <= end_time` | Incident resolved, apparatus heads home (same travel time) |
| RETURNING → AVAILABLE | `return_time <= end_time` | Apparatus back at station, all fields cleared |

### Incident state machine

```
REPORTED ──dispatch──► RESPONDED ──resolved_at reached──► RESOLVED ──all apparatus home──► (removed)
```

Incidents with no dispatch (unknown category, no resources) are cleaned up immediately.

### Timing diagram

For a single incident dispatched at time T:

```
T              T+60s            T+60s+travel     T+60s+travel+resolution    T+60s+2*travel+resolution
│               │                   │                     │                          │
│  dispatch     │  apparatus        │  first arrival      │  incident resolved       │  apparatus home
│  decision     │  departs          │  (response_time)    │                          │  (AVAILABLE)
│               │  (turnout delay)  │                     │                          │
```

### Reward

`reward = -(RESPOND_DELAY + min_travel_time)` — the negative response time of the **first-arriving** apparatus. Lower response time = higher (less negative) reward. Raw response time is also available in `info["response_time"]`.

### What gets cached

All heavy computation is cached to `cache/` on first run:

| Cache file | What | When rebuilt |
|---|---|---|
| `cache/graph_<hash>.pickle` | OSMnx road network (Davidson County) | bbox or network_type changes |
| `cache/travel_times_<hash>.npz` | All-pairs shortest path matrix (float32) | graph changes |
| `cache/stations_snapped.pkl` | Stations + apparatus snapped to graph nodes | stations CSV or graph changes |
| `cache/incidents_snapped.pkl` | Incidents snapped to graph nodes | incidents CSV or graph changes |

Delete `cache/` to force a full rebuild.

## Project structure

```
EmergencyResponse-gym/
├── configs/                            # Configurations for Emergency Response
│   ├── city/                           # Hydra subconfigurations for 'city'
│   │   └── ...
│   ├── demand/                         # Hydra subconfigurations for 'demand'
│   │   └── ...
│   ├── policy/                         # Hydra subconfigurations for 'policy'
│   │   └── ...
│   ├── solver/                         # Hydra subconfigurations for 'solver'
│   │   └── ...
│   └── config.yaml                     # Root configuration (defaults, seed, simulation parameters)
├── data/                               # Data (input) for the current simulation
│   ├── osm/                            # OSM files downloaded geofabrik.de
│   ├── osmium/                         # OSM files extracted using 'osmium-tool'
│   ├── osrm/                           # OSRM files pre-processed using an OSRM container
│   ├── bounds.geojson                  # Geographic bounds
│   ├── incidents.csv                   # Incidents CSV file
│   └── stations_with_apparatus.csv     # Stations with apparatus CSV file
├── docker/                             # Docker configurations and settings for containers from images
│   └── vroom/                          # Docker configurations and settings for VROOM
│       └── ...
├── output/                             # Output of the current simulation job
├── script/                             # Scripts for various operations
│   ├── download_osm_data.sh            # Download desired OSM data to a default path
│   ├── extract_region.sh               # Extract a region from OSM data using 'osmium-tool'
│   └── osrm_healthcheck.sh             # Health check an OSRM container
├── src/                                # Source code of the modules
│   ├── backend/                        # Backend module (using FastAPI)
│   │   └── ...
│   ├── db/                             # Database and storage management module (using postgres)
│   │   └── ...
│   ├── emergency_response/             # Module for event-driven simulation
│   │   └── ...
│   ├── utils/                          # Utilities for the overall project
│   │   └── ...
│   └── worker/                         # Worker module (job queueing and processing)
│       └── ...
├── storage/                            # Storage path
│   └── jobs/                           # Storage path fo jobs (configs, data, output) under their ID
├── tests/                              # Tests
│   ├── conftest.py                     # Shared test fixtures for the emergency response gym test suite
│   ├── e2e/                            # End-to-end tests
│   │   └── ...
│   ├── integration/                    # Integration tests
│   │   └── ...
│   └── unit/                           # Unit tests
│       └── ...
├── .env                                # Environment file (environment variables: DATABASE_URL, SECRET_KEY)
├── Dockerfile                          # Dockerfile
├── docker-compose.yml                  # Dockerfile (main)
├── docker-compose_osrm_vroom.yml       # Dokcerfile (for OSRM and VROOM)
├── pyproject.toml                      # Python project configuration (metadata, dependencies, build system)
└── README.md                           # ReadMe MarkDown file (this document)
```

## Hydra configuration

```
configs/
├── config.yaml                         # Root configuration (defaults, seed, simulation parameters)
├── city/                               # Hydra subconfigurations for 'city'
│   └── davidson.yaml                   # Davidson County bbox, H3 resolution, stations CSV
├── demand/                             # Hydra subconfigurations for 'demand'
│   └── empirical.yaml                  # Demand type and path to incidents.csv
├── policy/                             # Hydra subconfigurations for 'policy'
│   └── nearest.yaml                    # Dispatch policy type: nearest
└── solver/                             # Hydra subconfigurations for 'solver'
    └── nearest.yaml                    # Dispatch solver type: nearest
```

### Root config (`config.yaml`)

```yaml
defaults:
  - city: davidson       # which city config to use
  - demand: empirical    # incident source
  - policy: nearest      # dispatch policy
  - solver: nearest      # dispatch solver

seed: 42

simulation:
  max_incidents: 1000    # stop after N incidents
  start_time: null       # null = use first incident time from CSV
  drain: true            # simulate until all apparatus return after last incident
  max_drain_time: 7200   # max seconds to wait during drain
```

### CLI overrides

```bash
# Run fewer incidents
uv run python -m emergency_response.app simulation.max_incidents=100

# Change seed
uv run python -m emergency_response.app seed=123

# Skip drain phase
uv run python -m emergency_response.app simulation.drain=false

# Combine overrides
uv run python -m emergency_response.app simulation.max_incidents=500 seed=7
```

To add a new city, create `configs/city/<name>.yaml` with the same structure as `davidson.yaml` and run with `city=<name>`.

## Source code

```
src/
├── backend/                            # Backend module (using FastAPI)
│   ├── routes/                         # Routes submodule
│   │   ├── auth.py                     # User authentication routes
│   │   ├── jobs.py                     # User jobs route
│   │   └── sim.py                      # Simulation routes
│   ├── schemas/                        # Schemas submodule of backend
│   │   └── sim.py                      # Schemas for simulation-related objects
│   ├── services/                       # Services submodule of backend
│   │   ├── auth.py                     # Services for user authentication
│   │   └── sim.py                      # Services for simulation-related objects
│   ├── config.py                       # Configuration file for backend
│   └── main.py                         # Entry point for backend
├── db/                                 # Database and storage management module (using postgres)
│   ├── crud.py                         # Fundamental CRUD (Create, Read, Update, Delete) operations
│   ├── models.py                       # Models for database (User, Job)
│   ├── session.py                      # Session manager
│   └── storage.py                      # Storage manager
├── emergency_response/                 # Module for event-driven simulation
│   ├── env/                            # Environment
│   │   └── emergency_env.py            # EmergencyEnv (the core simulation)
│   ├── demand/                         # Demand
│   │   ├── base.py                     # IncidentModel ABC
│   │   └── empirical.py                # Replays incidents.csv chronologically
│   ├── geography/                      # Geography
│   │   ├── base.py                     # TravelTimeProvider protocol (OSRM-like interface)
│   │   ├── network.py                  # NetworkGeography (OSMnx + cached shortest paths)
│   │   └── h3_index.py                 # H3 spatial index for coordinate snapping
│   ├── models/                         # Models
│   │   ├── core.py                     # Incident, Apparatus, FireStation, State, enums
│   │   └── scenario.py                 # Scenario config dataclass
│   ├── policy/                         # Policies
│   │   ├── base.py                     # DispatchPolicy ABC
│   │   └── nearest.py                  # Nearest available apparatus heuristic
│   ├── solver/                         # DispatchSolver
│   │   ├── base.py                     # DispatchSolver ABC
│   │   └── nearest.py                  # Greedy nearest solver
│   ├── utils/                          # Utilities for emergency_response module
│   │   ├── cache.py                    # load_or_compute (pickle-based)
│   │   └── loaders.py                  # CSV/GeoJSON loaders + coordinate snapping
│   ├── app.py                          # Hydra entry point
│   └── metrics.py                      # Incident reporting + CSV export
├── utils/                              # Utilities for the overall project
│   └── config_validator.py             # Configuration path validator
└── worker                              # Worker module ((job queueing and processing)
    ├── main.py                         # Entry point of the worker module
    ├── processor.py                    # Job processor
    └── runner.py                       # Queue runner
```

## Data files

| File | Source | Description |
|---|---|---|
| `data/osm/` | [geofabrik.de](https://www.geofabrik.de/en/index.html) | OSM data (downloaded)  |
| `data/osmium/` | N/A | OSM data (extracted using `osmium-tool`)  |
| `data/osrm/` | N/A | OSRM data (pre-processed using OSRM) |
| `data/incidents.csv` | Nashville FD | 150K+ incidents with lat/lon, type, level, category, datetime |
| `data/stations_with_apparatus.csv` | Nashville FD | 36 fire stations with apparatus inventory by type |
| `data/bounds.geojson` | Nashville FD | Davidson County service area polygon |

## Tests

```
tests/
├── conftest.py                         # Shared test fixtures for the emergency response gym test suite
├── e2e/                                # End-to-end tests
│   ├── test_backend_db_worker.py       # End-to-end tests for the backend, database and worker suite
│   ├── test_backend_sim_api.py         # End-to-end tests for the backend simulation API
│   ├── test_full_src_stack.py          # End-to-end tests for the full stack packages under src
│   ├── test_job_lifecycle.py           # End-to-end tests for the job lifecycle
│   └── test_simulation.py              # End-to-end tests of simulation engine using mock geography
├── integration/                        # Integration tests
│   ├── rest_backend_auth_jobs.py       # Integration tests for backend auth and jobs routes with database CRUD
│   ├── test_backend_db_worker.py       # Integration tests for backend, database, and worker suite
│   ├── test_backend_sim_config.py      # Integration tests for backend sim route and configuration loading
│   ├── test_dispatch.py                # Integration tests for dispatch: policy, solver, geography
│   ├── test_geography.py               # Integration tests for geography: NetworkGeography
│   ├── test_snapping.py                # Integration tests for coordinate snapping
│   └── test_worker_processing.py       # Integration tests for worker processing, backend schemas and storage
└── unit/                               # Unit tests
    ├── test_backend.py                 # Unit tests for backend
    ├── test_db.py                      # Unit tests for database
    ├── test_demand.py                  # Unit tests for the empirical incident model
    ├── test_edge_cases.py              # Unit tests for edge cases across the system
    ├── test_h3_index.py                # Unit tests for H3 spatial index
    ├── test_loaders.py                 # Unit tests for data loaders
    ├── test_logs.py                    # Unit tests for apparatus event logs and step trace records
    ├── test_models.py                  # Unit tests for core data models
    ├── test_solver.py                  # Unit tests for the nearest dispatch solver
    ├── test_utils.py                   # Unit tests for utilities
    └── test_worker.py                  # Unit tests for worker
```

```bash
# Run all 167 tests
uv run pytest

# Run by tier
uv run pytest tests/unit/               # 133 tests — fast, no I/O
uv run pytest tests/integration/        # 20 tests — geography + dispatch + snapping, backend, db, worker, utils
uv run pytest tests/e2e/                # 14 tests — full simulation loops

# With coverage
uv run pytest --cov=emergency_response  # Value is Change 'emergency_response' to any module under 'src'
```

## Extensibility

- **New geography backend**: Implement the `TravelTimeProvider` protocol in `geography/base.py` (e.g., `OSRMGeography` that hits a real OSRM server). The interface is `drive_time`, `drive_time_matrix`, `nearest_node` — same shape as OSRM's p2p and table endpoints.
- **New policy**: Subclass `DispatchPolicy` in `policy/base.py`.
- **New solver**: Subclass `DispatchSolver` in `solver/base.py`.
- **New demand model**: Subclass `IncidentModel` in `demand/base.py` (e.g., synthetic Poisson generation).
- **New city**: Add a city yaml config with a bounding box, stations CSV, and incidents CSV.
