from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes


@dataclass(frozen=True)
class CredentialReference:
    account_id: str
    service: str
    channel_id: str
    assigned_worker_id: str
    credential_ref: str
    scopes: tuple[str, ...]
    status: str = "NOT_CONNECTED"
    last_verified_at: str | None = None


class WindowsCredentialVault:
    """Reference-only Windows credential-vault boundary.

    Secret values are deliberately absent from this API's serializable model.
    A future publisher may resolve a reference inside its process using an OS
    credential provider; workers, state, logs and UI never receive the value.
    """

    @property
    def backend(self) -> str:
        return "WINDOWS_CREDENTIAL_MANAGER"

    @property
    def available(self) -> bool:
        return hasattr(ctypes, "windll") and hasattr(ctypes.windll, "advapi32")

    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD), ("Attributes", wintypes.LPVOID),
            ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    def store(self, credential_ref: str, secret: bytes) -> None:
        self._validate_ref(credential_ref)
        if not self.available: raise RuntimeError("Secure Windows credential backend is unavailable")
        blob = (ctypes.c_ubyte * len(secret)).from_buffer_copy(secret)
        credential = self._CREDENTIAL(Type=1, TargetName=credential_ref, CredentialBlobSize=len(secret),
            CredentialBlob=ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte)), Persist=2, UserName="JARVIS OAuth")
        if not ctypes.windll.advapi32.CredWriteW(ctypes.byref(credential), 0):
            raise ctypes.WinError()

    def delete(self, credential_ref: str) -> None:
        self._validate_ref(credential_ref)
        if self.available and not ctypes.windll.advapi32.CredDeleteW(credential_ref, 1, 0):
            error = ctypes.get_last_error()
            if error not in (0, 1168): raise ctypes.WinError(error)

    def resolve_for_publisher(self, credential_ref: str):
        self._validate_ref(credential_ref)
        if not self.available:
            raise RuntimeError("Secure Windows credential backend is unavailable")
        pointer = ctypes.POINTER(self._CREDENTIAL)()
        if not ctypes.windll.advapi32.CredReadW(credential_ref, 1, 0, ctypes.byref(pointer)):
            raise ctypes.WinError()
        try:
            item = pointer.contents
            return ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize)
        finally:
            ctypes.windll.advapi32.CredFree(pointer)

    @staticmethod
    def _validate_ref(credential_ref: str) -> None:
        if not credential_ref or len(credential_ref) > 256 or any(ch in credential_ref for ch in "\r\n\0"):
            raise ValueError("Invalid credential reference")
