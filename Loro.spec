# PyInstaller spec para Loro.
# Construir con:   pyinstaller Loro.spec
# Resultado:       dist/Loro/Loro.exe  (carpeta con el exe + dependencias)
#
# Notas:
# - sounddevice, scipy, google-genai y pyaudiowpatch traen DLLs/datos que hay que
#   recolectar explícitamente con collect_all, o el exe falla al arrancar.
# - El .env y el logo NO se empaquetan: deben quedar JUNTO al exe para que la app
#   los encuentre (la app los busca en su carpeta). Ver README de build abajo.

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("sounddevice", "_sounddevice_data", "scipy",
            "google", "google.genai", "pyaudiowpatch", "webview",
            "elevenlabs"):  # voz clonada
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Logo embebido en la ventana (la cabecera ya va inline; el ícono necesita el .ico).
datas += [("logo.ico", "."), ("logo.png", ".")]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],  # no se usan; reducen tamaño
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Loro",
    console=False,          # sin ventana de consola
    icon="logo.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="Loro",
)
