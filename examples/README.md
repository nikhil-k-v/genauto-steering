# Example data

`sim_data/` is a data folder written by the simulator through the real app (gated controller, recorder,
store), so it has exactly the shape the app writes on hardware. Open it with:

```bash
cd pc
python -m steering ui --sim --data ../examples/sim_data
```

There is no catalog in the repo; the app rebuilds it from the `meta.json` files the first time it opens the
folder. Recordings you make while it is open are added to the same folder, so copy it first if you want to
keep it clean.

| collection | recording | what it shows |
|---|---|---|
| sim-demo | `autocal` | end stops found and zero set (health shows T2/T3 before it finished) |
| sim-demo | `hand-left-right` (pinned) | free-spin: a simulated hand turns the wheel left, right, left |
| sim-demo | `hand-left-right_pb01` | played back at ×1, Kp 30: RMS error about 6.5° |
| sim-demo | `hand-left-right_pb02` | played back at ×0.5, Kp 60, Ki 0.2: RMS error about 3.7° |
| tuning | `step`, `relay` | the two tests, with their results |
| tuning | `sine`, `chirp` | test waveforms |
| faults | `switch-opened` | slider moves, then the idle switch opens: the trip, S1/S2 changing and the events are inside |

Regenerate (takes about two minutes, runs in real time):

```bash
cd pc && python tools/make_sim_data.py
```

The numbers come from the simulator's motor model, not the real actuator.
