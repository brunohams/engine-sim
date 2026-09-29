# Musical Tuning Guide for Engine Simulator

When recording songs or sampling notes from Engine Simulator, this guide provides the formulas and reference tables mapping musical pitches to engine RPMs.

---

## 1. The Fundamental Pitch Formula

For a **4-stroke** engine:
$$\text{Frequency } (f) = \frac{\text{RPM}}{60} \times \frac{N_{\text{cylinders}}}{2}$$

To calculate the required **RPM** for a specific frequency:
$$\text{RPM} = \frac{f \times 60}{\frac{N_{\text{cylinders}}}{2}} = \frac{120 \times f}{N_{\text{cylinders}}}$$

For a **Rotary** (Wankel) or **2-stroke** engine:
$$\text{Frequency } (f) = \frac{\text{RPM}}{60} \times N_{\text{rotors/cylinders}}$$

---

## 2. Note to RPM Master Table (Standard A4 = 440 Hz)

| Musical Note | Frequency ($f$) | 4-Cylinder | 6-Cylinder | 8-Cylinder (V8) | 10-Cylinder (V10) | 12-Cylinder (V12) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **C2** | 65.41 Hz | 1,962 RPM | 1,308 RPM | 981 RPM | 785 RPM | 654 RPM |
| **D2** | 73.42 Hz | 2,203 RPM | 1,468 RPM | 1,101 RPM | 881 RPM | 734 RPM |
| **E2** | 82.41 Hz | 2,472 RPM | 1,648 RPM | 1,236 RPM | 989 RPM | 824 RPM |
| **G2** | 98.00 Hz | 2,940 RPM | 1,960 RPM | 1,470 RPM | 1,176 RPM | 980 RPM |
| **A2** | 110.00 Hz | 3,300 RPM | 2,200 RPM | 1,650 RPM | 1,320 RPM | 1,100 RPM |
| **C3** | 130.81 Hz | 3,924 RPM | 2,616 RPM | 1,962 RPM | 1,570 RPM | 1,308 RPM |
| **D3** | 146.83 Hz | 4,405 RPM | 2,937 RPM | 2,202 RPM | 1,762 RPM | 1,468 RPM |
| **E3** | 164.81 Hz | 4,944 RPM | 3,296 RPM | 2,472 RPM | 1,978 RPM | 1,648 RPM |
| **G3** | 196.00 Hz | 5,880 RPM | 3,920 RPM | 2,940 RPM | 2,352 RPM | 1,960 RPM |
| **A3** | 220.00 Hz | 6,600 RPM | 4,400 RPM | 3,300 RPM | 2,640 RPM | 2,200 RPM |
| **C4 (Mid C)** | 261.63 Hz | 7,849 RPM | 5,233 RPM | 3,924 RPM | 3,140 RPM | 2,616 RPM |
| **D4** | 293.66 Hz | 8,810 RPM | 5,873 RPM | 4,405 RPM | 3,524 RPM | 2,937 RPM |
| **E4** | 329.63 Hz | 9,889 RPM | 6,593 RPM | 4,944 RPM | 3,956 RPM | 3,296 RPM |
| **G4** | 392.00 Hz | 11,760 RPM | 7,840 RPM | 5,880 RPM | 4,704 RPM | 3,920 RPM |
| **A4 (Concert)**| 440.00 Hz | 13,200 RPM | 8,800 RPM | 6,600 RPM | 5,280 RPM | 4,400 RPM |
| **C5** | 523.25 Hz | — | 10,465 RPM | 7,849 RPM | 6,279 RPM | 5,233 RPM |
| **E5** | 659.25 Hz | — | 13,185 RPM | 9,889 RPM | 7,911 RPM | 6,593 RPM |
| **A5** | 880.00 Hz | — | — | 13,200 RPM | 10,560 RPM | 8,800 RPM |

---

## 3. Musical Response Tuning in `.mr`

1. **Snappy Keyboard-like Response**:
   ```mr
   flywheel_mass: 2.0 * units.lb,
   moment_of_inertia: 0.015,
   friction_torque: 3.0 * units.lb_ft
   ```
2. **Rock-Solid Pitch (Eliminating Flutter)**:
   ```mr
   fuel: fuel(
       max_burning_efficiency: 1.0,
       burning_efficiency_randomness: 0.0
   ),
   jitter: 0.02,
   noise: 0.05
   ```
3. **Hard Rev-Limiter Note Lock**:
   Set `rev_limit` in the distributor to the exact target note's RPM. Holding 100% throttle (`R`) locks that pitch with zero oscillation.
