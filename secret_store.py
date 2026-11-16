"""Protege los secretos de `config.json` (tokens y claves) para que no queden en
texto plano en el disco.

En Windows usa DPAPI (`CryptProtectData`), el mismo mecanismo que usan los
navegadores para guardar contraseñas: el dato solo se puede descifrar con la
MISMA cuenta de usuario de Windows en el MISMO equipo. Se llama por `ctypes`, sin
instalar nada. Qué protege y qué no:

- SÍ: un `config.json` que se copia a otro equipo o usuario, que acaba en una
  copia de seguridad en la nube, o que se sube por error a GitHub, deja de
  regalar las cuentas de Spotify / Google / Last.fm / ListenBrainz.
- NO: un programa que corra con TU cuenta en TU equipo puede pedirle a Windows
  que descifre (igual que con los navegadores). No es una caja fuerte.

En macOS y Linux no hay un equivalente sin dependencias extra: los valores se
quedan en texto plano y `config.save()` restringe el archivo a tu usuario
(permisos 600).

Formato en el archivo: `"dpapi:<base64>"`. Un valor SIN ese prefijo (un
`config.json` de versiones anteriores, o pegado a mano) se acepta tal cual y se
protege solo en el siguiente guardado.

Si descifrar falla (el archivo viene de otro equipo/usuario), el campo queda
vacío y hay que volver a conectar esa cuenta: es preferible a mostrar basura.
"""
from __future__ import annotations

import base64
import sys

from diag import note

PREFIX = "dpapi:"

# Campos de AppConfig que son secretos. (Los `client_id` no lo son: identifican a
# TU app de desarrollador y van dentro de las URL de autorización.)
SECRET_FIELDS = (
    "spotify_refresh_token",
    "google_client_secret",
    "google_refresh_token",
    "lastfm_api_secret",
    "lastfm_session_key",
    "listenbrainz_token",
    "youtube_api_key",
)


class _Dpapi:
    """DPAPI de Windows por ctypes. Solo se crea en Windows."""

    CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class DataBlob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]

        self._ct = ctypes
        self._Blob = DataBlob
        self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        blob_p = ctypes.POINTER(DataBlob)
        self._crypt32.CryptProtectData.argtypes = [
            blob_p, wintypes.LPCWSTR, blob_p, ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, blob_p]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            blob_p, ctypes.c_void_p, blob_p, ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, blob_p]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    def _call(self, fn, data: bytes, *, protect: bool) -> bytes:
        ct = self._ct
        buf = ct.create_string_buffer(data, len(data))          # se mantiene vivo durante la llamada
        blob_in = self._Blob(len(data), ct.cast(buf, ct.c_void_p))
        blob_out = self._Blob()
        if protect:
            ok = fn(ct.byref(blob_in), "YefriPlayer", None, None, None,
                    self.CRYPTPROTECT_UI_FORBIDDEN, ct.byref(blob_out))
        else:
            ok = fn(ct.byref(blob_in), None, None, None, None,
                    self.CRYPTPROTECT_UI_FORBIDDEN, ct.byref(blob_out))
        if not ok:
            raise OSError(ct.get_last_error(), "DPAPI falló")
        try:
            return ct.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            self._kernel32.LocalFree(blob_out.pbData)

    def encrypt(self, data: bytes) -> bytes:
        return self._call(self._crypt32.CryptProtectData, data, protect=True)

    def decrypt(self, data: bytes) -> bytes:
        return self._call(self._crypt32.CryptUnprotectData, data, protect=False)


_backend = None
_backend_loaded = False


def _get_backend():
    """El cifrador disponible (o None). Se crea una sola vez."""
    global _backend, _backend_loaded  # noqa: PLW0603 — estado de módulo a propósito (lo leen otros módulos o las pruebas)
    if not _backend_loaded:
        _backend_loaded = True
        if sys.platform == "win32":
            try:
                _backend = _Dpapi()
            except Exception as exc:
                note("secret_store.init", exc)
                _backend = None
    return _backend


def set_backend(backend) -> None:
    """Sustituye el cifrador (solo para pruebas). `None` = sin cifrado."""
    global _backend, _backend_loaded
    _backend, _backend_loaded = backend, True


def available() -> bool:
    return _get_backend() is not None


def protect(text: str) -> str:
    """Texto -> `dpapi:<base64>`. Si no se puede cifrar, devuelve el texto tal cual
    (perder un token sería peor que dejarlo en claro)."""
    if not isinstance(text, str) or not text or text.startswith(PREFIX):
        return text
    backend = _get_backend()
    if backend is None:
        return text
    try:
        blob = backend.encrypt(text.encode("utf-8"))
        return PREFIX + base64.b64encode(blob).decode("ascii")
    except Exception as exc:
        note("secret_store.protect", exc)
        return text


def reveal(text: str) -> str:
    """`dpapi:<base64>` -> texto. Un valor sin prefijo se devuelve igual (es de una
    versión anterior o pegado a mano). Si no se puede descifrar -> "" (volver a conectar)."""
    if not isinstance(text, str) or not text.startswith(PREFIX):
        return text
    backend = _get_backend()
    if backend is None:
        note("secret_store.reveal", RuntimeError("valor protegido pero sin DPAPI disponible"))
        return ""
    try:
        return backend.decrypt(base64.b64decode(text[len(PREFIX):], validate=True)).decode("utf-8")
    except Exception as exc:
        note("secret_store.reveal", exc)
        return ""


def protect_fields(data: dict) -> dict:
    """Copia de `data` con los campos secretos protegidos (para escribir al disco)."""
    out = dict(data)
    for name in SECRET_FIELDS:
        if name in out:
            out[name] = protect(out[name])
    return out


def reveal_fields(data: dict) -> dict:
    """Copia de `data` con los campos secretos ya en claro (al leer del disco)."""
    out = dict(data)
    for name in SECRET_FIELDS:
        if name in out:
            out[name] = reveal(out[name])
    return out
