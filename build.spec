# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['sf_saver.py'],
    pathex=[],
    binaries=[],
    datas=[('sflib/single-file.js', 'sflib'), ('sflib/LICENSE-SingleFile.txt', 'sflib'), ('app.ico', '.')],
    hiddenimports=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebChannel'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'numpy', 'pandas', 'matplotlib', 'scipy', 'PIL', 'PySide6.QtQuick',
              'PySide6.QtQml', 'PySide6.Qt3DCore', 'PySide6.QtMultimedia', 'PySide6.QtCharts',
              'PySide6.QtDataVisualization', 'PySide6.QtBluetooth', 'PySide6.QtNfc',
              'PySide6.QtPositioning', 'PySide6.QtSerialPort', 'PySide6.QtSql', 'PySide6.QtTest'],
    noarchive=False,
    optimize=0,
)
# _DROP_MARKS: 去掉调试用资源，减小体积、加快单文件解压启动
_DROP = ("devtools_resources", ".debug.pak", "v8_context_snapshot.debug")


def _trim(seq):
    out = []
    for e in seq:
        nm = str(e[0]).replace("\\", "/").lower()
        if any(d in nm for d in _DROP):
            continue
        out.append(e)
    return out


a.datas = _trim(a.datas)
a.binaries = _trim(a.binaries)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='离线网页保存器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app.ico',
)
