from pathlib import Path
import bpy
import os
from mathutils import Matrix, Vector

work = Path(os.environ["PAPERCUT_WORK"])
check = work / "evidence"
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=str(check / "装配.glb"))
pieces = [obj for obj in scene.objects if obj.type == 'MESH']
assert len(pieces) == 8
tray = next(obj for obj in pieces if "托框" in obj.name)
import json
verified = json.loads((check/"verification.json").read_text(encoding="utf8"))
tray_width = 192.8 if len(verified["plates"]) == 8 else 194.0
factor = tray_width / max(tray.dimensions)
for obj in pieces:
    obj.matrix_world = Matrix.Scale(factor, 4) @ obj.matrix_world
    obj.name = "GEN_" + obj.name
bpy.context.view_layer.update()
assert abs(max(tray.dimensions)-tray_width) < .01
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = .001
scene.unit_settings.length_unit = 'MILLIMETERS'
bpy.ops.object.camera_add(location=(238,-430,191))
camera = bpy.context.object
camera.rotation_euler = (Vector((93,-3,91))-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.type = 'ORTHO'
camera.data.ortho_scale = 232
camera.data.clip_end = 5000
scene.camera = camera
scene.render.engine = 'BLENDER_WORKBENCH'
shading = scene.display.shading
shading.light = 'STUDIO'
shading.color_type = 'VERTEX'
shading.show_cavity = True
shading.cavity_type = 'BOTH'
shading.show_shadows = True
shading.background_type = 'WORLD'
scene.world = bpy.data.worlds.new("Studio")
scene.world.color = (.13,.13,.13)
scene.view_settings.view_transform = 'Standard'
scene.render.resolution_x = scene.render.resolution_y = 1100
scene.render.resolution_percentage = 100
scene.render.filepath = str(check / "装盒斜视.png")
bpy.ops.render.render(write_still=True)
