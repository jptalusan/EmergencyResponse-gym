# EmergencyResponse-gym

Event-driven gym environment for simulating fire/EMS emergency response dispatch in Davidson County (Nashville, TN). Ported from a C++ fire simulator into Python, using the architecture patterns from [MultiModal-DVRP-gym](https://github.com/your-org/MultiModal-DVRP-gym).

## Quick start

```bash
# Install dependencies
uv sync --dev

# Run simulation (first run downloads OSM network + computes shortest paths, cached after)
uv run python -m emergency_response.app

# Run tests
uv run pytest
```

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
src/emergency_response/
├── app.py                      # Hydra entry point
├── metrics.py                  # Incident reporting + CSV export
├── env/
│   └── emergency_env.py        # EmergencyEnv (the core simulation)
├── models/
│   ├── core.py                 # Incident, Apparatus, FireStation, State, enums
│   └── scenario.py             # Scenario config dataclass
├── geography/
│   ├── base.py                 # TravelTimeProvider protocol (OSRM-like interface)
│   ├── network.py              # NetworkGeography (OSMnx + cached shortest paths)
│   └── h3_index.py             # H3 spatial index for coordinate snapping
├── demand/
│   ├── base.py                 # IncidentModel ABC
│   └── empirical.py            # Replays incidents.csv chronologically
├── policy/
│   ├── base.py                 # DispatchPolicy ABC
│   └── nearest.py              # Nearest available apparatus heuristic
├── solver/
│   ├── base.py                 # DispatchSolver ABC
│   └── nearest.py              # Greedy nearest solver
└── utils/
    ├── cache.py                # load_or_compute (pickle-based)
    └── loaders.py              # CSV/GeoJSON loaders + coordinate snapping
```

## Hydra configuration

```
configs/
├── config.yaml          # Root config (defaults, seed, simulation params)
├── city/
│   └── davidson.yaml    # Davidson County bbox, H3 resolution, stations CSV
├── demand/
│   └── empirical.yaml   # Path to incidents.csv
├── policy/
│   └── nearest.yaml     # type: nearest
└── solver/
    └── nearest.yaml     # type: nearest
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

## Data files

| File | Source | Description |
|---|---|---|
| `data/incidents.csv` | Nashville FD | 150K+ incidents with lat/lon, type, level, category, datetime |
| `data/stations_with_apparatus.csv` | Nashville FD | 36 fire stations with apparatus inventory by type |
| `data/bounds.geojson` | Nashville FD | Davidson County service area polygon |

## Tests

```bash
# Run all 73 tests
uv run pytest

# Run by tier
uv run pytest tests/unit/           # 41 tests — fast, no I/O
uv run pytest tests/integration/    # 13 tests — geography + dispatch + snapping
uv run pytest tests/e2e/            # 9 tests  — full simulation loops

# With coverage
uv run pytest --cov=emergency_response
```

## Extensibility

- **New geography backend**: Implement the `TravelTimeProvider` protocol in `geography/base.py` (e.g., `OSRMGeography` that hits a real OSRM server). The interface is `drive_time`, `drive_time_matrix`, `nearest_node` — same shape as OSRM's p2p and table endpoints.
- **New policy**: Subclass `DispatchPolicy` in `policy/base.py`.
- **New solver**: Subclass `DispatchSolver` in `solver/base.py`.
- **New demand model**: Subclass `IncidentModel` in `demand/base.py` (e.g., synthetic Poisson generation).
- **New city**: Add a city yaml config with a bounding box, stations CSV, and incidents CSV.
