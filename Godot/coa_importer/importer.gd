@tool
extends EditorPlugin

const SLOT_SCRIPT_SRC = """@tool
extends Node2D

@export var slot: int = 0:
	set(val):
		slot = val
		_update_visibility()

func _ready():
	_update_visibility()

func _update_visibility():
	var children = get_children()
	for i in range(children.size()):
		var child = children[i]
		if child is CanvasItem:
			child.visible = (i == slot)
"""

var open_importer = null

var import_window_res = preload("import_dialog.tscn")
var import_window = null
var warning_dialog = null
var btn_load_json = null
var btn_dst_file = null
var src_dialog = null
var dst_dialog = null
var src_scene = null
var dst_scene = null

var label_src_scene = null
var label_dst_scene = null

var json_info = null
var bone_count = 0
var sprite_count = 0

var check_merge = null

var json_data = {}
var json_path = ""
var file_dst_path = ""

var dir
var root_node

var slot_script: GDScript = null


func _init():
	print("PLUGIN INIT")


func _enter_tree():
	# 初始化 SLOT 挂载脚本
	slot_script = GDScript.new()
	slot_script.source_code = SLOT_SCRIPT_SRC
	slot_script.reload()

	import_window = import_window_res.instantiate()
	import_window.confirmed.connect(_create_imported_scene)
	
	# 先将主窗口添加至编辑器控制台
	get_editor_interface().get_base_control().add_child(import_window)
	import_window.get_ok_button().set_text("Import")
	
	json_info = import_window.get_node("Content/json_info/text")
	check_merge = import_window.get_node("Content/check_merge_scenes")
	
	label_dst_scene = import_window.get_node("Content/path_destination_file/label")
	label_src_scene = import_window.get_node("Content/path_source_file/label")
	
	warning_dialog = import_window.get_node("warning_dialog")
	
	# 初始化源文件选择对话框，并将其挂载为 import_window 的子节点，解决独占冲突
	src_dialog = EditorFileDialog.new()
	src_dialog.access = EditorFileDialog.ACCESS_FILESYSTEM
	src_dialog.file_mode = EditorFileDialog.FILE_MODE_OPEN_FILE
	src_dialog.add_filter("*.json", "JSON Files")
	src_dialog.file_selected.connect(_src_dialog_confirm)
	import_window.add_child(src_dialog)
	
	# 初始化目标保存对话框，同样挂载为 import_window 的子节点
	dst_dialog = EditorFileDialog.new()
	dst_dialog.access = EditorFileDialog.ACCESS_RESOURCES
	dst_dialog.file_mode = EditorFileDialog.FILE_MODE_SAVE_FILE
	dst_dialog.add_filter("*.xml", "XML Files")
	dst_dialog.add_filter("*.tscn", "TSCN Scenes")
	dst_dialog.add_filter("*.scn", "SCN Scenes")
	dst_dialog.file_selected.connect(_dst_dialog_confirm)
	import_window.add_child(dst_dialog)
	
	btn_load_json = import_window.get_node("Content/button_source")
	btn_load_json.pressed.connect(_open_src_dialog)
	
	btn_dst_file = import_window.get_node("Content/button_destination")
	btn_dst_file.pressed.connect(_open_dst_dialog)
	
	open_importer = Button.new()
	open_importer.set_text("Import COA File")
	open_importer.pressed.connect(_open_importer)
	add_control_to_container(CONTAINER_CANVAS_EDITOR_MENU, open_importer)
	
	
func _exit_tree():
	if open_importer:
		remove_control_from_container(CONTAINER_CANVAS_EDITOR_MENU, open_importer)
		open_importer.free()
		open_importer = null
	
	if import_window:
		import_window.free()
		import_window = null
		
	slot_script = null


### 打开导入主窗口并居中
func _open_importer():
	var pos = get_window().get_size() * 0.5 - import_window.size * 0.5
	import_window.position = pos

	json_info.clear()
	import_window.popup_centered()
	
	if json_path != "":
		_src_dialog_confirm(json_path)
	if file_dst_path != "":	
		_dst_dialog_confirm(file_dst_path)


### 打开源文件对话框
func _open_src_dialog():
	json_info.mouse_filter = Control.MOUSE_FILTER_IGNORE
	src_dialog.popup_centered_ratio()
	src_scene = null
	src_dialog.set_current_dir(src_dialog.get_current_dir())


### 加载并解析 JSON 源文件
func _src_dialog_confirm(path):
	json_info.clear()
	json_info.mouse_filter = Control.MOUSE_FILTER_STOP
	json_path = path
	
	if FileAccess.file_exists(json_path):
		var json = FileAccess.open(json_path, FileAccess.READ)
		if json:
			var test_json_conv = JSON.new()
			if test_json_conv.parse(json.get_as_text()) == OK:
				json_data = test_json_conv.get_data()
			json.close()
			
			label_src_scene.set_text(json_path)
	
	dir = DirAccess.open("res://")
	
	if src_scene != null:
		src_scene.free()
	src_scene = Node2D.new()
	src_scene.name = sanitize_node_name(json_data["name"])
	write_log(json_info, "Json Import File Information")
	json_info.newline()
	
	if "changelog" in json_data:
		write_log(json_info, "#### Changelog ####")
		for log_msg in json_data["changelog"]:
			write_log(json_info, str(log_msg))
		json_info.newline()
		
	write_log(json_info, "#### Node Information ####")
	write_log(json_info, str("Name: ", json_data["name"]))
	
	### 导入节点并记录
	sprite_count = 0
	bone_count = 0
	create_nodes(json_data["nodes"], src_scene, src_scene, false)
	write_log(json_info, str("Sprite2D Count: ", sprite_count), 0)
	write_log(json_info, str("Bone Count:   ", bone_count), 0)
	
	### 导入动画
	if "animations" in json_data:
		import_animations(json_data["animations"], src_scene)
	

### 打开目标文件保存对话框
func _open_dst_dialog():
	json_info.mouse_filter = Control.MOUSE_FILTER_IGNORE
	dst_dialog.popup_centered_ratio()
	dst_scene = null
	dst_dialog.set_current_dir(dst_dialog.get_current_dir())


### 确认目标保存路径
func _dst_dialog_confirm(path):
	json_info.mouse_filter = Control.MOUSE_FILTER_STOP

	file_dst_path = path
	label_dst_scene.set_text(file_dst_path)
	if FileAccess.file_exists(file_dst_path):
		var dst_scene_res = load(file_dst_path)
		dst_scene = dst_scene_res.instantiate()


### 保存节点场景
func save_packed_scene(scene):
	if scene.has_node("AnimationPlayer"):
		scene.get_node("AnimationPlayer").clear_caches()
	
	# 打包场景并保存
	var outfile = PackedScene.new()
	outfile.pack(scene)
	ResourceSaver.save(outfile, file_dst_path)


### 执行 JSON 导入
func _create_imported_scene():
	if file_dst_path != "" and json_path != "":
		if src_scene != null:
			src_scene.free()
		if dst_scene != null and check_merge.is_pressed():	
			src_scene = Node2D.new()
			src_scene.replace_by(dst_scene)
		else:
			src_scene = Node2D.new()
		src_scene.name = sanitize_node_name(json_data["name"])
		
		### 生成所有节点
		create_nodes(json_data["nodes"], src_scene, src_scene)
		
		### 导入所有动画
		if "animations" in json_data:
			import_animations(json_data["animations"], src_scene)
		
		### 场景合并或直接保存
		if dst_scene != null and check_merge.is_pressed():
			save_packed_scene(merge_scenes(src_scene, dst_scene))
			import_window.hide()
		else:
			save_packed_scene(src_scene)
			import_window.hide()
			
		show_warning_dialog.call_deferred("Info", "Import complete, please reload Scene.")
	else:
		show_warning_dialog.call_deferred("Warning", "Please select valid paths.")


### 递归获取子节点
func get_child_recursive(node, child_list=[]):
	for child in node.get_children():
		child_list.append(child)
		if child.get_child_count() > 0:
			get_child_recursive(child, child_list)
	return child_list


### 替换节点属性及动画
func replace_node(node, replace_with):
	var node_class = node.get_class()
	if node_class == "Node2D" or node_class == "Sprite2D":
		node.position = replace_with.position
		node.rotation = replace_with.rotation
		node.scale = replace_with.scale
		node.modulate.a = replace_with.modulate.a
		node.z_index = replace_with.z_index
		if node.get_script() != null and "slot" in node:
			node.set("slot", replace_with.get("slot"))
		if node_class == "Sprite2D":
			node.texture = replace_with.texture
			node.hframes = replace_with.hframes
			node.vframes = replace_with.vframes
			node.frame = replace_with.frame
			node.centered = replace_with.centered
			node.offset = replace_with.offset
	elif node_class == "AnimationPlayer":
		# 获取或创建默认动画库 ""
		var library: AnimationLibrary
		if node.has_animation_library(""):
			library = node.get_animation_library("")
		else:
			library = AnimationLibrary.new()
			node.add_animation_library("", library)
			
		var replace_library: AnimationLibrary
		if replace_with.has_animation_library(""):
			replace_library = replace_with.get_animation_library("")
		else:
			replace_library = AnimationLibrary.new()
			replace_with.add_animation_library("", replace_library)

		### 删除无用动画
		var anim_list = library.get_animation_list()
		for anim in anim_list:
			if !(replace_library.has_animation(anim)) and anim in node.get_meta_list():
				node.set_meta(anim, false)
				library.remove_animation(anim)
				node.clear_caches()
	
		### 更新和添加新动画
		anim_list = replace_library.get_animation_list()
		for anim in anim_list:
			if library.has_animation(anim):
				library.get_animation(anim).clear()
				node.clear_caches()
				library.remove_animation(anim)
			node.clear_caches()
			library.add_animation(anim, replace_library.get_animation(anim))


### 获取列表中的父节点
func get_parent_nodes(list):
	var parent_list = []
	for node in list:
		if node.get_parent() != null:
			if !(node.get_parent() in list):
				parent_list.append(node)
	return parent_list


### 递归添加子节点
func add_node_recursive(node, owner, parent):
	if node.get_parent() == null:
		parent.add_child(node)
	node.owner = owner
	if node.get_child_count() > 0:
		for child in node.get_children():
			add_node_recursive(child, owner, node)
			

### 合并源场景与目标场景
func merge_scenes(src_scene, dst_scene):
	### 删除不存在的、由 Blender 导入的旧节点
	var node_dst_scene = get_child_recursive(dst_scene)
	var to_be_deleted = []
	for node in node_dst_scene:
		if node != null:
			var node_path = dst_scene.get_path_to(node)
			if !(src_scene.has_node(node_path)) and node.has_meta("imported_from_blender"):
				to_be_deleted.append(node)
	for node in get_parent_nodes(to_be_deleted):
		node.free()
			
	### 更新或添加新节点
	var node_src_scene = get_child_recursive(src_scene)
	for node in node_src_scene:
		var node_path = src_scene.get_path_to(node)
		if dst_scene.has_node(node_path):
			var node2 = dst_scene.get_node(node_path)
			replace_node(node2, node)
		else:
			var new_nodes = node.duplicate()
			var parent_node = dst_scene.get_node(src_scene.get_path_to(node.get_parent()))
			add_node_recursive(new_nodes, dst_scene, parent_node)
	return dst_scene
		

### 记录日志信息
func write_log(text_field, msg, indent=0, line_break=false):
	text_field.push_indent(indent)
	if line_break:
		text_field.newline()
	text_field.add_text(msg)


### 显示警告框
func show_warning_dialog(title="", msg=""):
	if msg != "":
		warning_dialog.dialog_text = msg
	if title != "":
		warning_dialog.title = title
	warning_dialog.popup_centered()


### 递归判断节点是否有骨骼子节点
func has_bone_child(node):
	if "children" in node:
		for item in node["children"]:
			if item["type"] == "BONE":
				return true
			if "children" in item:
				if has_bone_child(item):
					return true
	return false


### 规范化节点名称以匹配 Godot 4 规则（滤除点号并替换为下划线）
func sanitize_node_name(name: String) -> String:
	return name.validate_node_name()


### 将旧格式属性动画路径映射到 Godot 4 标准命名并转译非法的节点名称
func fix_track_path(key: String) -> String:
	var parts = key.split(":")
	if parts.size() != 2:
		return key
	
	var node_path = parts[0]
	var property = parts[1]
	
	# 分割节点路径并逐一净化其各段名称
	var path_components = node_path.split("/")
	for idx in range(path_components.size()):
		path_components[idx] = sanitize_node_name(path_components[idx])
	node_path = "/".join(path_components)
	
	match property:
		"transform/pos":
			property = "position"
		"transform/rot":
			property = "rotation_degrees"
		"transform/scale":
			property = "scale"
		"visibility/opacity":
			property = "modulate:a"
		"z/z":
			property = "z_index"
		"slot":
			property = "slot"
		"frame":
			property = "frame"
		"modulate":
			property = "modulate"
			
	return node_path + ":" + property


### 导入动画至 AnimationPlayer 节点
func import_animations(animations, owner):
	var anim_player = AnimationPlayer.new()
	owner.add_child(anim_player)
	anim_player.owner = owner
	anim_player.name = "AnimationPlayer"
	
	write_log(json_info, str("Animation Count: ", animations.size()))
	if animations.size() > 0:
		write_log(json_info, str("#### Animations ####"), 0, true)
		
	# Godot 4 中，必须将动画添加到一个 AnimationLibrary，此处使用默认库 ""
	var anim_library = AnimationLibrary.new()
	anim_player.add_animation_library("", anim_library)
	
	for anim in animations:
		anim_player.clear_caches()
		write_log(json_info, str("> ", anim["name"], ":   length - ", anim["length"], "    fps - ", anim["fps"]))
		var anim_data = Animation.new()
		anim_data.loop_mode = Animation.LOOP_LINEAR # 替换旧的 set_loop(true)
		anim_data.set_length(anim["length"])
		for key in anim["keyframes"]:
			var track = anim["keyframes"][key]
			var idx = anim_data.add_track(Animation.TYPE_VALUE)
			
			# 映射旧路径至 Godot 4 标准
			var fixed_key = fix_track_path(key)
			anim_data.track_set_path(idx, fixed_key)
			
			for time in track:
				var value = track[time]["value"]
				if typeof(value) == TYPE_ARRAY:
					if key.find("pos") != -1:
						anim_data.track_insert_key(idx, float(time), Vector2(value[0], value[1]))
					elif key.find("scale") != -1:
						anim_data.track_insert_key(idx, float(time), Vector2(value[0], value[1]))
					elif key.find("modulate") != -1:
						anim_data.track_insert_key(idx, float(time), Color(value[0], value[1], value[2], 1.0))
				elif typeof(value) == TYPE_FLOAT or typeof(value) == TYPE_INT:
					if key.find("rot") != -1:
						anim_data.track_insert_key(idx, float(time), rad_to_deg(value))
					else:
						anim_data.track_insert_key(idx, float(time), value)

				if key.find(":frame") != -1 or key.find(":z/z") != -1 or key.find(":slot") != -1:
					anim_data.track_set_interpolation_type(idx, Animation.INTERPOLATION_NEAREST)
				else:
					anim_data.track_set_interpolation_type(idx, Animation.INTERPOLATION_LINEAR)
		anim_library.add_animation(anim["name"], anim_data)
		anim_player.set_meta(anim["name"], true)
		anim_player.clear_caches()
	


### 递归创建 Sprite 和 Bone 节点结构
func create_nodes(nodes, parent, subparent, copy_images=true, i=0):
	var dir2 = DirAccess.open("res://")
	for node in nodes:
		# 规避 JSON 中多余平铺（Flat）的节点副本造成的在根部二次创建的冗余 Bug
		if i == 0 and "/" in node.get("node_path", ""):
			continue
			
		var new_node = null
		var offset = Vector2(0,0)
		if "offset" in node:
			offset = Vector2(node["offset"][0], node["offset"][1])
		
		# 1. 处理 BONE 节点
		if node["type"] == "BONE":
			bone_count += 1
			new_node = Node2D.new()
			new_node.set_meta("imported_from_blender", true)
			new_node.name = sanitize_node_name(node["name"])
			new_node.position = Vector2(node["position"][0], node["position"][1])
			new_node.rotation = node["rotation"]
			new_node.scale = Vector2(node["scale"][0], node["scale"][1])	
			new_node.z_index = node["z"]
			subparent.add_child(new_node)
			new_node.owner = parent
			
			### 处理骨骼连接及绘制
			if new_node.get_parent() != null and node["bone_connected"]:
				new_node.set_meta("_edit_bone_", true)
			if !(has_bone_child(node)) or node["draw_bone"]:
				var draw_bone = Node2D.new()
				draw_bone.set_meta("_edit_bone_", true)
				draw_bone.name = sanitize_node_name(str(node["name"], "_tail"))
				draw_bone.position = Vector2(node["position_tip"][0], -node["position_tip"][1])
				draw_bone.hide()
				
				new_node.add_child(draw_bone)
				draw_bone.owner = parent

		# 2. 处理 SLOT 节点（映射为 Node2D）
		elif node["type"] == "SLOT":
			new_node = Node2D.new()
			new_node.set_meta("imported_from_blender", true)
			new_node.name = sanitize_node_name(node["name"])
			new_node.position = Vector2(node["position"][0], node["position"][1])
			new_node.rotation = node["rotation"]
			new_node.scale = Vector2(node["scale"][0], node["scale"][1])	
			new_node.z_index = node["z"]
			if "opacity" in node:
				new_node.modulate.a = node["opacity"]
			
			# 为 SLOT 动态挂载处理脚本以响应动画
			if slot_script:
				new_node.set_script(slot_script)
				new_node.set("slot", 0)

			subparent.add_child(new_node)
			new_node.owner = parent

		# 3. 处理 SPRITE 节点
		elif node["type"] == "SPRITE":
			sprite_count += 1
			### 复制图片到目标文件夹
			new_node = Sprite2D.new()
			if copy_images:
				if json_path != "":
					var sprite_dir_path = file_dst_path.get_base_dir()
					
					if !(dir.dir_exists(str(sprite_dir_path, "/sprites"))):
						dir.make_dir(str(sprite_dir_path, "/sprites"))
					if dir.file_exists(str(json_path.get_base_dir(), "/", node["resource_path"])):
						var _src = str(json_path.get_base_dir(), "/", node["resource_path"])
						var _dst = str(sprite_dir_path, "/", node["resource_path"])
						
						# 仅在文件不存在时执行复制，防止频繁锁写和触发重新导入引起 Safe Save Failed
						if !dir.file_exists(_dst):
							dir.copy(_src, _dst)
						
						### 设置 Sprite 纹理
						new_node.texture = load(str(sprite_dir_path, "/", node["resource_path"]))
		
			new_node.set_meta("imported_from_blender", true)
			new_node.name = sanitize_node_name(node["name"])
			new_node.hframes = node["tiles_x"]
			new_node.vframes = node["tiles_y"]
			
			# 安全区间映射，规避 Sprite 帧溢出报错
			var max_frames = node["tiles_x"] * node["tiles_y"]
			if node["frame_index"] < max_frames and node["frame_index"] >= 0:
				new_node.frame = node["frame_index"]
			else:
				new_node.frame = 0
				
			new_node.centered = false
			new_node.offset = Vector2(node["pivot_offset"][0], node["pivot_offset"][1])
			new_node.position = Vector2(node["position"][0] + offset[0], node["position"][1] + offset[1])
			new_node.rotation = node["rotation"]
			new_node.scale = Vector2(node["scale"][0], node["scale"][1])
			new_node.z_index = node["z"]
			
			subparent.add_child(new_node)
			new_node.owner = parent
		
		# 4. 递归处理子树节点（防空指针回退机制）
		if "children" in node and node["children"].size() > 0:
			var next_parent = new_node if new_node != null else subparent
			create_nodes(node["children"], parent, next_parent, copy_images, i + 1)
