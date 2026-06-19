"""Punto de entrada con UI. Reemplaza main.py.

Uso:
  python app.py --list     ver índices de dispositivos
  python app.py            abrir la ventana y configurar desde la UI
"""

import argparse
import asyncio
import base64
import concurrent.futures
import json
import os
import sys
import threading

import webview
from google import genai

# Logo embebido (data URI) para la cabecera; si falta, queda cadena vacía.
# Se reduce a 128px para no inflar el HTML; si Pillow no está, usa el PNG tal cual.
_logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
LOGO_DATA_URI = ""
if os.path.exists(_logo_path):
    try:
        import io
        from PIL import Image
        _img = Image.open(_logo_path)
        _img.thumbnail((128, 128))
        _buf = io.BytesIO()
        _img.save(_buf, format="PNG")
        _logo_bytes = _buf.getvalue()
    except Exception:
        with open(_logo_path, "rb") as _lf:
            _logo_bytes = _lf.read()
    LOGO_DATA_URI = "data:image/png;base64," + base64.b64encode(_logo_bytes).decode()

# Cargar .env si existe (sin dependencias externas)
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _v = _v.strip().strip('"').strip("'")
                os.environ.setdefault(_k.strip(), _v)

from audio import (MicCapture, Player, list_devices,
                   LoopbackCapture, list_loopback_devices, default_loopback_device)
from config import UNDERSTAND_TARGET, SPEAK_TARGET
from translator import TranslationSession

# ── HTML/CSS/JS de la interfaz ────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Loro — Traducción en vivo</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: #0f0f10;
    color: #e0e0e0;
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 20px;
    background: #1a1a1e;
    border-bottom: 1px solid #2a2a2e;
    flex-shrink: 0;
  }

  header h1 {
    font-size: 1.1rem; font-weight: 600; letter-spacing: 0.05em; color: #a0c4ff;
    display: flex; align-items: center; gap: 8px;
  }
  header h1 #logo {
    width: 28px; height: 28px; border-radius: 7px;
    object-fit: cover; display: block;
  }
  header h1 #logo[src=""] { display: none; }

  #status {
    font-size: 0.75rem;
    padding: 3px 10px;
    border-radius: 12px;
    background: #2a2a2e;
    color: #888;
  }
  #status.running      { background: #1a3a2a; color: #5dbb8a; }
  #status.error        { background: #3a1a1a; color: #e06060; }
  #status.reconnecting { background: #3a2e1a; color: #d8a850; animation: pulse 1.2s ease-in-out infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }

  #controls {
    display: flex;
    gap: 8px;
  }

  button {
    padding: 5px 16px;
    border: none;
    border-radius: 6px;
    font-size: 0.8rem;
    cursor: pointer;
    font-weight: 600;
    transition: opacity 0.15s;
  }
  button:disabled { opacity: 0.4; cursor: default; }
  #btn-start  { background: #3a7bd5; color: #fff; }
  #btn-stop   { background: #c0392b; color: #fff; }
  #btn-config { background: #2a2a3a; color: #a0a0c0; border: 1px solid #3a3a5a; }

  /* ── Setup modal ─────────────────────────────────── */
  #modal-overlay {
    position: fixed; inset: 0;
    background: rgba(0,0,0,.7);
    display: flex; align-items: center; justify-content: center;
    z-index: 100;
  }
  #modal-overlay.hidden { display: none; }

  #modal {
    background: #1a1a1e;
    border: 1px solid #2a2a2e;
    border-radius: 12px;
    padding: 28px 32px;
    width: 480px;
    max-height: 90vh;
    overflow-y: auto;
  }
  #modal h2 { font-size: 1rem; margin-bottom: 4px; color: #a0c4ff; }
  #modal .subtitle { font-size: 0.75rem; color: #555; margin-bottom: 18px; }

  .field { margin-bottom: 14px; }
  .field label { display: block; font-size: 0.75rem; color: #888; margin-bottom: 2px; }
  .field select {
    width: 100%;
    background: #111114;
    color: #e0e0e0;
    border: 1px solid #333;
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 0.85rem;
  }
  .field select.ok  { border-color: #2a6a3a; }
  .field select.warn { border-color: #6a4a1a; }

  .hint {
    font-size: 0.7rem;
    color: #556;
    margin-top: 3px;
    line-height: 1.4;
  }
  .hint b { color: #778; }

  .app-steps {
    background: #111114;
    border: 1px solid #222;
    border-radius: 8px;
    padding: 10px 14px;
    margin-bottom: 16px;
    font-size: 0.72rem;
    color: #556;
    line-height: 1.6;
  }
  .app-steps b { color: #889; }
  .app-steps .apps { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 6px; }
  .app-steps .app-btn {
    padding: 2px 8px; border-radius: 4px; border: 1px solid #333;
    background: #1a1a1e; color: #778; cursor: pointer; font-size: 0.7rem;
    transition: border-color 0.15s, color 0.15s;
  }
  .app-steps .app-btn.active { border-color: #3a7bd5; color: #a0c4ff; }

  #modal-start {
    width: 100%;
    margin-top: 8px;
    padding: 9px;
    background: #3a7bd5;
    color: #fff;
    font-size: 0.9rem;
    border-radius: 8px;
  }

  /* ── Paneles de transcript ───────────────────────── */
  #panels {
    flex: 1;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1px;
    background: #2a2a2e;
    overflow: hidden;
  }

  .panel {
    background: #0f0f10;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .panel-top {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 14px;
    background: #1a1a1e;
    border-bottom: 1px solid #2a2a2e;
    flex-shrink: 0;
  }
  .panel-header {
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #666;
    white-space: nowrap;
  }
  .panel-header span { color: #a0c4ff; }

  /* Medidor de nivel de audio (VU) */
  .vu {
    flex: 1;
    height: 6px;
    background: #0d0d10;
    border-radius: 3px;
    overflow: hidden;
  }
  .vu-fill {
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, #2a7d4f, #5dbb8a 70%, #e0c060);
    border-radius: 3px;
    transition: width 0.08s linear;
  }

  .transcript {
    flex: 1;
    overflow-y: auto;
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .bubble {
    max-width: 92%;
    padding: 8px 12px;
    border-radius: 10px;
    font-size: 0.85rem;
    line-height: 1.45;
    animation: fadein 0.2s ease;
  }
  @keyframes fadein { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; } }

  .bubble.input  { background: #1e2a3a; color: #c8d8f0; align-self: flex-start; }
  .bubble.output { background: #1e3a2a; color: #c0e8d0; align-self: flex-end; }

  .bubble .kind {
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 3px;
    opacity: 0.6;
  }

  .lang-grid {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    gap: 6px;
    align-items: start;
  }
  .lang-grid select {
    width: 100%;
    background: #111114;
    color: #e0e0e0;
    border: 1px solid #333;
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 0.85rem;
  }

  .empty-hint {
    color: #333;
    font-size: 0.8rem;
    text-align: center;
    margin-top: 40px;
  }
</style>
</head>
<body>

<div id="modal-overlay">
  <div id="modal">
    <h2>Configuración</h2>
    <p class="subtitle">Sin cables ni programas extra. Loro escucha lo que suena en tus auriculares.</p>

    <div class="app-steps">
      <b>Único paso en tu app de llamada (Discord/Zoom/Meet…):</b><br>
      🎙 En <b>Micrófono</b> elige <b>CABLE Input (VB-Audio Virtual Cable)</b>.<br>
      <span style="color:#445">Así la llamada escucha la traducción de tu voz, no tu voz real.
      El altavoz déjalo en tus auriculares de siempre.</span>
    </div>

    <div class="field">
      <label>① Tu micrófono real (donde hablas tú)</label>
      <select id="sel-mic-real"></select>
      <p class="hint">El micrófono con el que hablas normalmente.</p>
    </div>
    <div class="field">
      <label>② Micrófono virtual de la llamada</label>
      <select id="sel-virtual-mic"></select>
      <p class="hint">El mismo <b>CABLE Input</b> que pusiste en tu app de llamada.</p>
    </div>
    <div class="field">
      <label>③ Audio que escuchas (tus auriculares)</label>
      <select id="sel-loopback"></select>
      <p class="hint">Loro captura lo que suena aquí para traducir al entrevistador. Por defecto: tu salida de Windows.</p>
    </div>
    <div class="field lang-row">
      <label>④ Idiomas</label>
      <div class="lang-grid">
        <div>
          <p class="hint" style="margin-bottom:4px">Tu idioma <span style="color:#556">(tú hablas y escuchas)</span></p>
          <select id="sel-lang-me">
            <option value="es">🇪🇸 Español</option>
            <option value="en">🇺🇸 Inglés</option>
            <option value="fr">🇫🇷 Francés</option>
            <option value="de">🇩🇪 Alemán</option>
            <option value="pt">🇧🇷 Portugués</option>
            <option value="it">🇮🇹 Italiano</option>
            <option value="ja">🇯🇵 Japonés</option>
            <option value="ko">🇰🇷 Coreano</option>
            <option value="zh">🇨🇳 Chino (mandarín)</option>
            <option value="ar">🇸🇦 Árabe</option>
            <option value="ru">🇷🇺 Ruso</option>
            <option value="hi">🇮🇳 Hindi</option>
          </select>
        </div>
        <div style="align-self:center;text-align:center;color:#445;font-size:1.1rem;padding-top:18px">⇄</div>
        <div>
          <p class="hint" style="margin-bottom:4px">Idioma del entrevistador</p>
          <select id="sel-lang-them">
            <option value="en">🇺🇸 Inglés</option>
            <option value="es">🇪🇸 Español</option>
            <option value="fr">🇫🇷 Francés</option>
            <option value="de">🇩🇪 Alemán</option>
            <option value="pt">🇧🇷 Portugués</option>
            <option value="it">🇮🇹 Italiano</option>
            <option value="ja">🇯🇵 Japonés</option>
            <option value="ko">🇰🇷 Coreano</option>
            <option value="zh">🇨🇳 Chino (mandarín)</option>
            <option value="ar">🇸🇦 Árabe</option>
            <option value="ru">🇷🇺 Ruso</option>
            <option value="hi">🇮🇳 Hindi</option>
          </select>
        </div>
      </div>
    </div>
    <p id="vb-warn" style="display:none;color:#c08030;font-size:0.72rem;margin-top:10px;">
      ⚠ No se detectó <b>CABLE Input</b>. Para que la llamada escuche tu voz traducida instala
      <b>VB-Audio Virtual Cable</b> (gratuito) y reinicia la app.
    </p>
    <button id="modal-start" onclick="startFromModal()">Iniciar traducción</button>
  </div>
</div>

<header>
  <h1><img id="logo" src="__LOGO__" alt="">Loro</h1>
  <div id="controls">
    <span id="status">Detenido</span>
    <button id="btn-config" onclick="openConfig()">Configurar</button>
    <button id="btn-stop" onclick="stopSessions()" disabled>Detener</button>
  </div>
</header>

<div id="panels">
  <div class="panel">
    <div class="panel-top">
      <div class="panel-header" id="header-entender">Entrevistador → <span>Español</span></div>
      <div class="vu"><div class="vu-fill" id="vu-entender"></div></div>
    </div>
    <div class="transcript" id="t-entender">
      <p class="empty-hint">Esperando audio del entrevistador…</p>
    </div>
  </div>
  <div class="panel">
    <div class="panel-top">
      <div class="panel-header" id="header-hablar">Tú → <span>Inglés</span></div>
      <div class="vu"><div class="vu-fill" id="vu-hablar"></div></div>
    </div>
    <div class="transcript" id="t-hablar">
      <p class="empty-hint">Esperando tu voz…</p>
    </div>
  </div>
</div>

<script>
  // ── poblar selects con los dispositivos ───────────────────────────
  function fillSelect(id, items, defaultIndex) {
    const sel = document.getElementById(id);
    sel.innerHTML = '';
    items.forEach(it => {
      const opt = document.createElement('option');
      opt.value = it.index;
      opt.text  = it.name;
      sel.appendChild(opt);
    });
    if (defaultIndex !== undefined && defaultIndex !== null) {
      sel.value = defaultIndex;
    }
  }

  // Selecciona en un <select> la opción cuyo texto coincide con `name`.
  // Devuelve true si la encontró (para saber si una pref sigue siendo válida).
  function selectByName(id, name) {
    if (!name) return false;
    const sel = document.getElementById(id);
    for (const opt of sel.options) {
      if (opt.text === name) { sel.value = opt.value; return true; }
    }
    return false;
  }

  async function loadDevices() {
    try {
      const raw = await window.pywebview.api.get_setup();
      const setup = JSON.parse(raw);

      fillSelect('sel-mic-real', setup.mics, setup.mics[0] && setup.mics[0].index);
      fillSelect('sel-virtual-mic', setup.cables,
                 setup.cables[0] && setup.cables[0].index);

      // Loopback: agrega opción "automática" + la lista
      const loopItems = [{index: '', name: '🔊 Automático (salida de Windows)'}]
                        .concat(setup.loopbacks);
      fillSelect('sel-loopback', loopItems, '');

      // Marcar visualmente
      if (setup.cables.length) document.getElementById('sel-virtual-mic').classList.add('ok');

      document.getElementById('vb-warn').style.display =
        setup.cables.length === 0 ? 'block' : 'none';

      // Restaurar preferencias guardadas (por NOMBRE, los índices cambian).
      const prefsRaw = await window.pywebview.api.load_prefs();
      const prefs = JSON.parse(prefsRaw || '{}');
      if (prefs.mic_name)     selectByName('sel-mic-real', prefs.mic_name);
      if (prefs.cable_name)   selectByName('sel-virtual-mic', prefs.cable_name);
      if (prefs.loopback_name) selectByName('sel-loopback', prefs.loopback_name);
      if (prefs.lang_me)   document.getElementById('sel-lang-me').value = prefs.lang_me;
      if (prefs.lang_them) document.getElementById('sel-lang-them').value = prefs.lang_them;
    } catch(e) {
      console.error('Error cargando dispositivos', e);
    }
  }

  // Texto seleccionado de un <select> (o '' si es la opción vacía).
  function selText(id) {
    const sel = document.getElementById(id);
    const opt = sel.options[sel.selectedIndex];
    return opt ? opt.text : '';
  }

  const LANG_NAMES = {
    es:'Español', en:'Inglés', fr:'Francés', de:'Alemán', pt:'Portugués',
    it:'Italiano', ja:'Japonés', ko:'Coreano', zh:'Chino', ar:'Árabe',
    ru:'Ruso', hi:'Hindi',
  };

  async function startFromModal() {
    const langMe   = document.getElementById('sel-lang-me').value;
    const langThem = document.getElementById('sel-lang-them').value;

    document.getElementById('header-entender').innerHTML =
      `Entrevistador → <span>${LANG_NAMES[langMe] || langMe}</span>`;
    document.getElementById('header-hablar').innerHTML =
      `Tú → <span>${LANG_NAMES[langThem] || langThem}</span>`;

    const loopVal = document.getElementById('sel-loopback').value;
    const cfg = {
      mic_real:    +document.getElementById('sel-mic-real').value,
      virtual_mic: +document.getElementById('sel-virtual-mic').value,
      loopback:    loopVal === '' ? null : +loopVal,
      lang_me:   langMe,
      lang_them: langThem,
    };

    // Guardar preferencias por NOMBRE para la próxima vez.
    window.pywebview.api.save_prefs(JSON.stringify({
      mic_name:      selText('sel-mic-real'),
      cable_name:    selText('sel-virtual-mic'),
      loopback_name: loopVal === '' ? '' : selText('sel-loopback'),
      lang_me:   langMe,
      lang_them: langThem,
    }));

    document.getElementById('modal-overlay').classList.add('hidden');
    setStatus('Conectando…', '');
    await window.pywebview.api.start_sessions(JSON.stringify(cfg));
  }

  async function stopSessions() {
    await window.pywebview.api.stop_sessions();
  }

  function openConfig() {
    document.getElementById('modal-overlay').classList.remove('hidden');
  }

  // ── transcripts con acumulación ──────────────────────────────────
  // Por cada (session, kind) guardamos la burbuja activa y un timer.
  // Fragmentos que llegan dentro de 2.5 s se añaden a la misma burbuja.
  const _active = {};  // clave: "session-kind" -> { bubble, timer, textNode }

  function addTranscript(session, kind, text) {
    const panelId = session === 'entender' ? 't-entender' : 't-hablar';
    const panel = document.getElementById(panelId);

    const hint = panel.querySelector('.empty-hint');
    if (hint) hint.remove();

    const key = `${session}-${kind}`;

    if (_active[key]) {
      // Añadir a la burbuja existente
      clearTimeout(_active[key].timer);
      _active[key].textNode.textContent += ' ' + text;
      panel.scrollTop = panel.scrollHeight;
    } else {
      // Crear burbuja nueva
      const bubble = document.createElement('div');
      bubble.className = `bubble ${kind}`;
      const label = document.createElement('div');
      label.className = 'kind';
      label.textContent = kind === 'input' ? 'Escuché' : 'Traduje';
      const textNode = document.createElement('span');
      textNode.textContent = text;
      bubble.appendChild(label);
      bubble.appendChild(textNode);
      panel.appendChild(bubble);
      panel.scrollTop = panel.scrollHeight;
      _active[key] = { bubble, textNode };
    }

    // Cerrar burbuja tras 2.5 s de silencio
    _active[key].timer = setTimeout(() => {
      delete _active[key];
    }, 2500);
  }

  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function setStatus(label, cls) {
    const el = document.getElementById('status');
    el.textContent = label;
    el.className = cls;
    // Detener disponible mientras esté activo (traduciendo o reconectando).
    const active = (cls === 'running' || cls === 'reconnecting');
    document.getElementById('btn-stop').disabled = !active;
  }

  // pywebview llama esto desde Python
  window.onTranscript = function(session, kind, text) {
    addTranscript(session, kind, text);
  };
  window.onStatusChange = function(label, cls) {
    setStatus(label, cls);
  };
  // Niveles de audio (0.0–1.0) -> ancho de las barras VU
  window.onLevels = function(understand, hablar) {
    document.getElementById('vu-entender').style.width = Math.min(understand * 100, 100) + '%';
    document.getElementById('vu-hablar').style.width   = Math.min(hablar * 100, 100) + '%';
  };

  // Al cargar
  window.addEventListener('pywebviewready', loadDevices);
</script>
</body>
</html>
"""

# Insertar el logo embebido en el HTML.
HTML = HTML.replace("__LOGO__", LOGO_DATA_URI)


# Ruta del archivo de preferencias (junto al script).
PREFS_PATH = os.path.join(os.path.dirname(__file__), "loro_prefs.json")


# ── API expuesta a JS ─────────────────────────────────────────────────────────
class Api:
    def __init__(self):
        self._window = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._sessions: list[TranslationSession] = []
        self._conn: dict[str, str] = {}  # estado de conexión por sesión

    # ── preferencias persistidas ──────────────────────────────────────
    def load_prefs(self) -> str:
        """Devuelve las preferencias guardadas (nombres de dispositivos + idiomas)."""
        try:
            with open(PREFS_PATH, encoding="utf-8") as f:
                return f.read()
        except (FileNotFoundError, OSError):
            return "{}"

    def save_prefs(self, prefs_json: str):
        """Guarda las preferencias. El JS manda nombres, no índices."""
        try:
            with open(PREFS_PATH, "w", encoding="utf-8") as f:
                f.write(prefs_json)
        except OSError as e:
            print(f"No se pudieron guardar preferencias: {e}")

    def set_window(self, window):
        self._window = window

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    # ── llamados desde JS ─────────────────────────────────────────────
    def get_devices(self) -> str:
        import sounddevice as sd
        devs = []
        for i, d in enumerate(sd.query_devices()):
            devs.append({
                "index": i,
                "name": d["name"],
                "inputs": d["max_input_channels"],
                "outputs": d["max_output_channels"],
                "rate": int(d["default_samplerate"]),
            })
        return json.dumps(devs)

    def get_setup(self) -> str:
        """Devuelve lo que el modal simplificado necesita:
        - micrófonos reales (entrada, sin cables ni dispositivos del sistema)
        - cables virtuales de salida (para inyectar a la llamada)
        - loopbacks disponibles + cuál es el del altavoz por defecto
        """
        import sounddevice as sd

        def is_cable(name):
            n = name.lower()
            return "cable" in n or "vb-audio" in n or "voicemeeter" in n

        def is_system(name):
            n = name.lower()
            return any(s in n for s in (
                "asignador de sonido", "controlador primario",
                "mezcla estéreo", "stereo mix", "sound mapper",
                "primary sound", "hands-free", "bthhfenum"))

        # Preferir nombres completos (WASAPI) sobre los truncados (MME):
        # recorremos en orden y por nombre base nos quedamos con el más largo.
        mics, cables = {}, {}
        for i, d in enumerate(sd.query_devices()):
            name = d["name"]
            if is_system(name):
                continue
            if d["max_input_channels"] > 0 and not is_cable(name):
                key = name[:25]
                if key not in mics or len(name) > len(mics[key]["name"]):
                    mics[key] = {"index": i, "name": name}
            if (d["max_output_channels"] > 0 and is_cable(name)
                    and "output" not in name.lower()):
                key = name[:25]
                if key not in cables or len(name) > len(cables[key]["name"]):
                    cables[key] = {"index": i, "name": name}

        mics = list(mics.values())
        cables = list(cables.values())
        # Poner "CABLE Input" primero (lo que la mayoría debe elegir).
        cables.sort(key=lambda c: (0 if "cable input" in c["name"].lower() else 1,
                                   c["name"]))

        try:
            loopbacks = [{"index": i, "name": n} for i, n in list_loopback_devices()]
            default_lb = default_loopback_device()
            default_lb = {"index": default_lb[0], "name": default_lb[1]} if default_lb else None
        except Exception:
            loopbacks, default_lb = [], None

        return json.dumps({
            "mics": mics,
            "cables": cables,
            "loopbacks": loopbacks,
            "default_loopback": default_lb,
        })

    def start_sessions(self, cfg_json: str):
        cfg = json.loads(cfg_json)
        if not os.environ.get("GEMINI_API_KEY"):
            self._js("onStatusChange('Sin GEMINI_API_KEY', 'error')")
            return
        future = asyncio.run_coroutine_threadsafe(
            self._run_sessions(cfg), self._loop
        )
        future.add_done_callback(self._on_done)

    def stop_sessions(self):
        if self._task and not self._task.done():
            self._loop.call_soon_threadsafe(self._task.cancel)

    # ── internos ──────────────────────────────────────────────────────
    def _js(self, code: str):
        if self._window:
            self._window.evaluate_js(code)

    def _on_transcript(self, name: str, kind: str, text: str):
        safe = json.dumps(text)
        self._js(f"onTranscript({json.dumps(name)}, {json.dumps(kind)}, {safe})")

    def _on_conn_status(self, name: str, estado: str):
        """Combina el estado de las dos sesiones en un estado global de UI."""
        self._conn[name] = estado
        if any(s == "reconnecting" for s in self._conn.values()):
            self._js("onStatusChange('Reconectando…', 'reconnecting')")
        elif self._conn and all(s == "connected" for s in self._conn.values()):
            self._js("onStatusChange('Traduciendo…', 'running')")

    def _on_done(self, future):
        try:
            future.result()
        except (asyncio.CancelledError, concurrent.futures.CancelledError):
            pass
        except Exception as e:
            msg = json.dumps(f"Error: {str(e)[:80]}")
            self._js(f"onStatusChange({msg}, 'error')")
            return
        self._js("onStatusChange('Detenido', '')")

    async def _run_sessions(self, cfg: dict):
        client = genai.Client()
        self._conn = {}  # reiniciar estado de conexión

        # "entender": capturamos lo que SUENA en los auriculares (loopback WASAPI),
        # traducimos a tu idioma y SOLO mostramos el texto (sin reproducir, para no
        # hacer loop con el propio audio que sale por los auriculares).
        loopback_idx = cfg.get("loopback")  # None = altavoz por defecto
        understand = TranslationSession(
            name="entender",
            client=client,
            mic=LoopbackCapture(loopback_idx),
            player=None,  # modo solo-texto
            target_language=cfg.get("lang_me", UNDERSTAND_TARGET),
            on_transcript=self._on_transcript,
            on_status=self._on_conn_status,
        )

        # "hablar": tu micrófono real -> traducción al idioma del entrevistador
        # -> sale por el CABLE virtual que Discord usa como micrófono.
        speak = TranslationSession(
            name="hablar",
            client=client,
            mic=MicCapture(cfg["mic_real"]),
            player=Player(cfg["virtual_mic"]),
            target_language=cfg.get("lang_them", SPEAK_TARGET),
            on_transcript=self._on_transcript,
            on_status=self._on_conn_status,
        )
        self._sessions = [understand, speak]

        self._js("onStatusChange('Conectando…', 'reconnecting')")
        try:
            self._task = asyncio.current_task()
            await asyncio.gather(
                understand.run(),
                speak.run(),
                self._level_loop(understand.mic, speak.mic),
            )
        finally:
            understand.close()
            speak.close()
            self._js("onLevels(0, 0)")  # apagar barras al detener
            self._sessions = []

    async def _level_loop(self, understand_mic, speak_mic):
        """Envía a la UI el nivel de audio de cada captura ~7 veces/s."""
        while True:
            self._js(f"onLevels({understand_mic.level:.3f}, {speak_mic.level:.3f})")
            await asyncio.sleep(0.14)


# ── entrypoint ────────────────────────────────────────────────────────────────
def main():
    api = Api()

    # asyncio en hilo propio; pywebview toma el hilo principal
    loop = asyncio.new_event_loop()
    api.set_loop(loop)
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()

    window = webview.create_window(
        title="Loro — Traducción en vivo",
        html=HTML,
        js_api=api,
        width=960,
        height=620,
        min_size=(720, 480),
        background_color="#0f0f10",
    )
    api.set_window(window)

    _icon = os.path.join(os.path.dirname(__file__), "logo.ico")
    start_kwargs = {"debug": False}
    if os.path.exists(_icon):
        start_kwargs["icon"] = _icon
    try:
        webview.start(**start_kwargs)
    except TypeError:
        # Backends/versiones de pywebview que no aceptan icon=
        webview.start(debug=False)

    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=3)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="Listar dispositivos y salir")
    args = parser.parse_args()
    if args.list:
        list_devices()
    else:
        main()
