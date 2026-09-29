# Engine Simulator DSL (`.mr`) Cheatsheet

Engine Simulator uses a custom declarative scripting language (`.mr`). Below is the complete syntax guide.

---

## 1. Units & Constants

Always instantiate standard units and constants at the top:
```mr
import "engine_sim.mr"

units units()
constants constants()
impulse_response_library ir_lib()
```

Available units:
- Length: `units.mm`, `units.cm`, `units.inch`, `units.thou` (1 thou = 0.001 inch)
- Angle: `units.deg`, `constants.pi`
- Pressure: `units.psi`, `units.bar`, `k_28inH2O(val)`
- Volume: `units.cc`, `units.L`, `units.cm2`, `units.inch2`
- Mass: `units.g`, `units.kg`, `units.lb`
- Speed/Frequency: `units.rpm`, `units.Hz`
- Torque: `units.lb_ft`, `units.Nm`
- Flow: `k_carb(cfm)` (flow conversion helper)

---

## 2. Crankshaft & Rod Journals

```mr
crankshaft c0(
    throw: (stroke / 2),
    flywheel_mass: 25 * units.lb,
    mass: 60 * units.lb,
    friction_torque: 15.0 * units.lb_ft,
    moment_of_inertia: 0.15,
    position_x: 0.0,
    position_y: 0.0,
    tdc: 90 * units.deg + (v_angle / 2.0)
)

rod_journal rj0(angle: 0.0 * units.deg)
rod_journal rj1(angle: 90.0 * units.deg)

c0.add_rod_journal(rj0)
  .add_rod_journal(rj1)
```

---

## 3. Pistons, Rods & Cylinder Banks

```mr
piston_parameters piston_params(
    mass: 350 * units.g,
    compression_height: 1.2 * units.inch,
    wrist_pin_position: 0.0,
    displacement: 0.0
)

connecting_rod_parameters cr_params(
    mass: 400.0 * units.g,
    moment_of_inertia: 0.002,
    center_of_mass: 0.0,
    length: 6.0 * units.inch
)

cylinder_bank_parameters bank_params(
    bore: 4.0 * units.inch,
    deck_height: 9.0 * units.inch
)

cylinder_bank b0(bank_params, angle: -45 * units.deg)
b0.add_cylinder(
    piston: piston(piston_params, blowby: k_28inH2O(0.1)),
    connecting_rod: connecting_rod(cr_params),
    rod_journal: rj0,
    intake: intake,
    exhaust_system: exhaust0,
    ignition_wire: wires.wire1
)
```

---

## 4. Intake & Exhaust Systems

```mr
intake intake(
    plenum_volume: 2.0 * units.L,
    plenum_cross_section_area: 25.0 * units.cm2,
    intake_flow_rate: k_carb(600.0),
    idle_flow_rate: k_carb(0.01),
    idle_throttle_plate_position: 0.985,
    throttle_gamma: 1.5
)

exhaust_system_parameters es_params(
    outlet_flow_rate: k_carb(600.0),
    primary_tube_length: 14.0 * units.inch,
    primary_flow_rate: k_carb(200.0),
    velocity_decay: 1.0,
    volume: 15.0 * units.L
)

exhaust_system exhaust0(
    es_params,
    audio_volume: 2.0,
    impulse_response: ir_lib.default_0
)
```

---

## 5. Camshafts & Heads

```mr
harmonic_cam_lobe lobe(
    duration_at_50_thou: 220 * units.deg,
    gamma: 1.2,
    lift: 450 * units.thou,
    steps: 100
)

b0.set_cylinder_head(
    generic_small_engine_head(
        chamber_volume: 64 * units.cc,
        intake_camshaft: camshaft.intake_cam_0,
        exhaust_camshaft: camshaft.exhaust_cam_0
    )
)
```

---

## 6. Distributor & Ignition Timing

```mr
function timing_curve(1000 * units.rpm)
timing_curve
    .add_sample(0000 * units.rpm, 14 * units.deg)
    .add_sample(2000 * units.rpm, 24 * units.deg)
    .add_sample(4000 * units.rpm, 32 * units.deg)
    .add_sample(6000 * units.rpm, 36 * units.deg)

engine.add_ignition_module(
    distributor(
        wires: wires,
        timing_curve: timing_curve,
        rev_limit: 7500 * units.rpm
    )
)
```
