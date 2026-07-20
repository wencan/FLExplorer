import os
import random
import string
import time
import tempfile
import unittest
from collections import OrderedDict
from flexplorer.settings import (
    APP_NAME,
    LLMSetting,
    Cipher,
    Settings,
    SimpleCryptex,
    encrypt_with_attrs,
    decrypt_with_attrs,
    clean_cryptex_with_attrs,
    DecryptError,
    generate_unique_code,
    load_settings,
    save_settings,
    setting_from_strdict,
    setting_to_strdict,
)


def _random_chars(min_length: int, max_length: int) -> str:
    k = random.randint(min_length, max_length)
    return "".join(random.choices("张三李四王五" + string.hexdigits, k=k))


class TestSimpleCryptex(unittest.TestCase):
    def test_cryptex(self):
        attrs: OrderedDict[str, str] = OrderedDict(
            [
                ("app", "__unittest__"),
                ("setting", _random_chars(1, 10)),
                ("field", _random_chars(1, 10)),
            ]
        )
        plaintext = _random_chars(6, 100)
        cryptex = SimpleCryptex()
        ciphertext = cryptex.encrypt(attrs, plaintext)
        decrypted = cryptex.decrypt(attrs, ciphertext)
        self.assertEqual(decrypted, plaintext)

    def test_mismatch_attrs(self):
        attrs: OrderedDict[str, str] = OrderedDict(
            [
                ("app", "__unittest__"),
                ("setting", _random_chars(1, 10)),
                ("field", _random_chars(1, 10)),
            ]
        )
        plaintext = _random_chars(6, 100)
        cryptex = SimpleCryptex()
        ciphertext = cryptex.encrypt(attrs, plaintext)

        mismatch_attrs = attrs.copy()
        mismatch_attrs["needless"] = _random_chars(1, 10)
        with self.assertRaises(DecryptError):
            cryptex.decrypt(mismatch_attrs, ciphertext)

    def test_bad_ciphertext(self):
        attrs: OrderedDict[str, str] = OrderedDict(
            [
                ("app", "__unittest__"),
                ("setting", _random_chars(1, 10)),
                ("field", _random_chars(1, 10)),
            ]
        )
        plaintext = _random_chars(6, 100)
        cryptex = SimpleCryptex()
        ciphertext = cryptex.encrypt(attrs, plaintext)
        bad_ciphertext = ciphertext[:-1] + chr(ord(ciphertext[-1]) + 1)
        with self.assertRaises(DecryptError):
            cryptex.decrypt(attrs, bad_ciphertext)


class TestEncryptDecrypt(unittest.TestCase):
    def test_encrypt_decrypt(self):
        attrs: OrderedDict[str, str] = OrderedDict(
            [
                ("app", "__unittest__"),
                ("setting", _random_chars(1, 10)),
                ("field", _random_chars(1, 10)),
            ]
        )
        plaintext = _random_chars(6, 100)
        try:
            ciphertext = encrypt_with_attrs(attrs, plaintext)
            try:
                decrypted = decrypt_with_attrs(attrs, ciphertext)
            except LookupError:
                time.sleep(1)  # wait for secret-tool
                decrypted = decrypt_with_attrs(attrs, ciphertext)
            self.assertEqual(decrypted, plaintext)
        finally:
            clean_cryptex_with_attrs(attrs)

    def test_mismatch_attrs(self):
        attrs: OrderedDict[str, str] = OrderedDict(
            [
                ("app", "__unittest__"),
                ("setting", _random_chars(1, 10)),
                ("field", _random_chars(1, 10)),
            ]
        )
        plaintext = _random_chars(6, 100)
        try:
            ciphertext = encrypt_with_attrs(attrs, plaintext)

            mismatch_attrs = attrs.copy()
            mismatch_attrs["needless"] = _random_chars(1, 10)
            with self.assertRaises(DecryptError):
                decrypt_with_attrs(mismatch_attrs, ciphertext)
        finally:
            clean_cryptex_with_attrs(attrs)

    def test_bad_ciphertext(self):
        attrs: OrderedDict[str, str] = OrderedDict(
            [
                ("app", "__unittest__"),
                ("setting", _random_chars(1, 10)),
                ("field", _random_chars(1, 10)),
            ]
        )
        plaintext = _random_chars(6, 100)
        try:
            ciphertext = encrypt_with_attrs(attrs, plaintext)
            if ciphertext.endswith("******"):
                pass
            else:
                bad_ciphertext = ciphertext[:-1] + chr(ord(ciphertext[-1]) + 1)
                with self.assertRaises(DecryptError):
                    decrypt_with_attrs(attrs, bad_ciphertext)
        finally:
            clean_cryptex_with_attrs(attrs)


class TestSettingSerializer(unittest.TestCase):
    def test_without_cipher(self):
        llm = LLMSetting()
        llm.unique_code = generate_unique_code()
        llm.name = _random_chars(1, 10)
        llm.provider = "DeepSeek"
        llm.model = "test-1.0-flash"
        llm.base_url = "https://" + _random_chars(1, 10)
        llm.reasoning_effort = "medium"
        derialized = setting_to_strdict("llms", llm)
        deserialized = setting_from_strdict("llms", LLMSetting, derialized)
        self.assertEqual(llm, deserialized)

    def test_with_cipher(self):
        try:
            llm = LLMSetting()
            llm.unique_code = generate_unique_code()
            llm.name = _random_chars(1, 10)
            llm.provider = "DeepSeek"
            llm.api_key = Cipher(_random_chars(6, 10))
            llm.model = "test-1.0-flash"
            llm.base_url = "https://" + _random_chars(1, 10)
            llm.reasoning_effort = "medium"
            derialized = setting_to_strdict("llm", llm)
            deserialized = setting_from_strdict("llm", LLMSetting, derialized)
            self.assertEqual(llm, deserialized)
        finally:
            clean_cryptex_with_attrs(
                OrderedDict(
                    [
                        ("app", APP_NAME),
                        ("setting", "llm"),
                        ("field", "api_key"),
                    ]
                )
            )


class TestSettingsSerializer(unittest.TestCase):
    def test_without_no_llms(self):
        settings_path = os.path.join(
            tempfile.gettempdir(), f"settings_{time.time_ns()}.ini"
        )
        try:
            settings = Settings()
            settings.recent.open_file_dirpath = _random_chars(1, 10)
            save_settings(settings, settings_path)
            loaded = load_settings(settings_path)
            self.assertEqual(settings, loaded)
        finally:
            os.remove(settings_path)

    def test_without_one_llm(self):
        settings_path = os.path.join(
            tempfile.gettempdir(), f"settings_{time.time_ns()}.ini"
        )

        settings = Settings()
        try:
            settings.recent.open_file_dirpath = _random_chars(1, 10)
            settings.llms = [
                LLMSetting(
                    unique_code=generate_unique_code(),
                    name=_random_chars(1, 10),
                    provider="DeepSeek",
                    api_key=Cipher(_random_chars(6, 10)),
                    model="test-1.0-flash",
                    base_url="https://" + _random_chars(1, 10),
                    reasoning_effort="medium",
                )
            ]
            save_settings(settings, settings_path)
            loaded = load_settings(settings_filepath=settings_path)
            self.assertEqual(settings, loaded)
        finally:
            os.remove(settings_path)
            clean_cryptex_with_attrs(
                OrderedDict(
                    [
                        ("app", APP_NAME),
                        ("setting", "llms_" + settings.llms[0].name),
                        ("field", "api_key"),
                    ]
                )
            )

    def test_without_multi_llms(self):
        settings_path = os.path.join(
            tempfile.gettempdir(), f"settings_{time.time_ns()}.ini"
        )

        settings = Settings()
        try:
            settings.recent.open_file_dirpath = _random_chars(1, 10)
            for _ in range(random.randint(3, 10)):
                settings.llms.append(
                    LLMSetting(
                        unique_code=generate_unique_code(),
                        name=_random_chars(1, 10),
                        provider="DeepSeek",
                        api_key=Cipher(_random_chars(6, 10)),
                        model="test-1.0-flash",
                        base_url="https://" + _random_chars(1, 10),
                        reasoning_effort="medium",
                    )
                )
            save_settings(settings, settings_path)
            loaded = load_settings(settings_filepath=settings_path)
            self.assertEqual(settings, loaded)
        finally:
            os.remove(settings_path)
            clean_cryptex_with_attrs(
                OrderedDict(
                    [
                        ("app", APP_NAME),
                        ("setting", "llms_" + settings.llms[0].name),
                        ("field", "api_key"),
                    ]
                )
            )
