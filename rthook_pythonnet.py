"""PyInstaller Runtime-Hook: DLL-Suchpfad für pythonnet korrigieren.

Wird VOR dem App-Code ausgeführt. Stellt sicher, dass pythonnet's .NET-Runtime
die python3XX.dll im PyInstaller-Bundle findet.
"""
import os
import sys

if getattr(sys, "frozen", False) and sys.platform == "win32":
    _meipass = sys._MEIPASS

    # 1) PYTHONNET_PYDLL: expliziter Pfad zur Python-DLL für pythonnet
    _dll = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    _dll_path = os.path.join(_meipass, _dll)
    if os.path.exists(_dll_path):
        os.environ["PYTHONNET_PYDLL"] = _dll_path

    # 2) PATH erweitern: .NET's LoadLibrary sucht auch über PATH
    os.environ["PATH"] = _meipass + os.pathsep + os.environ.get("PATH", "")

    # 3) os.add_dll_directory (Python 3.8+): Windows DLL-Suchpfad erweitern
    try:
        os.add_dll_directory(_meipass)
    except (OSError, AttributeError):
        pass
