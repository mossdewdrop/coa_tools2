@tool
extends EditorContextMenuPlugin

func _popup_menu(paths: PackedStringArray) -> void:
	var has_json := false
	for path in paths:
		if path.get_extension().to_lower() == "json":
			has_json = true
			break
	if has_json:
		add_context_menu_item("Import COA", on_import_coa)

func on_import_coa(paths: PackedStringArray) -> void:
	var json_path := ""
	var tscn_path := ""
	
	for path in paths:
		var ext = path.get_extension().to_lower()
		if ext == "json":
			json_path = path
		elif ext == "tscn":
			tscn_path = path
			
	if json_path == "":
		printerr("COA Importer: No JSON config file selected!")
		return
		
	# If no existing .tscn file is selected, generate a .tscn file with the same name in the same directory
	if tscn_path == "":
		var base_dir = json_path.get_base_dir()
		var json_name = json_path.get_file().get_basename()
		tscn_path = base_dir.path_join(json_name + ".tscn")
		
	import_and_reconstruct(json_path, tscn_path)

func import_and_reconstruct(json_path: String, tscn_path: String) -> void:
	# 1. Read and parse JSON data
	if not FileAccess.file_exists(json_path):
		printerr("COA Importer: File not found: ", json_path)
		return
		
	var file = FileAccess.open(json_path, FileAccess.READ)
	var json_text = file.get_as_text()
	file.close()
	
	var json = JSON.new()
	var error = json.parse(json_text)
	if error != OK:
		printerr("COA Importer: JSON parse failed: ", json.get_error_message())
		return
		
	var data = json.data
	var root_name = data.get("name", "GeneratedScene")
	var nodes_data = data.get("nodes", [])
	
	# Automatically plan the atlas PNG path (e.g., res://sprites/Actor_Goblin_atlas.png)
	var json_base_dir = json_path.get_base_dir()
	var atlas_name = json_path.get_file().get_basename() + "_atlas.png"
	var atlas_path = json_base_dir.path_join(atlas_name)
	
	# 2. Collect all related individual sprites and resolve their paths
	var png_godot_paths: Array[String] = []
	var node_to_resolved_path: Dictionary = {} # Temporarily store each node's final resolved image path
	
	for node_data in nodes_data:
		var node_name = node_data.get("name", "Sprite")
		var raw_res_path = node_data.get("resource_path", "")
		
		# Smart path resolution
		var resolved_path = "res://" + raw_res_path
		if not ResourceLoader.exists(resolved_path):
			var relative_path = json_base_dir.path_join(raw_res_path)
			if ResourceLoader.exists(relative_path):
				resolved_path = relative_path
			else:
				var sprites_subfolder = json_base_dir.path_join("sprites").path_join(raw_res_path.get_file())
				if ResourceLoader.exists(sprites_subfolder):
					resolved_path = sprites_subfolder
				else:
					printerr("COA Importer: Unable to find resource: ", raw_res_path)
					continue
		
		node_to_resolved_path[node_name] = resolved_path
		if not png_godot_paths.has(resolved_path):
			png_godot_paths.append(resolved_path)
			
	# 3. Core step: auto-configure .import files for individual sprites, merge and reimport as TextureAtlas
	if png_godot_paths.size() > 0:
		auto_configure_and_reimport_atlas(png_godot_paths, atlas_path)
	else:
		printerr("COA Importer: No valid sprite resources found, aborting reconstruction.")
		return
		
	# 4. Build the scene (all sprites are now loaded as AtlasTexture)
	var root_node = Node2D.new()
	root_node.name = root_name
	
	# Sort by z-index (lowest z added first to the scene tree)
	nodes_data.sort_custom(func(a, b): return a.get("z", 0) < b.get("z", 0))
	
	# Name counter: JSON contains many duplicate node names (e.g., grass_min_24.png appears 8 times)
	# Without this, add_child would auto-rename duplicates to @Sprite2D@XXXXX
	var _name_counts: Dictionary = {}
	var _used_names: Dictionary = {}
	
	for node_data in nodes_data:
		var node_name = node_data.get("name", "Sprite")
		if not node_to_resolved_path.has(node_name):
			continue
			
		var resolved_path = node_to_resolved_path[node_name]
		var base_name = node_name.replace(".png", "")
		
		# Generate unique node name
		if not _name_counts.has(base_name):
			_name_counts[base_name] = 0
		_name_counts[base_name] += 1
		var clean_name = base_name
		if _name_counts[base_name] > 1:
			clean_name = base_name + "_" + str(_name_counts[base_name])
		
		# Collision prevention: if the generated name is already taken by another basename (e.g., the 2nd
		# grass_min_21 produces grass_min_21_2 but grass_min_21_2.png already exists), keep incrementing until a free name is found
		while _used_names.has(clean_name):
			_name_counts[base_name] += 1
			clean_name = base_name + "_" + str(_name_counts[base_name])
		_used_names[clean_name] = true
		
		# Load resource. Since auto-atlas packing was done earlier, the loaded resource will automatically be the corresponding AtlasTexture!
		# Use CACHE_MODE_IGNORE to bypass any stale resource cache
		var texture = ResourceLoader.load(resolved_path, "Texture2D", ResourceLoader.CACHE_MODE_IGNORE)
		if not texture:
			printerr("COA Importer: Failed to load redirected resource: ", resolved_path)
			continue
			
		var sprite = Sprite2D.new()
		sprite.name = clean_name
		sprite.texture = texture
		sprite.centered = false
		
		var pos = node_data.get("position", [0.0, 0.0])
		sprite.position = Vector2(pos[0], pos[1])
		
		var scale = node_data.get("scale", [1.0, 1.0])
		sprite.scale = Vector2(scale[0], scale[1])
		
		var rotation_deg = node_data.get("rotation", 0.0)
		sprite.rotation = deg_to_rad(rotation_deg)
		
		sprite.z_index = node_data.get("z", 0)
		
		root_node.add_child(sprite)
		sprite.owner = root_node
		
	# 5. Save the reconstructed scene file
	var packed_scene = PackedScene.new()
	var pack_result = packed_scene.pack(root_node)
	
	if pack_result == OK:
		var save_result = ResourceSaver.save(packed_scene, tscn_path)
		if save_result == OK:
			print("COA Importer: Scene reconstruction successful, saved to: ", tscn_path)
			EditorInterface.get_resource_filesystem().scan()
		else:
			printerr("COA Importer: Failed to save scene file: ", tscn_path)
	else:
		printerr("COA Importer: Failed to pack scene node tree.")
		
	root_node.queue_free()

# Core: configure individual sprites and reimport as a built-in TextureAtlas
func auto_configure_and_reimport_atlas(png_paths: Array[String], atlas_path: String) -> void:
	var files_to_reimport: PackedStringArray = []
	
	# ── Pre-create atlas placeholder file ────────────────────────────────────
	# Godot's reimport_files(), when processing a group, calls _reimport_file() on the atlas file
	# itself after group processing. If the atlas file is not in the filesystem cache, it errors
	# with "Can't find file during file reimport" and the atlas resource can't be registered,
	# causing AtlasTexture to fail finding the atlas reference when loading individual sprites later.
	if not FileAccess.file_exists(atlas_path):
		var placeholder = FileAccess.open(atlas_path, FileAccess.WRITE)
		if placeholder:
			placeholder.store_8(0)  # Minimal placeholder, will be overwritten by the real atlas during group processing
			placeholder.close()
		# Register in the editor filesystem cache so _reimport_file(atlas_path) can pass _find_file()
		EditorInterface.get_resource_filesystem().update_file(atlas_path)
	
	# ── Modify all individual sprites' .import files to point to the atlas ──
	for godot_res_path in png_paths:
		var import_path = godot_res_path + ".import"
		var import_config = ConfigFile.new()
		
		# If the existing .import file exists, read it first to preserve the original uid (crucial for Git collaboration and resource stability)
		if FileAccess.file_exists(import_path):
			import_config.load(import_path)
		
		# Rewrite remap key entries
		import_config.set_value("remap", "importer", "texture_atlas")
		import_config.set_value("remap", "type", "Texture2D")
		import_config.set_value("remap", "group_file", atlas_path) # Set the group file to point to the atlas
		import_config.set_value("remap", "valid", true)
		
		# Dependencies & source file
		import_config.set_value("deps", "source_file", godot_res_path)
		
		# Clear and write essential parameters for the TextureAtlas importer
		import_config.erase_section("params")
		import_config.set_value("params", "atlas_file", atlas_path)
		import_config.set_value("params", "import_mode", 0) # 0 = Region import mode
		import_config.set_value("params", "crop_to_region", true)
		import_config.set_value("params", "trim_alpha_border_from_region", true)
		
		var save_err = import_config.save(import_path)
		if save_err == OK:
			files_to_reimport.append(godot_res_path)
		else:
			printerr("COA Importer: Failed to save config file: ", import_path)
			
	if files_to_reimport.size() > 0:
		print("COA Importer: Detected unbound sprites. Using Godot's built-in packer to merge ", files_to_reimport.size(), " sprites into atlas: ", atlas_path)
		# Trigger reimport. This method is synchronous and blocking in the editor; it forces Godot's ResourceImporterTextureAtlas to pack the atlas and generate the image
		EditorInterface.get_resource_filesystem().reimport_files(files_to_reimport)
		print("COA Importer: Built-in atlas auto-packing and reimport completed.")
