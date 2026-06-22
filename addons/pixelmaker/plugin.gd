@tool
@icon("res://addons/pixelmaker/plugin_icon.svg")
extends EditorPlugin

## PixelMaker EditorPlugin
##
## Manages the lifecycle of the bundled Python server and registers the dock UI.
## The Python server runs on 127.0.0.1:8765 so it doesn't clash with the
## standalone PixelMaker web app (which defaults to port 8000).

const PLUGIN_NAME   := "PixelMaker"
const SERVER_PORT   := 8765

# NOTE: No preload here — we resolve the path at runtime so the plugin works
# whether installed under addons/, plugins/, or any other folder.
var _dock: Control
var _server_pid: int = -1


func _enter_tree() -> void:
	# Derive dock.gd path relative to this script, works in any install folder.
	var dock_path: String = get_script().get_path().get_base_dir() + "/dock.gd"
	_dock = load(dock_path).new()
	_dock.name   = "PixelMaker"
	_dock.plugin = self
	add_control_to_dock(DOCK_SLOT_LEFT_BL, _dock)

	# Editor menu shortcuts
	add_tool_menu_item(PLUGIN_NAME + ": Start Server",  Callable(self, "_start_server"))
	add_tool_menu_item(PLUGIN_NAME + ": Stop Server",   Callable(self, "_stop_server"))
	add_tool_menu_item(PLUGIN_NAME + ": Open Web UI",   Callable(self, "_open_web_ui"))
	add_tool_menu_item(PLUGIN_NAME + ": Get Python 3.10+", Callable(self, "_open_python_download"))

	_start_server()


func _exit_tree() -> void:
	remove_tool_menu_item(PLUGIN_NAME + ": Start Server")
	remove_tool_menu_item(PLUGIN_NAME + ": Stop Server")
	remove_tool_menu_item(PLUGIN_NAME + ": Open Web UI")
	remove_tool_menu_item(PLUGIN_NAME + ": Get Python 3.10+")

	if is_instance_valid(_dock):
		remove_control_from_docks(_dock)
		_dock.queue_free()
		_dock = null

	_stop_server()


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

func _start_server() -> void:
	if _server_pid > 0:
		push_warning("[PixelMaker] Server already running (PID %d)." % _server_pid)
		return

	var python := _find_python()
	if python.is_empty():
		push_error("[PixelMaker] Python 3.10+ not found. Install from python.org.")
		if is_instance_valid(_dock) and _dock.has_method("notify_python_missing"):
			_dock.notify_python_missing()
		return

	var launcher := ProjectSettings.globalize_path(
		get_script().get_path().get_base_dir() + "/server/launcher.py"
	)
	if not FileAccess.file_exists(launcher):
		push_error("[PixelMaker] launcher.py not found at: " + launcher)
		return

	_server_pid = OS.create_process(python, [launcher])
	if _server_pid <= 0:
		push_error("[PixelMaker] Failed to start the Python server.")
	else:
		print("[PixelMaker] Server started (PID %d) on port %d." % [_server_pid, SERVER_PORT])
		# Notify dock so it can refresh status after a short delay
		if is_instance_valid(_dock) and _dock.has_method("schedule_status_check"):
			_dock.schedule_status_check()


func _stop_server() -> void:
	if _server_pid > 0:
		OS.kill(_server_pid)
		print("[PixelMaker] Server stopped (PID %d)." % _server_pid)
		_server_pid = -1
	else:
		print("[PixelMaker] No server process to stop.")


func _open_web_ui() -> void:
	OS.shell_open("http://127.0.0.1:%d" % SERVER_PORT)


func _open_python_download() -> void:
	OS.shell_open("https://www.python.org/downloads/")


func get_server_pid() -> int:
	return _server_pid


# ---------------------------------------------------------------------------
# Python discovery
# ---------------------------------------------------------------------------

func _find_python() -> String:
	var candidates: Array[String]
	if OS.get_name() == "Windows":
		candidates = ["python", "python3", "py"]
	else:
		candidates = ["python3", "python"]

	for candidate in candidates:
		var output: Array = []
		var code := OS.execute(candidate, ["--version"], output, true, false)
		if code == 0:
			# Validate 3.10+ — reject Python 2 or old 3.x
			var ver: String = (output[0] if output.size() > 0 else "").strip_edges()
			var nums := ver.trim_prefix("Python ").split(".")
			if nums.size() >= 2:
				var major := int(nums[0])
				var minor := int(nums[1])
				if major > 3 or (major == 3 and minor >= 10):
					return candidate

	# Fallback: common install paths on Windows
	if OS.get_name() == "Windows":
		var win_paths: Array[String] = [
			"C:/Python313/python.exe",
			"C:/Python312/python.exe",
			"C:/Python311/python.exe",
			"C:/Python310/python.exe",
		]
		for p in win_paths:
			if FileAccess.file_exists(p):
				return p

	return ""
