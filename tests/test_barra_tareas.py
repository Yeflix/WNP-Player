"""Botones de la miniatura de la barra de tareas (taskbar_buttons.py) y COM con
ctypes (wincom.py): lo que se puede comprobar sin Windows."""
import ctypes, os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import taskbar_buttons as TB, wincom

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("ok   " if cond else "FALLA"), name, "" if cond else detail); fails += 0 if cond else 1

def wparam(bid): return (TB.THBN_CLICKED << 16) | bid
check("botón 1 → anterior", TB.action_for_command(wparam(1)) == "previous")
check("botón 2 → reproducir/pausar", TB.action_for_command(wparam(2)) == "play_pause")
check("botón 3 → siguiente", TB.action_for_command(wparam(3)) == "next")
check("otro WM_COMMAND (menú, etc.) → nada", TB.action_for_command(5) is None and TB.action_for_command(wparam(9)) is None)
check("mismos nombres que las teclas globales", {a for _i, a in TB.BUTTONS} == {"previous", "play_pause", "next"})
ptr = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 4
T = TB.THUMBBUTTON
icon_off = 16 if ptr == 8 else 12
check("THUMBBUTTON: hIcon alineado como en el SDK", T.hIcon.offset == icon_off, str(T.hIcon.offset))
check("THUMBBUTTON: szTip y dwFlags donde toca",
      T.szTip.offset == icon_off + ptr and T.dwFlags.offset == T.szTip.offset + 260 * ctypes.sizeof(ctypes.c_wchar))
if sys.platform == "win32":
    check("THUMBBUTTON: tamaño del SDK", ctypes.sizeof(T) == (552 if ptr == 8 else 540), str(ctypes.sizeof(T)))
g = wincom.GUID.from_str("EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF")
check("GUID ida y vuelta", str(g).upper() == "EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF" and ctypes.sizeof(g) == 16)
import process_loopback as PL
check("WAVEFORMATEX empaquetada (18 bytes)", ctypes.sizeof(PL._WAVEFORMATEX) == 18)
check("PROPVARIANT (24 bytes en 64 bits)", ctypes.sizeof(PL._PROPVARIANT) == (24 if ptr == 8 else 16))
check("parámetros de activación (12 bytes)", ctypes.sizeof(PL._ACTIVATION_PARAMS) == 12)
check("HRESULT de error se detecta", wincom.failed(-2147467262) and not wincom.failed(1))
try:
    wincom.check(-2147467262, "prueba"); check("check lanza ComError", False)
except wincom.ComError as e:
    check("check lanza ComError con el código", "80004002" in str(e))
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
