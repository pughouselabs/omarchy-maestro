# Device images

Pictures are chosen per model, never per family, in this order
(`app/DeviceAssets.js`):

1. The model's own folder: the model name in lower case with dashes, for
   example `mx-master-3s` for "MX Master 3S" or `mx-anywhere-3` for
   "MX Anywhere 3".
2. A folder whose render has the same body:

   | Model | Folder |
   | --- | --- |
   | MX Master, MX Master 2S | `mx-master` (MX Master 2S render) |
   | MX Master 3, MX Master 3S, MX Master 4 | `mx-master-3s` |
   | MX Vertical | `mx-vertical` |

3. The neutral alpha silhouette, tinted with the current theme. Every other
   model (MX Anywhere, MX Ergo, unknown) uses it until it has its own folder;
   a model never shows another model's picture.

A folder counts only when it holds `hero.png` or `top.png`; otherwise the next
step applies. Pictures added while the app runs appear within a few seconds,
including a model's own folder added while a shared picture is shown.

Every folder has its own `hotspots.json` and `LICENSE.txt` in the format below.
Images require source and license credits. The MX Master 2S renders are licensed
CC BY-NC 4.0, separately from Maestro's MIT code.

```json
{
  "image": "hero.png",
  "image_dark": "hero-rim.png",
  "inset_image": "thumb.png",
  "top_down_image": "top-down.png",
  "credit": "Original model, creator, source URL and license",
  "credit_url": "https://link-to-the-original-model",
  "license": "CC BY-NC 4.0",
  "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
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
name is accepted instead of an array. Only controls the mouse reports get a
hotspot (an MX Vertical has no thumb wheel, so its thumb-wheel entry is never
shown); the MX Master's built-in horizontal scroll is the one exception.

Help names the model and the picture shown for it, and displays `credit`,
`credit_changes`, a link to `credit_url`, the `license` (linked to
`license_url`), and the Logitech disclaimer. The silhouette has its own credit. Device imagery is decorative; dots and labels expose control names
and assignments to the keyboard and accessibility tree.
