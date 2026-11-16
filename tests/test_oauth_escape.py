"""La página de error del servidor OAuth local no debe permitir inyectar HTML."""
import os, sys, urllib.request, urllib.parse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import oauth_pkce

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1

srv = oauth_pkce.CallbackServer(0)
try:
    evil = "<script>alert(1)</script><img src=x onerror=alert(2)>"
    url = f"http://127.0.0.1:{srv.port}{oauth_pkce.CALLBACK_PATH}?" + urllib.parse.urlencode(
        {"error": "access_denied", "error_description": evil})
    body = urllib.request.urlopen(url, timeout=5).read().decode("utf-8")
    check("el HTML del error viene escapado", "<script>" not in body and "<img" not in body)
    check("el texto sigue visible (escapado)", "&lt;script&gt;" in body)
    try:
        srv.wait("estado", timeout_s=2)
        check("el error se reporta", False)
    except oauth_pkce.OAuthError as exc:
        check("el error se reporta como OAuthError", "rechazó" in str(exc))
finally:
    srv.close()
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
