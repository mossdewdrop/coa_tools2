@tool
extends EditorPlugin

var _ctx_plugin: EditorContextMenuPlugin

func _enter_tree():
	# Load the EditorContextMenuPlugin script and register it to the filesystem context menu
	var ctx_script = preload("res://addons/static_coa_importer/context_menu_impl.gd")
	_ctx_plugin = ctx_script.new()
	add_context_menu_plugin(EditorContextMenuPlugin.CONTEXT_SLOT_FILESYSTEM, _ctx_plugin)
	print("Static COA Importer plugin loaded - right-click a JSON file to import a COA scene")

func _exit_tree():
	if is_instance_valid(_ctx_plugin):
		remove_context_menu_plugin(_ctx_plugin)
		_ctx_plugin = null
