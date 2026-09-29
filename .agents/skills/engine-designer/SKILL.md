---
name: engine-designer
description: >-
  Design and build custom, physically accurate engine definitions (.mr files) for Engine Simulator.
  Use when the user asks to create an engine based on a car name (e.g. 'Ferrari 458', 'Ford Mustang GT',
  'Shelby GT350', 'Dodge Charger Hemi', 'Porsche 911', 'Toyota 2JZ', 'Mazda 787B'), describes an engine
  configuration (V8, V10, V12, I4, I6, Boxer, Rotary), or requests a specific acoustic/musical pitch profile for songs.
---

# Engine Simulator Designer Skill

This skill guides the design, generation, and tuning of custom engine scripts (`.mr` files) for Ange The Great's **Engine Simulator**.

---

## 1. Interaction Modes

When the user asks for a new engine, identify which input mode they are using:

### Mode A: Just a Car or Engine Name
*Example: "Build me a Shelby GT350 engine", "Create a 1969 Dodge Charger 426 Hemi", "Make a Ferrari 458 V8"*
1. Look up the vehicle/engine in [references/car_database.md](./references/car_database.md).
2. If not in the database, deduce or search for its real-world physical specs:
   - Engine configuration (e.g., 90° V8, Cross-Plane vs Flat-Plane)
   - Displacement, Bore, and Stroke
   - Firing order and crankshaft journal angles
   - Valvetrain type (OHV pushrod, SOHC, DOHC) and Cam timing
   - Redline and idle RPM
   - Exhaust characteristics (single, dual, merged, straight pipe)
3. Present a clear, concise specification summary before or while generating the script.

### Mode B: Descriptive / Musical Sound Request
*Example: "I need a high-revving screaming V8 that can play high melodies", "Make a deep rumbly bass V8 for rhythm", "I need an engine tuned to hit A4 at 6000 RPM"*
1. Consult [references/musical_tuning.md](./references/musical_tuning.md) to calculate the cylinder count, firing frequency, and RPM target:
   $$f = \frac{\text{RPM}}{60} \times \frac{N_{\text{cylinders}}}{2} \quad \text{(4-stroke)}$$
2. Tune dynamic parameters for music:
   - **Flywheel**: Reduce `flywheel_mass` (e.g., 2–5 lb) and `moment_of_inertia` for near-instant pitch changes.
   - **Acoustic Purity**: Set `jitter: 0.02` to `0.08` and `noise: 0.05` to `0.1` for clean musical notes.
   - **Timbre**: Select primary tube length and impulse response (`ir_lib`) to match desired brassiness or depth.

---

## 2. Anatomy of an Engine Script (`.mr`)

Every generated `.mr` engine file MUST follow this structural pipeline:

1. **Imports & Global Setup**:
   ```mr
   import "engine_sim.mr"
   units units()
   constants constants()
   impulse_response_library ir_lib()
   label cycle(2 * 360 * units.deg) // 720 deg for 4-stroke
   ```

2. **Ignition Wires Node**:
   ```mr
   private node wires {
       output wire1: ignition_wire();
       output wire2: ignition_wire();
       // ... one per cylinder
   }
   ```

3. **Cylinder Head & Valvetrain**:
   - Define custom cylinder head or use standard library head (`generic_small_engine_head`, `chevy_bbc_peanut_port_head`, etc.).
   - Define camshaft lobes with `harmonic_cam_lobe` and build intake/exhaust camshafts with appropriate lobe separation and advance.

4. **Engine Core Node (`public node <engine_name>`)**:
   - `alias output __out: engine;`
   - `engine engine(name: "...", redline: ... * units.rpm, starter_torque: ...)`
   - `crankshaft c0(throw: stroke / 2, flywheel_mass: ..., mass: ..., moment_of_inertia: ...)`
   - Rod journals with explicit angles matching the firing order.
   - Piston and connecting rod parameters.
   - Cylinder banks with bank angle (e.g. `angle: -45 * units.deg` and `45 * units.deg` for 90° V8).
   - Add cylinders mapping pistons, rods, journals, intake, exhaust, and wires.
   - Timing curve function and ignition distributor module.

5. **Main Pairing Node (`public node main`)**:
   ```mr
   public node main {
       set_engine(<engine_name>())
       set_vehicle(vehicle(mass: 1200 * units.kg))
       set_transmission(transmission())
   }
   main()
   ```

Refer to [references/engine_sim_dsl.md](./references/engine_sim_dsl.md) for full syntax reference.

---

## 3. Step-by-Step Generation Workflow

1. **Locate Target Path**:
   Save the engine script into `assets/engines/<manufacturer_or_category>/<engine_name>.mr` (e.g., `assets/engines/ford/shelby_gt350_voodoo.mr`).
2. **Generate the Complete Script**:
   Ensure all units (`units.inch`, `units.mm`, `units.lb`, `units.g`, `units.rpm`, `units.deg`, `units.cc`, `units.lb_ft`) are properly defined and imported.
3. **Configure Entry Point**:
   Update `assets/main.mr` to import the new engine script:
   ```mr
   import "engines/<category>/<engine_name>.mr"
   ```
4. **Test & Verify**:
   - Check syntax with a quick simulation launch or test command.
   - Inform the user how to test it in the simulator (`bin/engine-sim-app.exe` or `run_recorder.bat`).
