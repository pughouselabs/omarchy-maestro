# Device images

Each family has a folder: `mx-master`, `mx-anywhere`, `mx-vertical`, or `mx-ergo`.
Images require source and license credits. The MX Master 2S renders are licensed
CC BY-NC 4.0, separately from Maestro's MIT code. Other families and the empty
state use the neutral alpha silhouette, tinted with the current theme.

```json
{
  "image": "hero.png",
  "image_dark": "hero-rim.png",
  "inset_image": "thumb.png",
  "top_down_image": "top-down.png",
  "credit": "Original model, creator, source URL and license",
  "credit_changes": "Description of changes to the original model",
  "hotspots": [
    {"name": "middle", "label": "Middle click", "x": 0.301, "y": 0.26, "side": "left"}
  ],
  "inset_hotspots": [
    {"name": "thumb_wheel", "x": 0.593, "y": 0.412}
  ]
}
```

The hero is 2000 × 1500, the thumb detail 1200 × 1200, and the top-down view
900 × 1200. Transparent PNGs include contact shadows. The dark theme uses the
rim-lit hero. `top.png` remains a fallback for older asset sets. Metadata and
images reload without changing application code.

Coordinates are fractions (0 to 1) of the entire image, including transparent
padding. Recalibrate them whenever a camera or crop changes. Controls are
numbered by reading order: the left column, then the right column. Controls
on the same horizontal strip are arranged in left-to-right order before the
columns are numbered. Numbering is independent of window size.

The 168-pixel circular inset shows the thumb wheel, Forward, and Back from the side.
The circular alpha is baked into the PNG, so the UI draws it directly without a rectangular clip or a background-colored corner mask.
Inset hotspot coordinates refer to that final PNG. Close dot targets are
separated by at least 40 pixels, with short tethers to the calibrated locations.
Gesture stays on the main hero. Below 1100 pixels the inset is hidden.
Narrow editor views use six separate targets
with tethers. Each dot is one keyboard stop; callouts are clickable without
adding duplicate tab stops.

Names match engine controls: `gesture`, `back`, `forward`, `thumb_wheel`,
`middle`, `mode_shift` (`wheel_mode` is also accepted). A map keyed by control
name is accepted instead of an array. Only reported controls are enabled.

Help displays `credit` and `credit_changes`, plus the license and Logitech
disclaimer. Device imagery is decorative; dots and labels expose control names
and assignments to the keyboard and accessibility tree.
