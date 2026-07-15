import asyncio
import datetime
import json
import random
import secrets
import string
import threading
import time
import unittest
import uuid

from typing import Tuple
from flexplorer.llm import LLMApiError, build_llm_translate_request, chat_completion


class LLMTestServer:
    """
    ECHO server compliant with the LLM protocol.
    """

    def __init__(self):
        self._host = "127.0.0.1"
        self._port = 0  # auto assigned
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready_event = threading.Event()
        self._exit_event = asyncio.Event()

        self._api_key = secrets.token_hex(16)
        self._model = "test-1.0"
        # This fingerprint represents the backend configuration that the model runs with.
        self._system_fingerprint = f"fp_{secrets.token_hex(5)}"

    def start(self):
        self._thread = threading.Thread(target=self._thread_target)
        self._thread.start()
        self._ready_event.wait()

    def _thread_target(self):
        self._loop = asyncio.new_event_loop()

        async def run():
            server = await asyncio.start_server(
                self._client_connected_cb, self._host, self._port
            )
            _, self._port = server.sockets[0].getsockname()
            await server.start_serving()
            self._ready_event.set()

            await self._exit_event.wait()

            server.close()
            await server.wait_closed()

        self._loop.run_until_complete(run())
        self._loop.close()

    def stop(self):
        assert self._loop
        self._loop.call_soon_threadsafe(self._exit_event.set)
        assert self._thread
        self._thread.join()

    def host_and_port(self) -> Tuple[str, int]:
        return self._host, self._port

    def model(self) -> str:
        return self._model

    def api_key(self) -> str:
        return self._api_key

    async def _client_connected_cb(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        status_code: int = 200
        reason: str = "OK"
        error_code = ""
        error_message = ""

        # parse start line
        path = ""
        start_line_bs = await reader.readline()
        start_line = start_line_bs.decode("utf-8", errors="ignore")
        parts = start_line.split()
        if len(parts) == 3:
            method, path, protocol = parts
            if method != "POST":
                status_code = 405
                reason = "Method Not Allowed"
        else:
            status_code = 400
            reason = "Bad Request"

        # parse headers
        content_length: int = 0
        while True:
            line_bs = await reader.readline()
            line = line_bs.decode("utf-8", errors="ignore")
            line = line.strip()
            if line == "":
                break

            try:
                k, v = line.split(":", 1)
                k = k.lower()
                v = v.strip()
                if k == "content-length":
                    content_length = int(v)
                elif k == "authorization":
                    if v != f"Bearer {self._api_key}":
                        status_code = 401
                        reason = "Unauthorized"
                        break
            except ValueError:
                status_code = 400
                reason = "Bad Request"

        # parse body
        stream: bool = False
        user_content: str = ""
        if content_length > 0:
            req_body_bs = await reader.readexactly(content_length)
            try:
                req_body = req_body_bs.decode("utf-8", errors="ignore")
                req_body_dict = json.loads(req_body)
                model = req_body_dict.get("model", "")
                stream = req_body_dict.get("stream", False)
                messages = req_body_dict.get("messages", [])
                for message in messages:
                    if message.get("role") == "user":
                        user_content = message.get("content", "")

                if model != self._model:
                    status_code = 400
                    reason = "Bad Request"
                    error_code = "invalid_model_name"
                    error_message = "Invalid model name"
            except (UnicodeDecodeError, json.JSONDecodeError, LookupError):
                status_code = 400
                reason = "Bad Request"
        else:
            status_code = 400
            reason = "Bad Request"

        # This fingerprint represents the backend configuration that the model runs with.
        request_id = f"chatcmpl-{uuid.uuid4()}"

        if status_code != 200:
            error_code = error_code or str(status_code)
            error_message = error_message or reason
            await self._reply_error(
                status_code, reason, error_code, error_message, writer
            )
        else:
            if stream:
                await self._reply_stream(request_id, user_content, writer)
            elif path.startswith("/chunked"):
                await self._reply_chunked_content(request_id, user_content, writer)
            else:
                await self._reply_content(request_id, user_content, writer)

        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def _reply_content(
        self, request_id: str, user_content: str, writer: asyncio.StreamWriter
    ):
        content_tpl = string.Template(
            """{"id":"$request_id","choices":[{"finish_reason":"stop","index":0,"message":{"content":"$content","role":"assistant"}}],"created":$created,"model":"$model","system_fingerprint":"$system_fingerprint","object":"chat.completion","usage":{"total_tokens":148,"completion_tokens":78,"completion_tokens_details":{"accepted_prediction_tokens":0,"rejected_prediction_tokens":0,"reasoning_tokens":37},"prompt_tokens":70,"prompt_tokens_details":{"cached_tokens":0}},"time_info":{"created":$time_info_created,"queue_time":0.033054449,"prompt_time":0.001747039,"completion_time":0.048333766,"total_time":0.08599734306335449}}"""
        )
        content = content_tpl.substitute(
            request_id=request_id,
            content=json.dumps(user_content)[1:-1],  # escape characters such as \n
            created=int(time.time()),
            model=self._model,
            system_fingerprint=self._system_fingerprint,
            time_info_created=time.time(),
        )
        bs = content.encode("utf-8")

        writer.write(b"HTTP/1.1 200 OK\r\n")
        now = datetime.datetime.now(datetime.UTC)
        now_s = now.strftime("%a, %d %b %Y %H:%M:%S GMT")
        writer.write(f"Date: {now_s}\r\n".encode("utf-8"))
        writer.write(b"Content-Type: application/json\r\n")
        writer.write(f"Content-Length: {len(bs)}\r\n".encode("utf-8"))
        writer.write(b"Connection: close\r\n")
        writer.write(b"\r\n")
        writer.write(bs)
        writer.write(b"\r\n")

    async def _reply_chunked_content(
        self, request_id: str, user_content: str, writer: asyncio.StreamWriter
    ):
        content_tpl = string.Template(
            """{"id":"$request_id","choices":[{"finish_reason":"stop","index":0,"message":{"content":"$content","role":"assistant"}}],"created":$created,"model":"$model","system_fingerprint":"$system_fingerprint","object":"chat.completion","usage":{"total_tokens":148,"completion_tokens":78,"completion_tokens_details":{"accepted_prediction_tokens":0,"rejected_prediction_tokens":0,"reasoning_tokens":37},"prompt_tokens":70,"prompt_tokens_details":{"cached_tokens":0}},"time_info":{"created":$time_info_created,"queue_time":0.033054449,"prompt_time":0.001747039,"completion_time":0.048333766,"total_time":0.08599734306335449}}"""
        )
        content = content_tpl.substitute(
            request_id=request_id,
            content=json.dumps(user_content)[1:-1],  # escape characters such as \n
            created=int(time.time()),
            model=self._model,
            system_fingerprint=self._system_fingerprint,
            time_info_created=time.time(),
        )
        bs = content.encode("utf-8")

        writer.write(b"HTTP/1.1 200 OK\r\n")
        now = datetime.datetime.now(datetime.UTC)
        now_s = now.strftime("%a, %d %b %Y %H:%M:%S GMT")
        writer.write(f"Date: {now_s}\r\n".encode("utf-8"))
        writer.write(b"Content-Type: application/json\r\n")
        writer.write(b"Transfer-Encoding: chunked\r\n")
        writer.write(b"Connection: close\r\n")
        writer.write(b"\r\n")

        # split the content into chunks
        total_length = len(bs)
        chunks_number = random.randint(1, 3)
        chunk_size = total_length // chunks_number
        chunks_size = [chunk_size] * chunks_number
        chunks_size[-1] = total_length - chunk_size * (chunks_number - 1)
        offset = 0
        for current_size in chunks_size:
            chunk = bs[offset : offset + current_size]
            writer.write(f"{len(chunk):x}\r\n".encode("utf-8"))
            writer.write(chunk)
            writer.write(b"\r\n")

            offset += current_size
        # write the finish chunk
        writer.write(b"0\r\n")
        writer.write(b"\r\n")

    async def _reply_stream(
        self, request_id: str, user_content: str, writer: asyncio.StreamWriter
    ):
        writer.write(b"HTTP/1.1 200 OK\r\n")
        now = datetime.datetime.now(datetime.UTC)
        now_s = now.strftime("%a, %d %b %Y %H:%M:%S GMT")
        writer.write(f"Date: {now_s}\r\n".encode("utf-8"))
        writer.write(b"Content-Type: text/event-stream\r\n")
        writer.write(b"Transfer-Encoding: chunked\r\n")
        writer.write(b"Connection: close\r\n")
        writer.write(b"\r\n")

        # split the content into lines
        data_lines = []
        while len(user_content) > 0:
            line_length = random.randint(1, 3)
            line_length = min(line_length, len(user_content))
            data_tpl = string.Template(
                """{"id":"$request_id","choices":[{"delta":{"content":"$content"},"index":0}],"created":$created,"model":"$model","system_fingerprint":"$system_fingerprint","object":"chat.completion.chunk"}"""
            )
            data = data_tpl.substitute(
                request_id=request_id,
                content=json.dumps(user_content[:line_length])[1:-1],
                created=int(time.time()),
                model=self._model,
                system_fingerprint=self._system_fingerprint,
            )
            line = f"data: {data}"
            data_lines.append(line)
            user_content = user_content[line_length:]

        # add finish line
        finish_tpl = string.Template(
            """{"id":"$request_id","choices":[{"delta":{"content":""},"finish_reason":"stop","index":0}],"created":$created,"model":"$model","system_fingerprint":"$system_fingerprint","object":"chat.completion.chunk","usage":{"total_tokens":147,"completion_tokens":77,"completion_tokens_details":{"accepted_prediction_tokens":0,"rejected_prediction_tokens":0,"reasoning_tokens":48},"prompt_tokens":70,"prompt_tokens_details":{"cached_tokens":0}},"time_info":{"created":$time_info_created,"queue_time":0.004378409,"prompt_time":0.00156686,"completion_time":0.043500814,"total_time":0.053266048431396484}}"""
        )
        finish_data = finish_tpl.substitute(
            request_id=request_id,
            created=int(time.time()),
            model=self._model,
            system_fingerprint=self._system_fingerprint,
            time_info_created=time.time(),
        )
        data_lines.append(f"data: {finish_data}")
        data_lines.append("data: [DONE]")

        # write chunks
        while len(data_lines) > 0:
            num = random.randint(1, 5)
            num = min(num, len(data_lines))
            towrite_lines = data_lines[:num]
            data_lines = data_lines[num:]

            # write the chunk
            lines_bs = [line.encode("utf-8") for line in towrite_lines]
            chunk_length = sum(len(line_bs) + 2 for line_bs in lines_bs)
            writer.write(f"{chunk_length:x}\r\n".encode("utf-8"))
            for line_bs in lines_bs:
                writer.write(line_bs)
                writer.write(b"\n\n")
            writer.write(b"\r\n")
            await writer.drain()
        # write the finish chunk
        writer.write(b"0\r\n")
        writer.write(b"\r\n")

    async def _reply_error(
        self,
        status_code: int,
        reason: str,
        error_code: str,
        error_message: str,
        writer: asyncio.StreamWriter,
    ):
        error_tpl = string.Template(
            """{"error":{"code":$error_code,"message":$error_message}}"""
        )
        error = error_tpl.substitute(error_code=error_code, error_message=error_message)
        error_bs = error.encode("utf-8")

        writer.write(f"HTTP/1.1 {status_code} {reason}\r\n".encode("utf-8"))
        now = datetime.datetime.now(datetime.UTC)
        now_s = now.strftime("%a, %d %b %Y %H:%M:%S GMT")
        writer.write(f"Date: {now_s}\r\n".encode("utf-8"))
        writer.write(b"Content-Type: application/json\r\n")
        writer.write(f"Content-Length: {len(error_bs)}\r\n".encode("utf-8"))
        writer.write(b"Connection: close\r\n")
        writer.write(b"\r\n")
        writer.write(error_bs)
        writer.write(b"\r\n")


class TestLLMApi(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._server = LLMTestServer()
        self._server.start()

        self._host, self._port = self._server.host_and_port()

    def tearDown(self):
        self._server.stop()

    async def test_content(self):
        base_url = f"http://{self._host}:{self._port}/content"
        api_key = self._server.api_key()
        model = self._server.model()
        src = "".join(random.choices("张三李四王五" + string.printable, k=10))
        req_body = build_llm_translate_request(
            provider="deepseek",
            model=model,
            thinking=False,
            stream=False,
            src=src,
            target_lang="中文",
        )
        status_code, reason, headers, content_gen = await chat_completion(
            base_url, api_key, req_body, stream=False
        )
        assert status_code == 200
        assert reason == "OK"
        assert content_gen

        dst = ""
        async for chunk in content_gen:
            dst += chunk
        assert dst == src  # just echo

    async def test_chunked_content(self):
        base_url = f"http://{self._host}:{self._port}/chunked"
        api_key = self._server.api_key()
        model = self._server.model()
        src = "".join(random.choices("张三李四王五" + string.printable, k=100))
        req_body = build_llm_translate_request(
            provider="deepseek",
            model=model,
            thinking=False,
            stream=False,
            src=src,
            target_lang="中文",
        )
        status_code, reason, headers, content_gen = await chat_completion(
            base_url, api_key, req_body, stream=False
        )
        assert status_code == 200
        assert reason == "OK"
        assert content_gen

        dst = ""
        async for chunk in content_gen:
            dst += chunk
        assert dst == src  # just echo

    async def test_stream(self):
        base_url = f"http://{self._host}:{self._port}/stream"
        api_key = self._server.api_key()
        model = self._server.model()
        src = "".join(random.choices("张三李四王五" + string.printable, k=100))
        req_body = build_llm_translate_request(
            provider="deepseek",
            model=model,
            thinking=False,
            stream=True,
            src=src,
            target_lang="中文",
        )
        status_code, reason, headers, content_gen = await chat_completion(
            base_url, api_key, req_body, stream=True
        )
        assert status_code == 200
        assert reason == "OK"
        assert content_gen

        dst = ""
        async for chunk in content_gen:
            dst += chunk
        assert dst == src  # just echo

    async def test_invalid_key(self):
        base_url = f"http://{self._host}:{self._port}/content"
        api_key = secrets.token_hex(15)
        model = self._server.model()
        src = "".join(random.choices("张三李四王五" + string.printable, k=10))
        req_body = build_llm_translate_request(
            provider="deepseek",
            model=model,
            thinking=False,
            stream=False,
            src=src,
            target_lang="中文",
        )
        with self.assertRaises(LLMApiError):
            await chat_completion(base_url, api_key, req_body, stream=False)

    async def test_mismatch_model(self):
        base_url = f"http://{self._host}:{self._port}/content"
        api_key = self._server.api_key()
        model = "text-100.999"
        src = "".join(random.choices("张三李四王五" + string.printable, k=10))
        req_body = build_llm_translate_request(
            provider="deepseek",
            model=model,
            thinking=False,
            stream=False,
            src=src,
            target_lang="中文",
        )
        with self.assertRaises(LLMApiError):
            await chat_completion(base_url, api_key, req_body, stream=False)
