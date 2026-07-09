import configparser
import platform
import os
import os.path
import pathlib
import dataclasses
from typing import (
    List,
    Mapping,
    Literal,
    get_args,
    get_origin,
    get_type_hints,
)

__all__ = ["APP_NAME", "SYS_NAME", "SETTINGS", "save_settings"]

APP_NAME = "FLExplorer"

SYS_NAME = platform.system()


def _config_dir_path() -> str:
    home_path = str(pathlib.Path.home())
    if SYS_NAME == "Windows":
        config_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.join(home_path, "AppData", "Local")),
            APP_NAME,
        )
    elif SYS_NAME == "Linux":
        config_dir = os.path.join(home_path, ".config", APP_NAME)
    elif SYS_NAME == "Darwin":
        config_dir = os.path.join(home_path, "Library", "Application Support", APP_NAME)
    else:
        raise NotImplementedError(f"Unsupported platform: {SYS_NAME}")
    return config_dir


_CONFIG_DIR_PATH = _config_dir_path()
_SETTINGS_PATH = os.path.join(_CONFIG_DIR_PATH, "settings.ini")


@dataclasses.dataclass
class Recent:
    open_file_dirpath: str = ""


@dataclasses.dataclass
class LLM:
    name: str = ""
    provider: Literal["deepseek"] = "deepseek"
    encrypted_key: str = ""
    model: str = ""
    completions_url: str = ""
    thinking: bool = False
    preferred: bool = False


@dataclasses.dataclass
class Settings:
    recent: Recent = dataclasses.field(default_factory=Recent)
    llms: List[LLM] = dataclasses.field(default_factory=list)


def _strtobool(val: str) -> bool:
    val = val.lower()
    if val in ("y", "yes", "t", "true", "True", "on", "1"):
        return True
    elif val in ("n", "no", "f", "false", "False", "off", "0"):
        return False
    else:
        raise ValueError(f"invalid bool value {val!r}")


def _from_dict(data_cls, str_dict: Mapping[str, str]):
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
            else:
                v = hints[k](v)
        kvs[k] = v
    return data_cls(**kvs)


def _to_dict(data):
    d = {}
    for field in dataclasses.fields(data):
        k = field.name
        v = getattr(data, field.name)
        if field.type is bool:
            v = str(v).lower()
        d[k] = v
    return d


def load_settings() -> Settings:
    parser = configparser.ConfigParser()
    parser.read(_SETTINGS_PATH, encoding="utf-8")

    settings = {}

    for section_name, type_ in get_type_hints(Settings).items():
        if get_origin(type_) is list:
            data_type = get_args(type_)[0]

            data_list = []
            for full_name in parser.sections():
                if full_name.startswith(f"{section_name}_"):
                    str_dict = parser[full_name]
                    item = _from_dict(data_type, str_dict)
                    data_list.append(item)
            settings[section_name] = data_list
        else:
            if parser.has_section(section_name):
                str_dict = parser[section_name]
                data = _from_dict(type_, str_dict)
                settings[section_name] = data

    return Settings(**settings)


SETTINGS = load_settings()


def save_settings():
    parser = configparser.ConfigParser()

    for section_name, type_ in get_type_hints(Settings).items():
        data = getattr(SETTINGS, section_name)
        if get_origin(type_) is list:
            for item in data:
                item_name = getattr(item, "name")
                full_name = f"{section_name}_{item_name}"
                parser[full_name] = _to_dict(item)
        else:
            parser[section_name] = _to_dict(data)

    with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
        parser.write(f)
