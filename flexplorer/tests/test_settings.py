import copy
import os
import random
import string
import time
import tempfile
import unittest
import unittest.mock
from typing import List
from collections import OrderedDict
from flexplorer.settings import (
    LLMSetting,
    Cipher,
    Settings,
    SimpleCryptex,
    clean_cryptex,
    encrypt_with_attrs,
    decrypt_with_attrs,
    build_setting_attrs,
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
    _app_name = "__flexplorer_unittest__"

    def tearDown(self):
        clean_cryptex(self._app_name)

    def test_cryptex(self):
        attrs: OrderedDict[str, str] = build_setting_attrs(
            self._app_name, _random_chars(1, 10), _random_chars(1, 10)
        )
        plaintext = _random_chars(6, 100)
        cryptex = SimpleCryptex(self._app_name)
        ciphertext = cryptex.encrypt(attrs, plaintext)
        decrypted = cryptex.decrypt(attrs, ciphertext)
        self.assertEqual(decrypted, plaintext)

    def test_mismatch_attrs(self):
        attrs: OrderedDict[str, str] = build_setting_attrs(
            self._app_name, _random_chars(1, 10), _random_chars(1, 10)
        )
        plaintext = _random_chars(6, 100)
        cryptex = SimpleCryptex(self._app_name)
        ciphertext = cryptex.encrypt(attrs, plaintext)

        try:
            mismatch_attrs = attrs.copy()
            mismatch_attrs["needless"] = _random_chars(1, 10)
            with self.assertRaises(DecryptError):
                cryptex.decrypt(mismatch_attrs, ciphertext)
        finally:
            cryptex.clean(attrs)

    def test_bad_ciphertext(self):
        attrs: OrderedDict[str, str] = build_setting_attrs(
            self._app_name, _random_chars(1, 10), _random_chars(1, 10)
        )
        plaintext = _random_chars(6, 100)
        cryptex = SimpleCryptex(self._app_name)
        ciphertext = cryptex.encrypt(attrs, plaintext)

        try:
            bad_ciphertext = ciphertext[:-1] + chr(ord(ciphertext[-1]) + 1)
            with self.assertRaises(DecryptError):
                cryptex.decrypt(attrs, bad_ciphertext)
        finally:
            cryptex.clean(attrs)


class TestEncryptDecrypt(unittest.TestCase):
    _app_name = "__flexplorer_unittest__"

    def tearDown(self):
        clean_cryptex(self._app_name)

    def test_encrypt_decrypt(self):
        attrs: OrderedDict[str, str] = build_setting_attrs(
            self._app_name, _random_chars(1, 10), _random_chars(1, 10)
        )
        plaintext = _random_chars(6, 100)
        ciphertext = encrypt_with_attrs(self._app_name, attrs, plaintext)
        try:
            try:
                decrypted = decrypt_with_attrs(self._app_name, attrs, ciphertext)
            except LookupError:
                time.sleep(1)  # wait for secret-tool
                decrypted = decrypt_with_attrs(self._app_name, attrs, ciphertext)
            self.assertEqual(decrypted, plaintext)
        finally:
            clean_cryptex_with_attrs(self._app_name, attrs)

    def test_clean(self):
        attrs: OrderedDict[str, str] = build_setting_attrs(
            self._app_name, _random_chars(1, 10), _random_chars(1, 10)
        )
        plaintext = _random_chars(6, 100)
        ciphertext = encrypt_with_attrs(self._app_name, attrs, plaintext)
        clean_cryptex_with_attrs(self._app_name, attrs)
        if ciphertext.endswith("******"):
            return
        with self.assertRaises(LookupError):
            decrypt_with_attrs(self._app_name, attrs, ciphertext)

    def test_mismatch_attrs(self):
        attrs: OrderedDict[str, str] = build_setting_attrs(
            self._app_name, _random_chars(1, 10), _random_chars(1, 10)
        )
        plaintext = _random_chars(6, 100)
        ciphertext = encrypt_with_attrs(self._app_name, attrs, plaintext)
        try:
            mismatch_attrs = attrs.copy()
            mismatch_attrs["needless"] = _random_chars(1, 10)
            with self.assertRaises(LookupError):
                decrypt_with_attrs(self._app_name, mismatch_attrs, ciphertext)
        finally:
            clean_cryptex_with_attrs(self._app_name, attrs)

    def test_bad_ciphertext(self):
        attrs: OrderedDict[str, str] = build_setting_attrs(
            self._app_name, _random_chars(1, 10), _random_chars(1, 10)
        )
        plaintext = _random_chars(6, 100)
        ciphertext = encrypt_with_attrs(self._app_name, attrs, plaintext)
        try:
            if ciphertext.endswith("******"):
                pass
            else:
                bad_ciphertext = ciphertext[:-1] + chr(ord(ciphertext[-1]) + 1)
                with self.assertRaises(DecryptError):
                    decrypt_with_attrs(self._app_name, attrs, bad_ciphertext)
        finally:
            clean_cryptex_with_attrs(self._app_name, attrs)


class TestSettingSerializer(unittest.TestCase):
    _app_name = "__flexplorer_unittest__"

    def tearDown(self):
        clean_cryptex(self._app_name)

    def test_without_cipher(self):
        llm = LLMSetting()
        llm.unique_code = generate_unique_code()
        llm.name = _random_chars(1, 10)
        llm.provider = "DeepSeek"
        llm.model = "test-1.0-flash"
        llm.base_url = "https://" + _random_chars(1, 10)
        llm.reasoning_effort = "medium"
        derialized = setting_to_strdict(self._app_name, "llms", llm)
        deserialized = setting_from_strdict(
            self._app_name, "llms", LLMSetting, derialized
        )
        self.assertEqual(llm, deserialized)

    def test_with_cipher(self):
        llm = LLMSetting()
        llm.unique_code = generate_unique_code()
        llm.name = _random_chars(1, 10)
        llm.provider = "DeepSeek"
        llm.api_key = Cipher(_random_chars(6, 10))
        llm.model = "test-1.0-flash"
        llm.base_url = "https://" + _random_chars(1, 10)
        llm.reasoning_effort = "medium"
        derialized = setting_to_strdict(self._app_name, "llm", llm)
        try:
            deserialized = setting_from_strdict(
                self._app_name, "llm", LLMSetting, derialized
            )
            self.assertEqual(llm, deserialized)
        finally:
            clean_cryptex_with_attrs(
                self._app_name, build_setting_attrs(self._app_name, "llm", "api_key")
            )


class TestSettingsSerializer(unittest.TestCase):
    _app_name = "__flexplorer_unittest__"

    def tearDown(self):
        clean_cryptex(self._app_name)

    def test_no_llms(self):
        settings_path = os.path.join(
            tempfile.gettempdir(), f"settings_{time.time_ns()}.ini"
        )
        try:
            settings = Settings()
            settings.recent.open_file_dirpath = _random_chars(1, 10)
            save_settings(settings, settings_path, app_name=self._app_name)
            loaded = load_settings(settings_path, app_name=self._app_name)
            self.assertEqual(settings, loaded)
        finally:
            os.remove(settings_path)

    def test_one_llm(self):
        settings_path = os.path.join(
            tempfile.gettempdir(), f"settings_{time.time_ns()}.ini"
        )

        settings = Settings()
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
        save_settings(
            settings, settings_filepath=settings_path, app_name=self._app_name
        )
        try:
            loaded = load_settings(
                settings_filepath=settings_path, app_name=self._app_name
            )
            self.assertEqual(settings, loaded)
        finally:
            os.remove(settings_path)
            clean_cryptex_with_attrs(
                self._app_name,
                build_setting_attrs(
                    self._app_name, "llms_" + settings.llms[0].unique_code, "api_key"
                ),
            )

    def test_multi_llms(self):
        settings_path = os.path.join(
            tempfile.gettempdir(), f"settings_{time.time_ns()}.ini"
        )

        settings = Settings()
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
        save_settings(settings, settings_path, app_name=self._app_name)

        try:
            loaded = load_settings(
                settings_filepath=settings_path, app_name=self._app_name
            )
            self.assertEqual(settings, loaded)
        finally:
            os.remove(settings_path)
            for llm in settings.llms:
                clean_cryptex_with_attrs(
                    self._app_name,
                    build_setting_attrs(
                        self._app_name, "llms_" + llm.unique_code, "api_key"
                    ),
                )

    @unittest.mock.patch("flexplorer.settings.clean_cryptex_with_attrs")
    def test_mock_clean_cryptex(self, mocked):
        settings_path = os.path.join(
            tempfile.gettempdir(), f"settings_{time.time_ns()}.ini"
        )

        pre_settings = Settings()
        pre_settings.recent.open_file_dirpath = _random_chars(1, 10)
        for _ in range(random.randint(3, 10)):
            pre_settings.llms.append(
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
        save_settings(pre_settings, settings_path, app_name=self._app_name)

        reserved_llms: List[LLMSetting] = []
        try:
            new_settings = copy.deepcopy(pre_settings)
            new_settings.llms = []
            deleted_llms: List[LLMSetting] = []
            for idx, llm in enumerate(pre_settings.llms):
                if idx % 2 == 0:
                    new_settings.llms.append(llm)
                    reserved_llms.append(llm)
                else:
                    deleted_llms.append(llm)
            save_settings(
                new_settings,
                settings_path,
                previous_settings=pre_settings,
                app_name=self._app_name,
            )

            deleted_attrs_list: List[OrderedDict] = []
            for llm in deleted_llms:
                attrs = build_setting_attrs(
                    self._app_name, "llms_" + llm.unique_code, "api_key"
                )
                deleted_attrs_list.append(attrs)
            mocked.assert_has_calls(
                [
                    unittest.mock.call(self._app_name, attrs)
                    for attrs in deleted_attrs_list
                ]
            )
            self.assertEqual(mocked.call_count, len(deleted_llms))

        finally:
            os.remove(settings_path)
            for llm in pre_settings.llms:
                attrs = build_setting_attrs(
                    self._app_name, "llms_" + llm.unique_code, "api_key"
                )
                clean_cryptex_with_attrs(self._app_name, attrs)
