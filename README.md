# Dead Simple Motion

**Dead Simple Motion** is a Blender add-on for quick animation motion setup. The goal is simple: select objects, choose a motion, adjust a few controls, and move on.

> Current status: **0.1.0 alpha / first architecture build**

## Included tools

### Rotate
- Local X / Y / Z continuous rotation
- Speed and stable per-object variation
- Key In / Key Out range controls
- Optional Object or Armature Bone attachment
- Multi-object apply

### Orbit
- Orbit around an Object or Armature Bone
- No target uses the 3D Cursor as the pivot
- XY / XZ / YZ planes
- Circle, Ellipse, Infinity, Square, and Sphere paths
- Normal, evenly Offset, or Random starting behavior
- Stable per-object speed/timing variation
- Multi-object apply
- Live target/bone updates

### FX
- Presets: Sci-Fi Drone, Space Debris, Engine Vibration, Breathing, Magic Hover, Alakazam!
- Float, Wobble, Scale Pulse, Bob, and Shake layers
- Amount / Speed master controls
- Deterministic per-object phase variation
- Multi-object apply

### Spawn / Looper
- **Spawn:** continuous travel, brief hide/reset, respawn, repeat
- **Looper:** back-and-forth motion
- X / Y / Z, Speed, Distance, Variation
- Multi-object traffic/debris setup

### Follow
- Follow an Object or Armature Bone by location
- Works with cameras and normal objects
- Preserves initial positional offset
- Live viewport updates
- Smoothness and organic drift
- Multi-object apply with stable variation

## Architecture

Dead Simple Motion is one Blender add-on with isolated feature modules:

```text
dead_simple_motion/
├── __init__.py
├── properties.py
├── ui.py
├── utils.py
├── handlers.py
├── rotate.py
├── orbit.py
├── fx.py
├── spawn.py
└── follow.py
```

Each feature owns its own apply/clear logic. The central handler only updates live-motion systems. The goal is to avoid the duplicate operators, stale systems, and broad destructive cleanup that accumulated in the previous prototype.

## Safety rules

- Clear operations target only Dead Simple Motion data.
- Location-driven tools refuse objects that already have location animation/drivers rather than deleting that work.
- FX refuses existing delta-transform animation/drivers rather than replacing it.
- Stable random values are stored on the object so variation does not reshuffle every frame.
- Orbit, Spawn, and Follow are treated as mutually exclusive primary location-motion systems.

## Install for testing

1. Download or clone this repository.
2. Zip the `dead_simple_motion` folder itself.
3. In Blender: **Edit → Preferences → Add-ons → Install from Disk**.
4. Choose the zip and enable **Dead Simple Motion**.
5. Open the 3D View sidebar and choose the **Dead Simple** tab.

## Blender target

The first build targets Blender **4.2+** APIs and is intended to be validated against current Blender 5.x releases before a public release.

## Development note

This repository is the clean rebuild of the earlier Dead Simple Animation Toolkit prototype. Version 0.1.0 is the first modular implementation and should be treated as an alpha until it receives real Blender runtime testing.
