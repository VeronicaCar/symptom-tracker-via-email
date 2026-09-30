"""Keep the Gmail app password in Windows Credential Manager.

The SYMPTOM_TRACKER_APP_PASSWORD environment variable, when set, wins over the
stored credential.
"""

import ctypes
import os
import sys
from ctypes import wintypes as wt

ENV_VAR = "SYMPTOM_TRACKER_APP_PASSWORD"
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wt.DWORD),
        ("Type", wt.DWORD),
        ("TargetName", wt.LPWSTR),
        ("Comment", wt.LPWSTR),
        ("LastWritten", wt.FILETIME),
        ("CredentialBlobSize", wt.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wt.DWORD),
        ("AttributeCount", wt.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wt.LPWSTR),
        ("UserName", wt.LPWSTR),
    ]


def _advapi():
    if sys.platform != "win32":
        raise OSError("Windows Credential Manager is only available on Windows")
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.CredReadW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD,
                              ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))]
    api.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIAL), wt.DWORD]
    api.CredDeleteW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD]
    api.CredFree.argtypes = [ctypes.c_void_p]
    return api


def _target(email):
    return f"SymptomTracker:{email.lower()}"


def get_password(email):
    env = os.environ.get(ENV_VAR)
    if env:
        return env.replace(" ", "")
    api = _advapi()
    ptr = ctypes.POINTER(_CREDENTIAL)()
    if not api.CredReadW(_target(email), _CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)):
        if ctypes.get_last_error() == _ERROR_NOT_FOUND:
            return None
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        cred = ptr.contents
        blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        return blob.decode("utf-16-le")
    finally:
        api.CredFree(ptr)


def set_password(email, password):
    password = "".join(password.split())  # Google shows app passwords in groups of 4
    blob = password.encode("utf-16-le")
    buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = _CREDENTIAL(
        Type=_CRED_TYPE_GENERIC,
        TargetName=_target(email),
        Comment="Gmail app password for Symptom Tracker",
        CredentialBlobSize=len(blob),
        CredentialBlob=ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)),
        Persist=_CRED_PERSIST_LOCAL_MACHINE,
        UserName=email,
    )
    if not _advapi().CredWriteW(ctypes.byref(cred), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def delete_password(email):
    api = _advapi()
    if not api.CredDeleteW(_target(email), _CRED_TYPE_GENERIC, 0):
        if ctypes.get_last_error() != _ERROR_NOT_FOUND:
            raise ctypes.WinError(ctypes.get_last_error())
