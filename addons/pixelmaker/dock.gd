## PixelMaker editor dock.
##
## Builds the full panel UI programmatically (no .tscn needed) and communicates
## with the bundled Python server via HTTP on 127.0.0.1:8765.
##
## Tabs:
##   Sprite     — text → AI sprite  |  image upload → local pixelation
##   Background — text → AI background (with optional seamless tile)
##   Animate    — sprite upload → walk / idle / jump / attack animation
##   Isometric  — text → 2:1 isometric tileset with Godot 4 TileSet export
@tool
extends Control

const SERVER_URL := "http://127.0.0.1:8765"

## Set by plugin.gd after instantiation.
var plugin: EditorPlugin = null

# ── busy / state ─────────────────────────────────────────────────────────────
var _busy            := false
var _pending_action  := ""
# Sprite-tab upload (image → pixelate)
var _sp_upload_bytes : PackedByteArray
var _sp_upload_fname := "image.png"
# Animate-tab upload (sprite → animation)
var _an_upload_bytes : PackedByteArray
var _an_upload_fname := "sprite.png"

# ── stored results ────────────────────────────────────────────────────────────
var _sprite_png      : PackedByteArray
var _preview_png     : PackedByteArray
var _bg_png          : PackedByteArray
var _tile_png        : PackedByteArray
var _sheet_png       : PackedByteArray
var _gif_png         : PackedByteArray
var _iso_zip         : PackedByteArray
var _iso_zip_name    := "iso.zip"
var _iso_prev_bytes  : PackedByteArray

# ── HTTP nodes ────────────────────────────────────────────────────────────────
var _http       : HTTPRequest   # generation requests
var _hlth_http  : HTTPRequest   # health-check (separate to avoid conflicts)
var _usage_http : HTTPRequest   # usage check (separate to avoid conflicts)

# ── UI refs: shared ───────────────────────────────────────────────────────────
var _status_lbl   : Label
var _api_key      : LineEdit
var _key_indicator: Label
var _key_field_row: HBoxContainer
var _tabs         : TabContainer
var _log_lbl      : Label

# ── UI refs: Sprite tab ───────────────────────────────────────────────────────
var _sp_mode        : OptionButton
var _sp_prompt_box  : VBoxContainer
var _sp_prompt      : TextEdit
var _sp_upload_box  : HBoxContainer
var _sp_upload_lbl  : Label
var _sp_size        : OptionButton
var _sp_palette     : OptionButton
var _sp_colors      : SpinBox
var _sp_rm_bg       : CheckBox
var _sp_fill        : CheckBox
var _sp_gen_btn     : Button
var _sp_preview     : TextureRect
var _sp_save_spr    : Button
var _sp_save_pre    : Button

# ── UI refs: Background tab ───────────────────────────────────────────────────
var _bg_prompt      : TextEdit
var _bg_width       : SpinBox
var _bg_height      : SpinBox
var _bg_palette     : OptionButton
var _bg_colors      : SpinBox
var _bg_pixel_sz    : OptionButton
var _bg_tileable    : CheckBox
var _bg_gen_btn     : Button
var _bg_preview     : TextureRect
var _bg_save_bg     : Button
var _bg_save_tile   : Button

# ── UI refs: Animate tab ──────────────────────────────────────────────────────
var _an_upload_lbl  : Label
var _an_action      : OptionButton
var _an_frames_row  : HBoxContainer
var _an_frames      : OptionButton
var _an_fps         : SpinBox
var _an_gen_btn     : Button
var _an_preview     : TextureRect
var _an_save_sheet  : Button
var _an_save_gif    : Button

# ── UI refs: Isometric tab ────────────────────────────────────────────────────
var _iso_prompt     : TextEdit
var _iso_side       : TextEdit
var _iso_width      : OptionButton
var _iso_palette    : OptionButton
var _iso_colors     : SpinBox
var _iso_variants   : Array[CheckBox] = []
var _iso_rim        : CheckBox
var _iso_name       : LineEdit
var _iso_gen_btn    : Button
var _iso_preview    : TextureRect
var _iso_save_zip   : Button


# =============================================================================
# Lifecycle
# =============================================================================

func _ready() -> void:
	_build_ui()
	_setup_http()
	# Load persisted API key from editor settings.
	var _es := EditorInterface.get_editor_settings()
	if _es.has_setting("pixelmaker/api_key"):
		_api_key.text = str(_es.get_setting("pixelmaker/api_key"))
		_update_key_indicator()
	# Give the server a moment to start before the first health check.
	_log_msg("Plugin loaded. Waiting for server…")
	get_tree().create_timer(3.0).timeout.connect(_check_server_status)


func _setup_http() -> void:
	_http = HTTPRequest.new()
	_http.timeout = 120.0
	add_child(_http)
	_http.request_completed.connect(_on_request_completed)

	_hlth_http = HTTPRequest.new()
	_hlth_http.timeout = 5.0
	add_child(_hlth_http)
	_hlth_http.request_completed.connect(_on_health_completed)

	_usage_http = HTTPRequest.new()
	_usage_http.timeout = 15.0
	add_child(_usage_http)
	_usage_http.request_completed.connect(_on_usage_completed)


## Called by plugin.gd after the server process is created.
func schedule_status_check() -> void:
	get_tree().create_timer(4.0).timeout.connect(_check_server_status)


# =============================================================================
# UI construction helpers
# =============================================================================

func _scrolled_vbox(tab_name: String) -> VBoxContainer:
	var scroll := ScrollContainer.new()
	scroll.name = tab_name
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.size_flags_vertical   = Control.SIZE_EXPAND_FILL
	_tabs.add_child(scroll)
	var vb := VBoxContainer.new()
	vb.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	vb.add_theme_constant_override("separation", 4)
	scroll.add_child(vb)
	return vb


func _lbl(parent: Control, text: String) -> void:
	var l := Label.new()
	l.text = text
	parent.add_child(l)


func _row(parent: VBoxContainer, label_text: String, min_lbl_w: int = 72) -> HBoxContainer:
	var row := HBoxContainer.new()
	row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	parent.add_child(row)
	var lbl := Label.new()
	lbl.text = label_text
	lbl.custom_minimum_size.x = min_lbl_w
	row.add_child(lbl)
	return row


func _option(parent: Control, items: Array) -> OptionButton:
	var ob := OptionButton.new()
	ob.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	for item in items:
		ob.add_item(str(item))
	parent.add_child(ob)
	return ob


func _spinbox(parent: Control, lo: float, hi: float, val: float) -> SpinBox:
	var sb := SpinBox.new()
	sb.min_value = lo
	sb.max_value = hi
	sb.value     = val
	sb.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	parent.add_child(sb)
	return sb


func _preview(parent: VBoxContainer, min_h: int = 160) -> TextureRect:
	var tr := TextureRect.new()
	# 3 = EXPAND_FIT_WIDTH_PROPORTIONAL (works on all Godot 4.x, constant guaranteed ≥4.2)
	tr.expand_mode   = 3
	tr.stretch_mode  = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	tr.custom_minimum_size = Vector2(0, min_h)
	tr.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	parent.add_child(tr)
	return tr


func _gen_btn(parent: VBoxContainer, text: String, cb: Callable) -> Button:
	var btn := Button.new()
	btn.text = text
	btn.pressed.connect(cb)
	parent.add_child(btn)
	return btn


func _save_row(parent: VBoxContainer, labels: Array) -> Array:
	var row := HBoxContainer.new()
	row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	parent.add_child(row)
	var btns := []
	for lbl in labels:
		var btn := Button.new()
		btn.text = str(lbl)
		btn.disabled = true
		btn.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(btn)
		btns.append(btn)
	return btns


# =============================================================================
# Build full UI
# =============================================================================

func _build_ui() -> void:
	# The dock is a plain Control; its child needs FULL_RECT anchors to fill it.
	# (size_flags only work inside Container parents — anchors work in any Control.)
	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 4)
	add_child(root)
	root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	# ─── Status row ───────────────────────────────────────────────────────────
	var srow := HBoxContainer.new()
	root.add_child(srow)

	_status_lbl = Label.new()
	_status_lbl.text = "● Server: checking…"
	_status_lbl.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	srow.add_child(_status_lbl)

	var rfbtn := Button.new()
	rfbtn.text         = "↺"
	rfbtn.flat         = true
	rfbtn.tooltip_text = "Check server status"
	rfbtn.pressed.connect(_check_server_status)
	srow.add_child(rfbtn)

	# ─── API key (collapsible) ───────────────────────────────────────────────
	var krow := HBoxContainer.new()
	root.add_child(krow)

	var ktoggle := Button.new()
	ktoggle.text                   = "[Key] API Key"
	ktoggle.flat                   = true
	ktoggle.toggle_mode            = true
	ktoggle.size_flags_horizontal  = Control.SIZE_EXPAND_FILL
	ktoggle.tooltip_text           = "Show / hide API key field"
	krow.add_child(ktoggle)

	_key_indicator = Label.new()
	_key_indicator.text         = " \u25CB"
	_key_indicator.tooltip_text = "No key set"
	krow.add_child(_key_indicator)

	var kusage := Button.new()
	kusage.text         = "Usage"
	kusage.flat         = true
	kusage.tooltip_text = "Check this month's OpenAI spend"
	kusage.pressed.connect(_check_usage)
	krow.add_child(kusage)

	# Key input — hidden until the toggle is pressed
	_key_field_row = HBoxContainer.new()
	_key_field_row.visible = false
	root.add_child(_key_field_row)

	_api_key = LineEdit.new()
	_api_key.placeholder_text        = "sk-… (stored in editor settings, never shown)"
	_api_key.secret                  = true
	_api_key.size_flags_horizontal   = Control.SIZE_EXPAND_FILL
	_key_field_row.add_child(_api_key)

	ktoggle.toggled.connect(func(on: bool): _key_field_row.visible = on)
	_api_key.text_changed.connect(_on_api_key_changed)

	# ─── Tabs ─────────────────────────────────────────────────────────────────
	_tabs = TabContainer.new()
	_tabs.size_flags_vertical = Control.SIZE_EXPAND_FILL
	root.add_child(_tabs)

	_build_sprite_tab()
	_build_background_tab()
	_build_animate_tab()
	_build_isometric_tab()

	# ─── Log ──────────────────────────────────────────────────────────────────
	root.add_child(HSeparator.new())
	_log_lbl = Label.new()
	_log_lbl.text = "Ready."
	_log_lbl.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_log_lbl.custom_minimum_size.y = 40
	root.add_child(_log_lbl)


# ── Sprite tab ────────────────────────────────────────────────────────────────

func _build_sprite_tab() -> void:
	var vb := _scrolled_vbox("Sprite")

	var mr := _row(vb, "Mode:", 48)
	_sp_mode = _option(mr, ["From Text (AI)", "From Image (local)"])
	_sp_mode.item_selected.connect(_on_sprite_mode_changed)

	# Text mode section
	_sp_prompt_box = VBoxContainer.new()
	vb.add_child(_sp_prompt_box)
	_lbl(_sp_prompt_box, "Prompt:")
	_sp_prompt = TextEdit.new()
	_sp_prompt.placeholder_text = "e.g. a cute blue wizard"
	_sp_prompt.custom_minimum_size.y = 48
	_sp_prompt.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_sp_prompt_box.add_child(_sp_prompt)

	# Upload mode section (hidden by default)
	_sp_upload_box = HBoxContainer.new()
	_sp_upload_box.visible = false
	vb.add_child(_sp_upload_box)
	var upbtn := Button.new()
	upbtn.text = "Choose Image…"
	upbtn.pressed.connect(_open_sprite_upload)
	_sp_upload_box.add_child(upbtn)
	_sp_upload_lbl = Label.new()
	_sp_upload_lbl.text = "(no file)"
	_sp_upload_lbl.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_sp_upload_box.add_child(_sp_upload_lbl)

	# Options
	var szr := _row(vb, "Size:")
	_sp_size = _option(szr, [16, 32, 64, 128])
	_sp_size.select(1)  # default: 32

	var par := _row(vb, "Palette:")
	_sp_palette = _option(par, ["adaptive", "nes", "gameboy", "cga", "pico8"])

	var clr := _row(vb, "Colors:")
	_sp_colors = _spinbox(clr, 2, 256, 16)

	_sp_rm_bg = CheckBox.new()
	_sp_rm_bg.text = "Remove Background"
	_sp_rm_bg.button_pressed = true
	vb.add_child(_sp_rm_bg)

	_sp_fill = CheckBox.new()
	_sp_fill.text = "Fill Frame"
	_sp_fill.button_pressed = true
	vb.add_child(_sp_fill)

	_sp_gen_btn = _gen_btn(vb, "Generate Sprite", _on_generate_sprite)

	vb.add_child(HSeparator.new())
	_sp_preview = _preview(vb)

	var saves := _save_row(vb, ["Save Sprite PNG", "Save Preview PNG"])
	_sp_save_spr = saves[0]
	_sp_save_pre = saves[1]
	_sp_save_spr.pressed.connect(func(): _save_dialog(_sprite_png,  "sprite.png",    "assets/sprites"))
	_sp_save_pre.pressed.connect(func(): _save_dialog(_preview_png, "preview.png",   "assets/sprites"))


func _on_sprite_mode_changed(idx: int) -> void:
	_sp_prompt_box.visible = (idx == 0)
	_sp_upload_box.visible = (idx == 1)


# ── Background tab ────────────────────────────────────────────────────────────

func _build_background_tab() -> void:
	var vb := _scrolled_vbox("Background")

	_lbl(vb, "Prompt:")
	_bg_prompt = TextEdit.new()
	_bg_prompt.placeholder_text = "e.g. forest at dusk"
	_bg_prompt.custom_minimum_size.y = 48
	_bg_prompt.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	vb.add_child(_bg_prompt)

	var wr := _row(vb, "Width:")
	_bg_width = _spinbox(wr, 256, 3840, 1280)

	var hr := _row(vb, "Height:")
	_bg_height = _spinbox(hr, 256, 3840, 720)

	var par := _row(vb, "Palette:")
	_bg_palette = _option(par, ["adaptive", "nes", "gameboy", "cga", "pico8"])

	var clr := _row(vb, "Colors:")
	_bg_colors = _spinbox(clr, 2, 256, 24)

	var pxr := _row(vb, "Px Size:")
	_bg_pixel_sz = _option(pxr, [4, 6, 8, 12, 16])
	_bg_pixel_sz.select(2)  # default: 8

	_bg_tileable = CheckBox.new()
	_bg_tileable.text = "Tileable (seamless horizontal repeat)"
	_bg_tileable.button_pressed = true
	vb.add_child(_bg_tileable)

	_bg_gen_btn = _gen_btn(vb, "Generate Background", _on_generate_background)

	vb.add_child(HSeparator.new())
	_bg_preview = _preview(vb)

	var saves := _save_row(vb, ["Save Background", "Save Tile"])
	_bg_save_bg   = saves[0]
	_bg_save_tile = saves[1]
	_bg_save_bg.pressed.connect(func(): _save_dialog(_bg_png,    "background.png",      "assets/backgrounds"))
	_bg_save_tile.pressed.connect(func(): _save_dialog(_tile_png, "background_tile.png", "assets/backgrounds"))


# ── Animate tab ───────────────────────────────────────────────────────────────

func _build_animate_tab() -> void:
	var vb := _scrolled_vbox("Animate")

	_lbl(vb, "Upload a pixel sprite to animate:")
	var uprow := HBoxContainer.new()
	vb.add_child(uprow)
	var upbtn := Button.new()
	upbtn.text = "Choose Sprite…"
	upbtn.pressed.connect(_open_animate_upload)
	uprow.add_child(upbtn)
	_an_upload_lbl = Label.new()
	_an_upload_lbl.text = "(no file)"
	_an_upload_lbl.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	uprow.add_child(_an_upload_lbl)

	var actr := _row(vb, "Action:")
	_an_action = _option(actr, ["walk", "idle", "jump", "attack"])
	_an_action.item_selected.connect(_on_action_changed)

	_an_frames_row = HBoxContainer.new()
	vb.add_child(_an_frames_row)
	var fl := Label.new()
	fl.text = "Frames:"
	fl.custom_minimum_size.x = 72
	_an_frames_row.add_child(fl)
	_an_frames = _option(_an_frames_row, [4, 6])
	_an_frames.select(1)  # default: 6

	var fpsr := _row(vb, "FPS (ms):")
	_an_fps = _spinbox(fpsr, 40, 500, 120)

	_an_gen_btn = _gen_btn(vb, "Generate Animation", _on_generate_animation)

	vb.add_child(HSeparator.new())
	_an_preview = _preview(vb)

	var saves := _save_row(vb, ["Save Sprite Sheet", "Save GIF"])
	_an_save_sheet = saves[0]
	_an_save_gif   = saves[1]
	_an_save_sheet.pressed.connect(func(): _save_dialog(_sheet_png, "spritesheet.png", "assets/animations"))
	_an_save_gif.pressed.connect(func():   _save_dialog(_gif_png,   "animation.gif",   "assets/animations"))


func _on_action_changed(idx: int) -> void:
	# "Frames" option only matters for walk
	_an_frames_row.visible = (idx == 0)


# ── Isometric tab ─────────────────────────────────────────────────────────────

func _build_isometric_tab() -> void:
	var vb := _scrolled_vbox("Isometric")

	_lbl(vb, "Top Texture Prompt:")
	_iso_prompt = TextEdit.new()
	_iso_prompt.placeholder_text = "e.g. grass"
	_iso_prompt.custom_minimum_size.y = 40
	_iso_prompt.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	vb.add_child(_iso_prompt)

	_lbl(vb, "Side Texture Prompt (optional):")
	_iso_side = TextEdit.new()
	_iso_side.placeholder_text = "e.g. stone bricks  (blank = auto-shade from top)"
	_iso_side.custom_minimum_size.y = 40
	_iso_side.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	vb.add_child(_iso_side)

	var wr := _row(vb, "Tile Width:")
	_iso_width = _option(wr, [32, 64, 128])
	_iso_width.select(1)  # default: 64

	var par := _row(vb, "Palette:")
	_iso_palette = _option(par, ["adaptive", "nes", "gameboy", "cga", "pico8"])

	var clr := _row(vb, "Colors:")
	_iso_colors = _spinbox(clr, 2, 256, 16)

	_lbl(vb, "Height Variants:")
	var vrow := HBoxContainer.new()
	vb.add_child(vrow)
	for vname in ["full", "half", "quarter", "slab"]:
		var cb := CheckBox.new()
		cb.text = vname
		cb.button_pressed = true
		vrow.add_child(cb)
		_iso_variants.append(cb)

	_iso_rim = CheckBox.new()
	_iso_rim.text = "Material Rim (top lip over side)"
	_iso_rim.button_pressed = true
	vb.add_child(_iso_rim)

	var nr := _row(vb, "Name:")
	_iso_name = LineEdit.new()
	_iso_name.text = "iso"
	_iso_name.placeholder_text = "asset folder / file prefix"
	_iso_name.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	nr.add_child(_iso_name)

	_iso_gen_btn = _gen_btn(vb, "Generate Isometric Tiles", _on_generate_isometric)

	vb.add_child(HSeparator.new())
	_iso_preview = _preview(vb)

	var saves := _save_row(vb, ["Save ZIP (Godot 4 TileSet + atlas)"])
	_iso_save_zip = saves[0]
	_iso_save_zip.pressed.connect(func(): _save_dialog(_iso_zip, _iso_zip_name, "assets/isometric"))


# =============================================================================
# File dialogs
# =============================================================================

func _open_sprite_upload() -> void:
	_open_load_dlg(
		["*.png ; PNG", "*.jpg *.jpeg ; JPEG", "*.webp ; WebP"],
		_on_sprite_file_selected
	)


func _open_animate_upload() -> void:
	_open_load_dlg(
		["*.png ; PNG Images"],
		_on_animate_file_selected
	)


func _on_sprite_file_selected(path: String) -> void:
	var file := FileAccess.open(path, FileAccess.READ)
	if not file:
		_log_msg("Cannot open: " + path)
		return
	_sp_upload_bytes = file.get_buffer(file.get_length())
	file.close()
	_sp_upload_fname = path.get_file()
	_sp_upload_lbl.text = _sp_upload_fname
	if not _sp_upload_bytes.is_empty():
		var img := Image.new()
		if img.load_png_from_buffer(_sp_upload_bytes) == OK:
			_sp_preview.texture = ImageTexture.create_from_image(img)
	_log_msg("Loaded: %s (%d bytes)" % [_sp_upload_fname, _sp_upload_bytes.size()])


func _on_animate_file_selected(path: String) -> void:
	var file := FileAccess.open(path, FileAccess.READ)
	if not file:
		_log_msg("Cannot open: " + path)
		return
	_an_upload_bytes = file.get_buffer(file.get_length())
	file.close()
	_an_upload_fname = path.get_file()
	_an_upload_lbl.text = _an_upload_fname
	_log_msg("Loaded: %s (%d bytes)" % [_an_upload_fname, _an_upload_bytes.size()])


func _open_load_dlg(filters: Array, cb: Callable) -> void:
	var dlg := FileDialog.new()
	dlg.file_mode = FileDialog.FILE_MODE_OPEN_FILE
	dlg.access    = FileDialog.ACCESS_FILESYSTEM
	for f in filters:
		dlg.add_filter(f)
	dlg.file_selected.connect(cb)
	dlg.file_selected.connect(func(_p): dlg.queue_free())
	dlg.canceled.connect(func(): dlg.queue_free())
	add_child(dlg)
	dlg.popup_centered(Vector2i(800, 600))


func _save_dialog(data: PackedByteArray, default_name: String, subfolder: String = "assets") -> void:
	if data.is_empty():
		_log_msg("Nothing to save yet — generate first.")
		return
	var dlg := FileDialog.new()
	dlg.file_mode    = FileDialog.FILE_MODE_SAVE_FILE
	dlg.access       = FileDialog.ACCESS_RESOURCES
	var start_dir := "res://" + subfolder
	if not DirAccess.dir_exists_absolute(ProjectSettings.globalize_path(start_dir)):
		start_dir = "res://"
	dlg.current_dir  = start_dir
	dlg.current_file = default_name
	if default_name.ends_with(".png"):
		dlg.add_filter("*.png ; PNG Images")
	elif default_name.ends_with(".gif"):
		dlg.add_filter("*.gif ; GIF Animations")
	elif default_name.ends_with(".zip"):
		dlg.add_filter("*.zip ; ZIP Archives")
	dlg.file_selected.connect(func(p: String): _write_file(p, data))
	dlg.canceled.connect(func(): dlg.queue_free())
	add_child(dlg)
	dlg.popup_centered(Vector2i(800, 600))


func _write_file(path: String, data: PackedByteArray) -> void:
	# Resolve res:// to absolute path for FileAccess (required on some platforms).
	var abs_path := ProjectSettings.globalize_path(path) if path.begins_with("res://") else path
	# Ensure parent directory exists.
	var dir := abs_path.get_base_dir()
	if not DirAccess.dir_exists_absolute(dir):
		DirAccess.make_dir_recursive_absolute(dir)
	var file := FileAccess.open(abs_path, FileAccess.WRITE)
	if not file:
		_log_msg("Cannot write: " + abs_path)
		return
	file.store_buffer(data)
	file.close()
	_log_msg("Saved → " + path)
	# Always rescan so Godot picks up the new asset immediately.
	EditorInterface.get_resource_filesystem().scan()


# =============================================================================
# HTTP helpers
# =============================================================================

func _form_body(fields: Dictionary) -> PackedByteArray:
	var parts: Array[String] = []
	for key in fields:
		parts.append(str(key).uri_encode() + "=" + str(fields[key]).uri_encode())
	return "&".join(parts).to_utf8_buffer()


func _multipart_body(fields: Dictionary,
		file_key: String, file_bytes: PackedByteArray, filename: String) -> Array:
	## Returns [body: PackedByteArray, content_type_header: String]
	var boundary := "PixelMakerGodot1234567890"
	var crlf     := "\r\n"
	var body     := PackedByteArray()

	for key in fields:
		var part  := "--" + boundary + crlf
		part += "Content-Disposition: form-data; name=\"" + str(key) + "\"" + crlf + crlf
		part += str(fields[key]) + crlf
		body.append_array(part.to_utf8_buffer())

	if not file_key.is_empty() and not file_bytes.is_empty():
		var fh  := "--" + boundary + crlf
		fh += "Content-Disposition: form-data; name=\"" + file_key + "\"; filename=\"" + filename + "\"" + crlf
		fh += "Content-Type: image/png" + crlf + crlf
		body.append_array(fh.to_utf8_buffer())
		body.append_array(file_bytes)
		body.append_array((crlf + "--" + boundary + "--" + crlf).to_utf8_buffer())
	else:
		body.append_array(("--" + boundary + "--" + crlf).to_utf8_buffer())

	return [body, "Content-Type: multipart/form-data; boundary=" + boundary]


func _post_form(endpoint: String, fields: Dictionary, action: String) -> void:
	if _busy:
		_log_msg("Busy — wait for the current request to finish.")
		return
	_start_request(action)
	var body    := _form_body(fields)
	var headers := PackedStringArray(["Content-Type: application/x-www-form-urlencoded"])
	var err     := _http.request_raw(SERVER_URL + endpoint, headers, HTTPClient.METHOD_POST, body)
	if err != OK:
		_log_msg("HTTP error %d — is the server running?" % err)
		_end_request()


func _post_multipart(endpoint: String, fields: Dictionary,
		file_key: String, file_bytes: PackedByteArray,
		filename: String, action: String) -> void:
	if _busy:
		_log_msg("Busy — wait for the current request to finish.")
		return
	_start_request(action)
	var mp      := _multipart_body(fields, file_key, file_bytes, filename)
	var headers := PackedStringArray([mp[1]])
	var err     := _http.request_raw(SERVER_URL + endpoint, headers, HTTPClient.METHOD_POST, mp[0])
	if err != OK:
		_log_msg("HTTP error %d — is the server running?" % err)
		_end_request()


func _start_request(action: String) -> void:
	_busy           = true
	_pending_action = action
	_set_gen_btns(false)
	_log_msg("Generating… (this may take a minute for AI features)")


func _end_request() -> void:
	_busy           = false
	_pending_action = ""
	_set_gen_btns(true)


# =============================================================================
# Generation triggers
# =============================================================================

func _on_generate_sprite() -> void:
	var sizes    := [16, 32, 64, 128]
	var palettes := ["adaptive", "nes", "gameboy", "cga", "pico8"]
	var sz:  int    = sizes[_sp_size.selected]
	var pal: String = palettes[_sp_palette.selected]
	var cols     := int(_sp_colors.value)
	var rm_bg    := _bool_str(_sp_rm_bg.button_pressed)
	var fill     := _bool_str(_sp_fill.button_pressed)
	var api_key  := _api_key.text.strip_edges()

	if _sp_mode.selected == 0:
		# AI text → sprite
		var prompt := _sp_prompt.text.strip_edges()
		if prompt.is_empty():
			_log_msg("Please enter a prompt.")
			return
		_post_form("/api/generate", {
			"prompt": prompt, "size": sz, "palette": pal,
			"colors": cols, "remove_bg": rm_bg, "fill": fill, "api_key": api_key,
		}, "sprite")
	else:
		# Local upload → sprite
		if _sp_upload_bytes.is_empty():
			_log_msg("Please choose an image file first.")
			return
		_post_multipart("/api/convert", {
			"size": sz, "palette": pal, "colors": cols,
			"remove_bg": rm_bg, "fill": fill,
		}, "file", _sp_upload_bytes, _sp_upload_fname, "sprite")


func _on_generate_background() -> void:
	var prompt := _bg_prompt.text.strip_edges()
	if prompt.is_empty():
		_log_msg("Please enter a prompt.")
		return
	var px_opts := [4, 6, 8, 12, 16]
	var palettes := ["adaptive", "nes", "gameboy", "cga", "pico8"]
	_post_form("/api/background", {
		"prompt":     prompt,
		"width":      int(_bg_width.value),
		"height":     int(_bg_height.value),
		"palette":    palettes[_bg_palette.selected],
		"colors":     int(_bg_colors.value),
		"pixel_size": px_opts[_bg_pixel_sz.selected],
		"tileable":   _bool_str(_bg_tileable.button_pressed),
		"tile_div":   "1",
		"api_key":    _api_key.text.strip_edges(),
	}, "background")


func _on_generate_animation() -> void:
	if _an_upload_bytes.is_empty():
		_log_msg("Please upload a sprite first.")
		return
	var actions    := ["walk", "idle", "jump", "attack"]
	var frame_opts := [4, 6]
	_post_multipart("/api/walk", {
		"action":  actions[_an_action.selected],
		"frames":  frame_opts[_an_frames.selected],
		"fps_ms":  int(_an_fps.value),
	}, "file", _an_upload_bytes, _an_upload_fname, "animation")


func _on_generate_isometric() -> void:
	var prompt := _iso_prompt.text.strip_edges()
	if prompt.is_empty():
		_log_msg("Please enter a top texture prompt.")
		return
	var variant_names := ["full", "half", "quarter", "slab"]
	var chosen: Array[String] = []
	for i in range(_iso_variants.size()):
		if _iso_variants[i].button_pressed:
			chosen.append(variant_names[i])
	if chosen.is_empty():
		_log_msg("Select at least one height variant.")
		return
	var widths   := [32, 64, 128]
	var palettes := ["adaptive", "nes", "gameboy", "cga", "pico8"]
	var iso_name := _iso_name.text.strip_edges()
	if iso_name.is_empty():
		iso_name = "iso"
	_post_form("/api/isometric", {
		"prompt":      prompt,
		"side_prompt": _iso_side.text.strip_edges(),
		"width":       widths[_iso_width.selected],
		"palette":     palettes[_iso_palette.selected],
		"colors":      int(_iso_colors.value),
		"variants":    ",".join(chosen),
		"rim":         _bool_str(_iso_rim.button_pressed),
		"name":        iso_name,
		"api_key":     _api_key.text.strip_edges(),
	}, "isometric")


# =============================================================================
# HTTP response handlers
# =============================================================================

func _on_request_completed(result: int, response_code: int,
		_hdrs: PackedStringArray, body: PackedByteArray) -> void:
	var action := _pending_action
	_end_request()

	if result != HTTPRequest.RESULT_SUCCESS:
		_log_msg("Network error (%d). Is the server running?" % result)
		return
	if response_code != 200:
		var msg := body.get_string_from_utf8().left(300)
		_log_msg("Server error %d: %s" % [response_code, msg])
		return

	var json := JSON.new()
	if json.parse(body.get_string_from_utf8()) != OK:
		_log_msg("Could not parse server response.")
		return
	var data: Dictionary = json.get_data()

	match action:
		"sprite":     _handle_sprite(data)
		"background": _handle_background(data)
		"animation":  _handle_animation(data)
		"isometric":  _handle_isometric(data)


func _handle_sprite(data: Dictionary) -> void:
	if data.has("sprite_png"):
		_sprite_png  = Marshalls.base64_to_raw(data["sprite_png"])
	if data.has("preview_png"):
		_preview_png = Marshalls.base64_to_raw(data["preview_png"])
	var tex_src := _preview_png if not _preview_png.is_empty() else _sprite_png
	if not tex_src.is_empty():
		var img := Image.new()
		if img.load_png_from_buffer(tex_src) == OK:
			_sp_preview.texture = ImageTexture.create_from_image(img)
	_sp_save_spr.disabled = _sprite_png.is_empty()
	_sp_save_pre.disabled = _preview_png.is_empty()
	_log_msg("Sprite done! Grid size: %dx%d" % [data.get("size", 0), data.get("size", 0)])


func _handle_background(data: Dictionary) -> void:
	if data.has("background_png"):
		_bg_png  = Marshalls.base64_to_raw(data["background_png"])
	if data.has("tile_png") and typeof(data["tile_png"]) == TYPE_STRING:
		_tile_png = Marshalls.base64_to_raw(data["tile_png"])
	else:
		_tile_png = PackedByteArray()
	if not _bg_png.is_empty():
		var img := Image.new()
		if img.load_png_from_buffer(_bg_png) == OK:
			_bg_preview.texture = ImageTexture.create_from_image(img)
	_bg_save_bg.disabled   = _bg_png.is_empty()
	_bg_save_tile.disabled = _tile_png.is_empty()
	_log_msg("Background done! %dx%d" % [data.get("width", 0), data.get("height", 0)])


func _handle_animation(data: Dictionary) -> void:
	if data.has("sheet_png"):
		_sheet_png = Marshalls.base64_to_raw(data["sheet_png"])
	if data.has("gif_png"):
		_gif_png   = Marshalls.base64_to_raw(data["gif_png"])
	if not _sheet_png.is_empty():
		var img := Image.new()
		if img.load_png_from_buffer(_sheet_png) == OK:
			_an_preview.texture = ImageTexture.create_from_image(img)
	_an_save_sheet.disabled = _sheet_png.is_empty()
	_an_save_gif.disabled   = _gif_png.is_empty()
	_log_msg("Animation done! %d frames @ %dx%d" % [
		data.get("frame_count", 0), data.get("width", 0), data.get("height", 0)])


func _handle_isometric(data: Dictionary) -> void:
	if data.has("zip"):
		_iso_zip      = Marshalls.base64_to_raw(data["zip"])
		_iso_zip_name = data.get("zip_name", "iso.zip")
	if data.has("preview_png"):
		_iso_prev_bytes = Marshalls.base64_to_raw(data["preview_png"])
		var img := Image.new()
		if img.load_png_from_buffer(_iso_prev_bytes) == OK:
			_iso_preview.texture = ImageTexture.create_from_image(img)
	_iso_save_zip.disabled = _iso_zip.is_empty()
	var variants: Array = data.get("variants", [])
	_log_msg("Isometric done! Variants: %s — ZIP: %s" % [str(variants), _iso_zip_name])


# =============================================================================
# Server health check
# =============================================================================

func _check_server_status() -> void:
	# Avoid stacking requests
	if _hlth_http.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	_status_lbl.text = "● Server: checking…"
	_hlth_http.request(SERVER_URL + "/api/health")


func _on_health_completed(result: int, response_code: int,
		_hdrs: PackedStringArray, body: PackedByteArray) -> void:
	if result == HTTPRequest.RESULT_SUCCESS and response_code == 200:
		var json := JSON.new()
		if json.parse(body.get_string_from_utf8()) == OK:
			var d: Dictionary = json.get_data()
			var ai: bool = d.get("ai_enabled", false)
			_status_lbl.text = "● Server: online%s" % (" + AI" if ai else " (local only)")
			_log_msg("Ready — select a tab and start generating!")
		else:
			_status_lbl.text = "● Server: online"
			_log_msg("Ready — select a tab and start generating!")
	else:
		_status_lbl.text = "● Server: offline — Tools > PixelMaker: Start Server"
		_log_msg("Server offline. Use Tools > PixelMaker: Start Server.")


# =============================================================================
# Utilities
# =============================================================================

func _set_gen_btns(enabled: bool) -> void:
	for btn: Button in [_sp_gen_btn, _bg_gen_btn, _an_gen_btn, _iso_gen_btn]:
		if is_instance_valid(btn):
			btn.disabled = not enabled


func _log_msg(msg: String) -> void:
	if is_instance_valid(_log_lbl):
		_log_lbl.text = msg
	print("[PixelMaker] " + msg)


func _bool_str(val: bool) -> String:
	return "true" if val else "false"


# =============================================================================
# API key helpers
# =============================================================================

func _update_key_indicator() -> void:
	var has_key := _api_key.text.strip_edges().length() > 0
	_key_indicator.text         = " \u25CF" if has_key else " \u25CB"
	_key_indicator.tooltip_text = "Key saved \u2014 AI features enabled" if has_key else "No key \u2014 AI features disabled"


func _on_api_key_changed(t: String) -> void:
	_update_key_indicator()
	EditorInterface.get_editor_settings().set_setting("pixelmaker/api_key", t)


# =============================================================================
# Usage check
# =============================================================================

func _check_usage() -> void:
	var key := _api_key.text.strip_edges()
	if key.is_empty():
		_key_field_row.visible = true
		_log_msg("Enter your API key first, then press Usage.")
		return
	_log_msg("Fetching OpenAI usage\u2026")
	var body    := ("api_key=" + key.uri_encode()).to_utf8_buffer()
	var headers := PackedStringArray(["Content-Type: application/x-www-form-urlencoded"])
	var err     := _usage_http.request_raw(SERVER_URL + "/api/usage", headers,
						HTTPClient.METHOD_POST, body)
	if err != OK:
		_log_msg("Usage request failed (HTTP error %d)." % err)


func _on_usage_completed(result: int, code: int,
		_hdrs: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		_log_msg("Usage check failed (HTTP %d). Key may lack billing access." % code)
		return
	var json := JSON.new()
	if json.parse(body.get_string_from_utf8()) != OK:
		_log_msg("Usage: could not parse server response.")
		return
	var d: Dictionary = json.get_data()
	if d.has("error"):
		_log_msg("Usage: " + str(d["error"]))
		return
	var parts: Array[String] = []
	if d.has("period"):
		parts.append("Period: " + str(d["period"]))
	if d.has("month_usage_usd"):
		parts.append("This month: $%.4f" % float(d["month_usage_usd"]))
	if d.has("total_available"):
		parts.append("Balance remaining: $%.2f" % float(d["total_available"]))
	if d.has("total_used"):
		parts.append("Total used: $%.2f" % float(d["total_used"]))
	_log_msg(("\n".join(parts)) if parts.size() > 0 else "No billing data returned.")
