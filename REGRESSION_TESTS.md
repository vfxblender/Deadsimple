# Dead Simple Motion 0.3.2 Regression Checklist

Run this checklist in Blender 4.2+ after any motion-system change. Repeat the camera/render tests in the newest supported Blender release as well.

## Ownership / cleanup
- Apply each DSM tool to an object that also has unrelated animation on a different property. Clear the DSM tool and verify unrelated animation remains.
- Clear All must remove only DSM-owned data.
- Re-apply Rotate, Orbit, Spawn/Looper, Follow, and FX and verify per-object variation does not reshuffle unless the seed is intentionally changed.

## Rotate
- Fresh cube: Apply Rotate and confirm the cube spins.
- After Apply, confirm both cube and `DSM_ROT_CTRL_*` are selectable and the cube is active.
- Move and tilt the Rotate control; confirm the local spin follows the control orientation.
- Set Key In and Key Out at different current frames; confirm the existing rig updates immediately.
- Bake Rotation; confirm two linear rotation keys are created at the range endpoints.
- Clear Rotate; confirm only unchanged DSM bake points are removed and the control is deleted.
- Add unrelated rotation animation before Apply; confirm DSM refuses to overwrite it.

## Orbit
- Circle, Ellipse, Infinity, Square: verify expected path and current placement behavior.
- Sphere: verify true 3D precessing orbit and Axis Speed.
- Orientation None: preserve object rotation.
- Face Direction: model points along its direction of travel.
- Face Target: the chosen forward side stays toward the pivot like a moon/satellite.
- Camera: create `DSM_ORBIT_FOCUS_*` at the pivot; camera looks at it; moving focus reframes the shot.
- Move an object/bone orbit target and verify orbit/focus follows without duplicate-handler jitter.
- Existing location/required rotation animation must block Apply instead of being overwritten.

## Spawn / Looper
- Spawn: object travels, hides at reset seam, and respawns.
- Looper: object travels A → B → A with easing.
- Move/rotate `DSM_SPAWN_CTRL_*`; verify the whole path moves/rotates.
- Move the animated object/camera after Apply; verify manual local offset is preserved on top of procedural motion.
- Camera: `DSM_LOOP_FOCUS_*` is selectable and camera looks at it while looping.
- Render an animation and compare slider position/focus behavior with viewport playback.
- Existing location animation must block Apply; camera rotation animation must also block camera Looper Apply.

## Follow
- Object target: follower preserves initial world-space offset.
- Bone target with Drift = 0: rotating the bone in place must not orbit/swing the follower.
- Delay = 0: immediate location follow.
- Delay > 0: visible trailing response based on elapsed time rather than callback count.
- Drag target in viewport and play/render animation; verify no feedback loop or runaway motion.
- Existing location animation must block Apply.

## FX
- Test every preset: Sci-Fi Drone, Space Debris, Engine Vibration, Breathing, Magic Hover, Alakazam!, Handheld Camera, Floating UI, Engine Idle, Heavy Machinery, Underwater, Drunk Camera, Micro Jitter, Hovercraft.
- Multi-select objects and verify variation stays deterministic across clear/reapply.
- Existing delta-transform animation/drivers must block Apply instead of being overwritten.
- Clear FX must restore saved delta transforms and remove only DSM-owned drivers.

## Handlers / reload
- Enable addon, reload scripts/module, and confirm exactly one DSM handler exists in each of frame-change, depsgraph-update, and render-pre.
- Scrub, play, drag targets/controls, and render. Confirm no recursive update loop or accumulating slowdown.
- Save/reopen a test file and repeat viewport/render comparison.

## UI
- Tabs remain: Rotate | Orbit | Spawn | Follow | FX.
- Every tool uses consistent Apply/Clear placement.
- Advanced controls remain collapsed by default.
- Follow Delay is visible without opening Advanced.
- No development build label is shown in the normal panel.
