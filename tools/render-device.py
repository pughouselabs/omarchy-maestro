"""Render device images for app/assets/devices from a downloaded glTF model.

Run inside Blender (no add-ons needed):

    VIEWS="hero,-0.6,-1,1.3" blender -b --factory-startup -P tools/render-device.py -- \
        model.glb outdir 1600

VIEWS is a ";"-separated list of name,x,y,z camera directions (pointing from the model
toward the camera). Optional: LENS (mm, default 85), SAMPLES (default 256),
EXPOSURE (default 0.45). Output is a transparent PNG per view; crop it tightly and
record control positions in hotspots.json (see app/assets/devices/README.md).
"""

import os
import sys

import bpy
import mathutils

model, out_dir, resolution = sys.argv[sys.argv.index("--") + 1 :][:3]
resolution = int(resolution)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=model)
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
corners = [o.matrix_world @ mathutils.Vector(c) for o in meshes for c in o.bound_box]
center = sum(corners, mathutils.Vector()) / len(corners)
size = max((p - center).length for p in corners)

# Hide status-light glow materials so the shot stays neutral.
for obj in meshes:
    if any(m and "NEON" in m.name for m in obj.data.materials):
        obj.hide_render = True

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = int(os.environ.get("SAMPLES", "256"))
scene.cycles.use_denoising = True
scene.render.resolution_x = scene.render.resolution_y = resolution
scene.render.film_transparent = True
transforms = [
    v.identifier for v in scene.view_settings.bl_rna.properties["view_transform"].enum_items
]
scene.view_settings.view_transform = "AgX" if "AgX" in transforms else "Filmic"
scene.view_settings.exposure = float(os.environ.get("EXPOSURE", "0.45"))

world = bpy.data.worlds.new("studio")
scene.world = world
world.use_nodes = True
background = world.node_tree.nodes["Background"]
background.inputs[0].default_value = (0.8, 0.82, 0.86, 1)
background.inputs[1].default_value = 0.35


def add_light(name, direction, energy, light_size):
    light = bpy.data.lights.new(name, "AREA")
    light.energy = energy
    light.size = light_size
    obj = bpy.data.objects.new(name, light)
    scene.collection.objects.link(obj)
    obj.location = center + mathutils.Vector(direction).normalized() * size * 4
    obj.rotation_euler = (center - obj.location).to_track_quat("-Z", "Y").to_euler()


scale = size * size
add_light("key", (-0.6, -1.0, 1.4), 120 * scale, size * 2.5)
add_light("fill", (1.0, -0.3, 0.6), 40 * scale, size * 3)
add_light("rim", (1.2, 0.2, 0.7), 160 * scale, size * 1.5)
add_light("rim2", (0.2, 1.2, 0.5), 90 * scale, size * 1.5)
add_light("top", (0, 0, 1), 30 * scale, size * 3)

camera = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
scene.collection.objects.link(camera)
scene.camera = camera
camera.data.lens = float(os.environ.get("LENS", "85"))

for spec in os.environ.get("VIEWS", "hero,-0.6,-1,1.3").split(";"):
    name, x, y, z = spec.split(",")
    direction = mathutils.Vector((float(x), float(y), float(z))).normalized()
    camera.location = center + direction * size * 5.2
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Z").to_euler()
    scene.render.filepath = f"{out_dir}/{name}.png"
    bpy.ops.render.render(write_still=True)
