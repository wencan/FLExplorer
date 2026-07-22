import base64
import binascii
import configparser
import ctypes
import ctypes.wintypes
import platform
import os
import os.path
import pathlib
import re
import shutil
import dataclasses
import signal
import string
import subprocess
import hashlib
import hmac
import secrets
from collections import OrderedDict
import sys
import time
from typing import (
    List,
    Mapping,
    Literal,
    Tuple,
    get_args,
    get_origin,
    get_type_hints,
    Protocol,
)

__all__ = [
    "APP_NAME",
    "SYS_NAME",
    "generate_unique_code",
    "build_setting_attrs",
    "load_settings",
    "save_settings",
    "Cipher",
    "clean_cryptex",
    "LLMSetting",
    "LLMProvider",
    "LLMReasoningEffort",
    "RecentSetting",
    "Settings",
]

APP_NAME = "FLExplorer"

SYS_NAME = platform.system()

MACHINE_ID = ""
if os.path.exists("/etc/machine-id"):
    try:
        with open("/etc/machine-id") as f:
            MACHINE_ID = f.read().strip()
    except Exception:
        pass


@dataclasses.dataclass
class RecentSetting:
    open_file_dirpath: str = ""


class Cipher(str):
    """A plaintext string requiring encrypted storage."""

    ...


LLMProvider = Literal[
    "DeepSeek",
    "SiliconFlow",
    "OpenRouter",
    "OpenAI",
    "OpenAI-compatible",
]

# https://developers.openai.com/api/docs/guides/reasoning#reasoning-effort
LLMReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]


@dataclasses.dataclass
class LLMSetting:
    unique_code: str = ""  #
    name: str = ""
    provider: LLMProvider = "DeepSeek"
    base_url: str = ""
    api_key: Cipher = dataclasses.field(default_factory=Cipher)
    model: str = ""
    # https://developers.openai.com/api/docs/guides/reasoning#reasoning-effort
    reasoning_effort: LLMReasoningEffort = "none"


@dataclasses.dataclass
class Settings:
    recent: RecentSetting = dataclasses.field(default_factory=RecentSetting)
    llms: List[LLMSetting] = dataclasses.field(default_factory=list)


def generate_unique_code() -> str:
    start_ns = 1767225600000000000  # 2026-01-01T00:00:00Z in nanoseconds
    now_ns = time.time_ns()
    ns = now_ns - start_ns

    ns_base36 = ""
    while ns > 0:
        ns, rem = divmod(ns, 36)
        ns_base36 = (string.digits + string.ascii_uppercase)[rem] + ns_base36

    return ns_base36


def _setting_dir_path() -> str:
    home_path = str(pathlib.Path.home())
    if SYS_NAME == "Windows":
        appdata_dir = os.environ.get(
            "LOCALAPPDATA", os.path.join(home_path, "AppData", "Local")
        )
        config_dir = os.path.join(appdata_dir, APP_NAME)
    elif SYS_NAME == "Linux":
        config_dir = os.path.join(home_path, ".config", APP_NAME)
    elif SYS_NAME == "Darwin":
        config_dir = os.path.join(home_path, "Library", "Application Support", APP_NAME)
    else:
        raise NotImplementedError(f"Unsupported platform: {SYS_NAME}")
    return config_dir


_SETTINGS_DIR_PATH = _setting_dir_path()
_SETTINGS_FILE_PATH = os.path.join(_SETTINGS_DIR_PATH, "settings.ini")


class _Cryptex(Protocol):
    scheme: str

    def __init__(self, app_name: str): ...

    def encrypt(self, attrs: OrderedDict[str, str], plaintext: str) -> str: ...

    def decrypt(self, attrs: OrderedDict[str, str], ciphertext: str) -> str: ...

    def clean(self, attrs: OrderedDict[str, str]): ...

    def clean_all(self, search_attrs: OrderedDict[str, str]): ...


class CalledProcessError(subprocess.CalledProcessError):
    """
    `subprocess.CalledProcessError` does not print `stderr` and `output`.
    """

    def __str__(self):
        if self.returncode and self.returncode < 0:
            try:
                return "Command '%s' died with %r." % (
                    self.cmd,
                    signal.Signals(-self.returncode),
                )
            except ValueError:
                return "Command '%s' died with unknown signal %d." % (
                    self.cmd,
                    -self.returncode,
                )
        else:
            return (
                "Command '%s' returned non-zero exit status %d. stderr: '%s'. output: '%s'"
                % (
                    self.cmd,
                    self.returncode,
                    (self.stderr or "").strip(),
                    (self.output or "").strip(),
                )
            )


class DecryptError(Exception): ...


class LinuxCryptex:
    scheme = "secret"

    def __init__(self, app_name: str):
        self._app_name = app_name

    def encrypt(self, attrs: OrderedDict[str, str], plaintext: str) -> str:
        cmd = ["secret-tool", "store"]
        cmd += ["--label", "-".join([v for v in attrs.values()])]
        cmd += [kv for pair in attrs.items() for kv in pair]
        r = subprocess.run(
            cmd,
            input=plaintext,
            capture_output=True,
            encoding="utf-8",
            text=True,
            timeout=5,
        )
        if r.returncode != 0:
            raise CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr
            )
        return "******"

    def decrypt(self, attrs: OrderedDict[str, str], ciphertext: str) -> str:
        cmd = ["secret-tool", "lookup"]  # no label
        cmd += [kv for pair in attrs.items() for kv in pair]
        r = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", text=True, timeout=5
        )
        if r.returncode == 0:
            return r.stdout.strip()
        elif r.returncode == 1:  # not found
            raise LookupError("not found")
        else:
            raise CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr
            )

    def clean(self, attrs: OrderedDict[str, str]):
        cmd = ["secret-tool", "clear"]
        cmd += [kv for pair in attrs.items() for kv in pair]
        r = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", text=True, timeout=5
        )
        if r.returncode not in (0, 1):
            raise CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr
            )

    def clean_all(self, search_attrs: OrderedDict[str, str]):
        if len(search_attrs) == 0:
            raise ValueError("search_attrs must not be empty")

        cmd = ["secret-tool", "search", "--all"]
        cmd += [kv for pair in search_attrs.items() for kv in pair]
        r = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            text=True,
        )
        if r.returncode != 0:
            raise CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr
            )

        lines = r.stdout.splitlines()
        attrs_list: List[OrderedDict[str, str]] = []
        for line in lines:
            if re.match(r"^\[\/\d+\]$", line):
                attrs_list.append(OrderedDict())
                continue
            if line.startswith("attribute."):
                parts = line.split("=", 1)
                assert len(parts) == 2
                key, value = parts[0].strip(), parts[1].strip()
                key = key[len("attribute.") :]
                attrs_list[-1][key] = value

        for attrs in attrs_list:
            self.clean(attrs)


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _to_blob(data: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB()
    blob.cbData = len(data)
    blob.pbData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    blob._buffer_ref = buf
    return blob


def _from_blob(blob: _DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)  # type: ignore


class WindowsCryptex:
    scheme = "dpapi"

    def __init__(self, app_name: str):
        self._app_name = app_name

    def encrypt(self, attrs: OrderedDict[str, str], plaintext: str) -> str:
        in_blob = _to_blob(plaintext.encode("utf-8"))
        description = "secret_store"
        entropy = "-".join([f"{k}:{v}" for k, v in attrs.items()])
        entropy_blob = _to_blob(entropy.encode("utf-8"))
        entropy_blob_ptr = ctypes.byref(entropy_blob)
        CRYPTPROTECT_UI_FORBIDDEN = 0x01
        out_blob = _DATA_BLOB()

        # https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
        success = ctypes.windll.crypt32.CryptProtectData(  # type: ignore
            ctypes.byref(in_blob),
            description,
            entropy_blob_ptr,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not success:
            raise ctypes.WinError(ctypes.get_last_error())  # type: ignore

        bs = _from_blob(out_blob)
        return base64.urlsafe_b64encode(bs).decode("utf-8")

    def decrypt(self, attrs: OrderedDict[str, str], ciphertext: str) -> str:
        try:
            in_blob = _to_blob(base64.urlsafe_b64decode(ciphertext.encode("utf-8")))
        except binascii.Error as e:  # invalid base64
            raise DecryptError("invalid base64 data") from e
        entropy = "-".join([f"{k}:{v}" for k, v in attrs.items()])
        entropy_blob = _to_blob(entropy.encode("utf-8"))
        entropy_blob_ptr = ctypes.byref(entropy_blob)
        CRYPTPROTECT_UI_FORBIDDEN = 0x01
        out_blob = _DATA_BLOB()

        # https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata
        success = ctypes.windll.crypt32.CryptUnprotectData(  # type: ignore
            ctypes.byref(in_blob),
            None,
            entropy_blob_ptr,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not success:
            # raise ctypes.WinError(ctypes.get_last_error())  # type: ignore
            raise DecryptError("failed to decrypt") from ctypes.WinError(  # type: ignore
                ctypes.get_last_error()  # type: ignore
            )

        bs = _from_blob(out_blob)
        return bs.decode("utf-8")

    def clean(self, attrs: OrderedDict[str, str]):
        pass

    def clean_all(self, search_attrs: OrderedDict[str, str]):
        pass


class DarwinCryptex:
    scheme = "security"

    def __init__(self, app_name: str):
        self._app_name = app_name

    def encrypt(self, attrs: OrderedDict[str, str], plaintext: str) -> str:
        account = "-".join([f"{k}:{v}" for k, v in attrs.items()])

        # When the `security find-generic-password` command outputs content containing non-ASCII characters,
        # it encodes the content as hex before displaying it.
        plaintext_hex = plaintext.encode("utf-8").hex()
        cmd = [
            "security",
            "add-generic-password",
            "-a",
            account,
            "-s",
            self._app_name,
            "-w",
            plaintext_hex,
            "-U",
        ]
        r = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            text=True,
            timeout=5,
        )
        if r.returncode != 0:
            safe_cmd = cmd.copy()
            safe_cmd[cmd.index("-w") + 1] = "******"
            raise CalledProcessError(
                r.returncode, safe_cmd, output=r.stdout, stderr=r.stderr
            )
        return "******"

    def decrypt(self, attrs: OrderedDict[str, str], ciphertext: str) -> str:
        account = "-".join([f"{k}:{v}" for k, v in attrs.items()])
        cmd = [
            "security",
            "find-generic-password",
            "-a",
            account,
            "-s",
            self._app_name,
            "-w",
        ]
        r = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            output = r.stdout.strip()
            return bytes.fromhex(output).decode("utf-8")
        elif r.returncode == 44:
            raise LookupError("not found")
        else:
            raise CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr
            )

    def clean(self, attrs: OrderedDict[str, str]):
        account = "-".join([f"{k}:{v}" for k, v in attrs.items()])
        cmd = [
            "security",
            "delete-generic-password",
            "-a",
            account,
            "-s",
            self._app_name,
        ]
        r = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", text=True, timeout=5
        )
        if r.returncode not in (0, 44):
            raise CalledProcessError(
                r.returncode, cmd, output=r.stdout, stderr=r.stderr
            )

    def clean_all(self, search_attrs: OrderedDict[str, str]):
        raise NotImplementedError()


def _xor_bytes(b1: bytes, b2: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(b1, b2))


def _derive_keys(master_key: bytes) -> tuple[bytes, bytes]:
    """Derive independent encryption and MAC keys from the master key"""
    enc_key = hmac.new(master_key, b"encryption", hashlib.sha256).digest()
    mac_key = hmac.new(master_key, b"authentication", hashlib.sha256).digest()
    return enc_key, mac_key


def _simple_encrypt(plaintext: bytes, key: bytes) -> bytes:
    # This function was generated by Gemini 3.5 Flash.

    # 1. Derive independent subkeys
    enc_key, mac_key = _derive_keys(key)

    # 2. Generate a random nonce and perform CTR-like encryption
    nonce = secrets.token_bytes(16)
    block_size = 32
    num_blocks = (len(plaintext) + block_size - 1) // block_size

    keystream = bytearray()
    for i in range(num_blocks):
        counter_block = nonce + i.to_bytes(8, byteorder="big")
        block_key = hmac.new(enc_key, counter_block, hashlib.sha256).digest()
        keystream.extend(block_key)

    ciphertext_payload = _xor_bytes(plaintext, keystream)

    # 3. Combine the nonce and the ciphertext payload
    encrypted_data = nonce + ciphertext_payload

    # 4. Calculate the MAC over the entire encrypted_data (nonce + ciphertext)
    # HMAC-SHA256 outputs a 32-byte digest
    mac = hmac.new(mac_key, encrypted_data, hashlib.sha256).digest()

    # 5. Format: nonce (16 bytes) + ciphertext (N bytes) + MAC (32 bytes)
    return encrypted_data + mac


def _simple_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    # This function was generated by Gemini 3.5 Flash.

    # Minimum length: nonce (16 bytes) + MAC (32 bytes) = 48 bytes
    if len(ciphertext) < 48:
        raise DecryptError("invalid ciphertext")

    # 1. Derive independent subkeys
    enc_key, mac_key = _derive_keys(key)

    # 2. Separate the encrypted data and the received MAC
    encrypted_data = ciphertext[:-32]
    received_mac = ciphertext[-32:]

    # 3. Recompute and compare the MAC (using compare_digest to prevent timing attacks)
    expected_mac = hmac.new(mac_key, encrypted_data, hashlib.sha256).digest()
    if not hmac.compare_digest(received_mac, expected_mac):
        raise DecryptError("ciphertext integrity check failed")

    # 4. Decrypt the data after validation passes
    nonce = encrypted_data[:16]
    payload = encrypted_data[16:]

    block_size = 32
    num_blocks = (len(payload) + block_size - 1) // block_size

    keystream = bytearray()
    for i in range(num_blocks):
        counter_block = nonce + i.to_bytes(8, byteorder="big")
        block_key = hmac.new(enc_key, counter_block, hashlib.sha256).digest()
        keystream.extend(block_key)

    return _xor_bytes(payload, keystream)


class SimpleCryptex:
    scheme = "simple"

    def __init__(self, app_name: str):
        self._app_name = app_name

    def _key(self, attrs: OrderedDict[str, str]) -> str:
        key = ""
        if MACHINE_ID != "":
            key += MACHINE_ID + "-"

        key += "-".join([f"{k}:{v}" for k, v in attrs.items()])
        return key

    def encrypt(self, attrs: OrderedDict[str, str], plaintext: str) -> str:
        key = self._key(attrs)
        encrypted = _simple_encrypt(plaintext.encode(), key.encode("utf-8"))
        encoded = base64.urlsafe_b64encode(encrypted)
        return encoded.decode("utf-8")

    def decrypt(self, attrs: OrderedDict[str, str], ciphertext: str) -> str:
        try:
            decoded = base64.urlsafe_b64decode(ciphertext.encode("utf-8"))
            key = self._key(attrs)
            decrypted = _simple_decrypt(decoded, key.encode())
            return decrypted.decode("utf-8")
        except binascii.Error as e:  # invalid base64
            raise DecryptError("invalid ciphertext") from e

    def clean(self, attrs: OrderedDict[str, str]):
        pass

    def clean_all(self, search_attrs: OrderedDict[str, str]):
        pass


def _cryptex_for_environ() -> type[_Cryptex]:
    if SYS_NAME == "Linux":
        if shutil.which("secret-tool") is not None:
            return LinuxCryptex
    elif SYS_NAME == "Windows":
        return WindowsCryptex
    elif SYS_NAME == "Darwin":
        if shutil.which("security") is not None:
            return DarwinCryptex

    # fallback
    return SimpleCryptex


_attrs2scheme = {}


def encrypt_with_attrs(
    app_name: str, attrs: OrderedDict[str, str], plaintext: str
) -> str:
    cryptex_cls = _cryptex_for_environ()
    cryptex = cryptex_cls(app_name)
    ciphertext = cryptex.encrypt(attrs, plaintext)
    scheme = cryptex.scheme
    ciphertext = f"{scheme}:{ciphertext}"

    _attrs2scheme[tuple(attrs.items())] = scheme

    return ciphertext


def _cryptex_for_scheme(scheme: str) -> type[_Cryptex] | None:
    cryptex_clses: Tuple[type[_Cryptex], ...] = (
        LinuxCryptex,
        WindowsCryptex,
        DarwinCryptex,
        SimpleCryptex,
    )
    for cryptex_cls in cryptex_clses:
        if scheme == cryptex_cls.scheme:
            return cryptex_cls
    return None


def decrypt_with_attrs(
    app_name: str, attrs: OrderedDict[str, str], ciphertext: str
) -> str:
    parts = ciphertext.split(":")
    if len(parts) != 2:
        raise ValueError(f"invalid ciphertext: {ciphertext}")
    scheme, cipher_part = parts[0], parts[1]

    cryptex_cls = _cryptex_for_scheme(scheme)
    if cryptex_cls is None:
        raise DecryptError(f"Unsupported encryption scheme {scheme}")

    cryptex = cryptex_cls(app_name)
    plaintext = cryptex.decrypt(attrs, cipher_part)

    _attrs2scheme[tuple(attrs.items())] = scheme

    return plaintext


def clean_cryptex_with_attrs(app_name: str, attrs: OrderedDict[str, str]):
    key = tuple(attrs.items())
    scheme = _attrs2scheme.get(key)
    if scheme is None:
        raise LookupError(f"No encryption scheme found for {attrs}")

    cryptex_cls = _cryptex_for_scheme(scheme)
    if cryptex_cls is None:
        raise DecryptError(f"Unsupported encryption scheme {scheme}")
    cryptex = cryptex_cls(app_name)
    cryptex.clean(attrs)

    del _attrs2scheme[key]


def clean_cryptex(app_name: str):
    cryptex_cls = _cryptex_for_environ()
    cryptex = cryptex_cls(app_name)
    cryptex.clean_all(OrderedDict([("app", app_name)]))


def _strtobool(val: str) -> bool:
    val = val.lower()
    if val in ("y", "yes", "t", "true", "on", "1"):
        return True
    elif val in ("n", "no", "f", "false", "off", "0"):
        return False
    else:
        raise ValueError(f"invalid bool value {val!r}")


def build_setting_attrs(
    app_name: str, setting_name: str, field_name: str
) -> OrderedDict[str, str]:
    return OrderedDict(
        [("app", app_name), ("setting", setting_name), ("field", field_name)]
    )


def setting_from_strdict(
    app_name: str, setting_name: str, data_cls, str_dict: Mapping[str, str]
):
    """Convert a dict whose keys and values are both strings into a setting dataclass object."""
    hints = get_type_hints(data_cls)

    fields = dataclasses.fields(data_cls)
    key2field = {field.name: field for field in fields}
    kvs = {}
    for k, v in str_dict.items():
        field = key2field.get(k)
        if field is None:
            continue
        if get_origin(field.type) == Literal:
            allowed = get_args(field.type)
            if v not in allowed:
                raise ValueError(f"{k} must be one of [{allowed}]")
        else:
            vtype = hints[k]
            if vtype is bool:
                v = _strtobool(v)
            elif vtype is Cipher:
                if v != "":
                    attrs = build_setting_attrs(app_name, setting_name, k)
                    v = decrypt_with_attrs(app_name, attrs, v)
            else:
                v = hints[k](v)
        kvs[k] = v
    return data_cls(**kvs)


def setting_to_strdict(app_name: str, setting_name: str, data):
    """Convert a setting dataclass object into a dict whose keys and values are both strings."""
    d = {}
    for field in dataclasses.fields(data):
        k = field.name
        v = getattr(data, field.name)
        if field.type is bool:
            v = str(v).lower()
        elif field.type is Cipher:
            if v != "":
                attrs = build_setting_attrs(app_name, setting_name, k)
                v = encrypt_with_attrs(app_name, attrs, v)
        d[k] = v
    return d


def load_settings(
    settings_filepath: str = _SETTINGS_FILE_PATH, app_name: str = APP_NAME
) -> Settings:
    parser = configparser.ConfigParser()
    parser.read(settings_filepath, encoding="utf-8")

    settings_dict = {}

    for setting_name, type_ in get_type_hints(Settings).items():
        if get_origin(type_) is list:
            setting_type = get_args(type_)[0]

            setting_list = []
            for full_setting_name in parser.sections():
                if full_setting_name.startswith(f"{setting_name}_"):
                    str_dict = parser[full_setting_name]
                    try:
                        setting = setting_from_strdict(
                            app_name, full_setting_name, setting_type, str_dict
                        )
                    except DecryptError as e:
                        print(
                            f"failed to decrypt section [{full_setting_name}]: {e}",
                            file=sys.stderr,
                        )
                    else:
                        setting_list.append(setting)
            settings_dict[setting_name] = setting_list
        else:
            setting_type = type_
            if parser.has_section(setting_name):
                str_dict = parser[setting_name]
                try:
                    setting = setting_from_strdict(
                        app_name, setting_name, setting_type, str_dict
                    )
                except DecryptError as e:
                    print(
                        f"failed to decrypt section [{setting_name}]: {e}",
                        file=sys.stderr,
                    )
                else:
                    settings_dict[setting_name] = setting

    return Settings(**settings_dict)


def _save_settings(
    app_name: str,
    settings: Settings,
    settings_filepath: str = _SETTINGS_FILE_PATH,
):
    parser = configparser.ConfigParser()

    for setting_name, type_ in get_type_hints(Settings).items():
        setting = getattr(settings, setting_name)
        if get_origin(type_) is list:
            setting_list = setting
            for setting in setting_list:
                unique_code = getattr(setting, "unique_code")
                assert unique_code is not None
                full_setting_name = f"{setting_name}_{unique_code}"
                parser[full_setting_name] = setting_to_strdict(
                    app_name, full_setting_name, setting
                )
        else:
            parser[setting_name] = setting_to_strdict(app_name, setting_name, setting)

    os.makedirs(os.path.dirname(settings_filepath), exist_ok=True)
    with open(settings_filepath, "w", encoding="utf-8") as f:
        parser.write(f)


def _clean_cryptex_for_deleted_setting(
    app_name: str, new_settings: Settings, pre_settings: Settings
):
    for setting_name, type_ in get_type_hints(Settings).items():
        pre_setting = getattr(pre_settings, setting_name)
        if get_origin(type_) is list:
            pre_setting_list = pre_setting
            for pre_setting in pre_setting_list:
                unique_code = getattr(pre_setting, "unique_code")
                assert unique_code is not None

                # check if the setting is deleted
                deleted = True
                new_setting_list = getattr(new_settings, setting_name)
                for new_setting in new_setting_list:
                    if getattr(new_setting, "unique_code") == unique_code:
                        deleted = False
                if not deleted:
                    continue

                full_setting_name = f"{setting_name}_{unique_code}"
                sub_type = get_args(type_)[0]
                for filed_name, field_type in get_type_hints(sub_type).items():
                    if field_type is Cipher:
                        attrs = build_setting_attrs(
                            app_name, full_setting_name, filed_name
                        )
                        clean_cryptex_with_attrs(app_name, attrs)


def save_settings(
    new_settings: Settings,
    settings_filepath: str = _SETTINGS_FILE_PATH,
    previous_settings: Settings | None = None,
    app_name: str = APP_NAME,
):
    _save_settings(app_name, new_settings, settings_filepath)
    if previous_settings is not None:
        _clean_cryptex_for_deleted_setting(app_name, new_settings, previous_settings)
