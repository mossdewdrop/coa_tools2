import bpy
import sys
import os
import json

# Add addon source to path
addon_path = r"D:\Github\coa_tools2"
if addon_path not in sys.path:
    sys.path.insert(0, addon_path)

# Ensure addon is registered
addon_name = "coa_tools2"
if addon_name not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=addon_name)

# Reload modules so latest code is used
import importlib
import coa_tools2
import coa_tools2.operators.exporter.export_dragonbones as export_dragonbones
importlib.reload(export_dragonbones)

# Open blend file
blend_path = r"D:\WorkProjects\对抗式移格仔RPG\场景对象\3D\Export\Item_gold_coin_db_2.blend"
print(f"Opening {blend_path}")
bpy.ops.wm.open_mainfile(filepath=blend_path)

# Find the sprite object
sprite_obj = None
for obj in bpy.context.scene.objects:
    if obj.type == "EMPTY" and hasattr(obj, "coa_tools2"):
        sprite_obj = obj
        print(f"Found sprite object: {obj.name}")
        break

if sprite_obj is None:
    # Try to find any MESH object that belongs to a sprite group
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH" and hasattr(obj, "coa_tools2"):
            if obj.parent and obj.parent.type == "EMPTY":
                sprite_obj = obj.parent
                print(f"Found sprite object via child: {sprite_obj.name}")
                break

if sprite_obj is None:
    print("ERROR: No sprite object found")
    sys.exit(1)

# Select the sprite object
bpy.ops.object.select_all(action='DESELECT')
sprite_obj.select_set(True)
bpy.context.view_layer.objects.active = sprite_obj

# Set export parameters
scene = bpy.context.scene
scene.coa_tools2.export_path = r"D:\WorkProjects\对抗式移格仔RPG\场景对象\3D\Export\Item_gold_coin_db_test"
scene.coa_tools2.project_name = "Item_gold_coin_test"
scene.coa_tools2.runtime_format = "DRAGONBONES"

# Ensure export dir exists
os.makedirs(scene.coa_tools2.export_path, exist_ok=True)

print("Executing export...")
try:
    bpy.ops.coa_tools2.export_dragon_bones()
    print("Export finished")
except Exception as e:
    print(f"Export error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Read exported JSON
json_path = os.path.join(scene.coa_tools2.export_path, "Item_gold_coin_test_ske.json")
if not os.path.exists(json_path):
    print(f"ERROR: JSON file not found at {json_path}")
    sys.exit(1)

with open(json_path, "r") as f:
    data = json.load(f)

# Check display data
armature = data["armature"][0]
skin_slots = armature["skin"][0]["slot"]
for slot in skin_slots:
    print(f"\nSlot: {slot['name']}")
    displays = slot.get("display", [])
    print(f"  Displays: {len(displays)}")
    vertices_list = []
    for i, d in enumerate(displays):
        verts = d.get("vertices", [])
        vertices_list.append(tuple(verts))
        print(f"  Display {i}: name={d['name']}, width={d.get('width')}, height={d.get('height')}, vertices_count={len(verts)}")

    if len(set(vertices_list)) == len(vertices_list):
        print("  SUCCESS: All displays have unique vertices!")
    else:
        print("  FAILURE: Some displays share the same vertices!")

print("\nTest complete")
