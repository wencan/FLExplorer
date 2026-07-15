import json
import urllib.parse
import asyncio
import ssl
from typing import Any, Dict, Literal, AsyncGenerator, Tuple


class LLMApiError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self):
        return f"{self.code}: {self.message}"


default_ssl_context = ssl.create_default_context()


async def _receive_response_body(
    reader: asyncio.StreamReader, content_length: int, transfer_encoding: str
) -> AsyncGenerator[bytes]:
    if content_length > 0:
        bs = await reader.readexactly(content_length)
        yield bs
    elif transfer_encoding.startswith("chunked"):
        while True:
            # read chunk length
            line_bs = await reader.readline()
            if len(line_bs) == 0:
                break
            line = line_bs.decode("utf-8", errors="ignore")
            chunk_length_str = line.split(";", 1)[0]
            chunk_length = int(chunk_length_str, 16)
            if chunk_length == 0:  # end
                # read tailer \r\n or \n\n
                await reader.readline()
                break

            # read chunk
            chunk_bs = await reader.readexactly(chunk_length)
            yield chunk_bs

            # read \r\n or \n\n
            await reader.readexactly(2)
    else:
        # fallback
        # read until EOF
        bs = await reader.read()
        yield bs


async def _receive_complete_response_body(
    reader: asyncio.StreamReader, content_length: int, transfer_encoding: str
):
    bs = bytearray()
    async for b in _receive_response_body(reader, content_length, transfer_encoding):
        bs.extend(b)
    return bs


def _parse_llm_error_response(
    status_code: int, reason: str, resp_body: str
) -> LLMApiError:
    # example:
    # {"code":20012,"message":"Model does not exist. Please check it carefully.","data":null}
    # {"error":{"message":"Authentication Fails, Your api key: ****3750 is invalid","type":"authentication_error","param":null,"code":"invalid_request_error"}}
    # {"error":{"message":"The supported API model names are deepseek-v4-pro or deepseek-v4-flash, but you passed test-1.0-flash.","type":"invalid_request_error","param":null,"code":"invalid_request_error"}}
    # {"error":"Invalid username or password."}
    error_code = ""
    error_message = ""
    try:
        resp_dict = json.loads(resp_body)
        if isinstance(resp_dict, dict):
            error = resp_dict.get("error")
            error_dict = {}
            error_desc = ""
            if isinstance(error, dict):
                error_dict = error
            if isinstance(error, str):
                error_desc = error

            error_code = resp_dict.get("code") or error_dict.get("code")
            error_message = (
                resp_dict.get("message") or error_dict.get("message") or error_desc
            )
        elif isinstance(resp_dict, str):
            error_message = resp_body
    except json.JSONDecodeError:
        error_message = resp_body

    if error_code in ("", None):
        error_code = str(status_code)
    if not isinstance(error_code, str):
        error_code = str(error_code)
    if error_message == "":
        error_message = reason or "error"

    return LLMApiError(error_code, error_message)


async def _parse_llm_content_response(resp_body: str) -> str:
    try:
        resp_dict = json.loads(resp_body)
        choice = resp_dict["choices"][0]
        message = choice.get("delta") or choice.get("message")
        if message is None:
            raise LookupError("message is None")
        content = message.get("content")
        reasoning_content = message.get("reasoning_content")
        if content is not None:
            return content
        if reasoning_content is not None:
            pass
        raise LookupError("no content")
    except (json.JSONDecodeError, LookupError) as e:
        raise Exception(
            "The response is not in the expected format: " + resp_body
        ) from e


async def _parse_llm_stream_response(
    receiver: AsyncGenerator[bytes],
) -> AsyncGenerator[str]:
    bs = bytearray()
    async for chunk_bs in receiver:
        bs.extend(chunk_bs)
        while b"\n" in bs:
            line_bs, _, bs = bs.partition(b"\n")
            if len(line_bs) == 0:
                continue
            line = line_bs.decode("utf-8", errors="ignore")
            line = line.strip()
            if line.startswith("data: "):
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                if data == "":
                    continue

                try:
                    data_dict = json.loads(data)
                    choices = data_dict["choices"]
                    if not choices:
                        # choices is []
                        break
                    delta = choices[0]["delta"]
                except (json.JSONDecodeError, LookupError) as e:
                    raise Exception(
                        "The chunk is not in the expected format: " + data
                    ) from e
                content = delta.get("content")
                reasoning_content = delta.get("reasoning_content")
                if content is not None:
                    yield content
                if reasoning_content is not None:
                    pass


async def chat_completion(
    base_url: str,
    api_key: str | None,
    req_body: Dict[str, Any],
    stream: bool = False,
    connection_timeout: float = 5.0,
) -> Tuple[int, str, Dict[str, str], AsyncGenerator[str] | None]:
    completions_url = urllib.parse.urljoin(base_url, "/chat/completions")
    url = urllib.parse.urlparse(completions_url)
    if url.scheme not in ("http", "https"):
        raise NotImplementedError(f"Unsupported scheme: {url.scheme}")
    is_ssl = url.scheme == "https"
    host = url.hostname
    port = url.port or (443 if is_ssl else 80)
    path = url.path or "/"

    ssl_context = None
    server_hostname = None
    if is_ssl:
        ssl_context = ssl.create_default_context()
        server_hostname = host

    if stream != bool(req_body.get("stream")):
        raise ValueError("stream mismatch")

    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(
            host, port, ssl=ssl_context, server_hostname=server_hostname
        ),
        connection_timeout,
    )
    try:
        req_start_line = f"POST {path} HTTP/1.1"
        req_body_bs = json.dumps(req_body).encode("utf-8")
        accept = "application/json" if not stream else "text/event-stream"
        req_headers = [
            ("Host", host if port in (80, 443) else f"{host}:{port}"),
            ("Connection", "close"),
            ("Authorization", f"Bearer {api_key}"),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(req_body_bs))),
            ("Accept", accept),
            (
                "User-Agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python-Requests/2.0",
            ),
        ]

        # start line in request
        writer.write(req_start_line.encode("utf-8"))
        writer.write(b"\r\n")
        # headers in request
        for k, v in req_headers:
            writer.write(f"{k}: {v}\r\n".encode("utf-8"))
        writer.write(b"\r\n")
        # body in request
        writer.write(req_body_bs)
        # go!
        await writer.drain()

        # start line in response
        start_line_bs = await reader.readline()
        start_line = start_line_bs.decode("utf-8", errors="ignore")
        start_line = start_line.rstrip()
        parts = start_line.split(" ", 2)
        status_code = int(parts[1])
        reason = parts[2]

        # headers in response
        resp_headers = {}
        while True:
            line_bs = await reader.readline()
            if len(line_bs) == 0:
                break

            line = line_bs.decode("utf-8", errors="ignore")
            line = line.rstrip()
            if len(line) == 0:
                break

            k, v = line.split(":", 1)
            resp_headers[k.strip().lower()] = v.strip()

    except Exception as e:
        writer.close()
        await writer.wait_closed()
        raise e
    else:
        transfer_encoding = resp_headers.get("transfer-encoding", "")
        content_length = int(resp_headers.get("content-length", "0"))

        # body in response
        if status_code != 200:
            try:
                bs = await _receive_complete_response_body(
                    reader, content_length, transfer_encoding
                )
                resp_body = bs.decode("utf-8", errors="ignore")
                raise _parse_llm_error_response(status_code, reason, resp_body)
            finally:
                writer.close()
                await writer.wait_closed()
        elif stream:

            async def gen_stream():
                try:
                    receiver = _receive_response_body(
                        reader, content_length, transfer_encoding
                    )
                    async for chunk in _parse_llm_stream_response(receiver):
                        yield chunk
                finally:
                    writer.close()
                    await writer.wait_closed()

            return status_code, reason, resp_headers, gen_stream()
        else:  # no stream

            async def gen_content():
                try:
                    bs = await _receive_complete_response_body(
                        reader, content_length, transfer_encoding
                    )
                    resp_body = bs.decode("utf-8", errors="ignore")
                    yield await _parse_llm_content_response(resp_body)
                finally:
                    writer.close()
                    await writer.wait_closed()

            return status_code, reason, resp_headers, gen_content()


def build_llm_translate_request(
    provider: Literal["deepseek", "siliconflow", "openrouter"],
    model: str,
    thinking: bool,
    stream: bool,
    src: str,
    target_lang: str,
) -> Dict:
    prompt = f"""You are a professional {target_lang} native translator who needs to fluently translate text into {target_lang}.

## Translation Rules
1. Output only the translated content, without explanations or additional content (such as "Here's the translation:" or "Translation as follows:")
2. The returned translation must maintain exactly the same number of paragraphs and format as the original text
3. If the text contains HTML tags, consider where the tags should be placed in the translation while maintaining fluency
4. For content that should not be translated (such as proper nouns, code, etc.), keep the original text.
"""
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": prompt,
            },
            {"role": "user", "content": src},
        ],
        "thinking": {"type": "disabled"},
        "stream": stream,
    }

    if provider == "deepseek":
        if thinking:
            body["thinking"] = {"type": "enabled"}
            body["reasoning_effort"] = "high"  # higt or max
        else:
            body["thinking"] = {"type": "disabled"}
    elif provider == "siliconflow":
        if thinking:
            body["enable_thinking"] = True
            body["reasoning_effort"] = "high"  # higt or max
        else:
            body["enable_thinking"] = False
    elif provider == "openrouter":
        # https://openrouter.ai/docs/guides/best-practices/reasoning-tokens#reasoning-effort-level
        if thinking:
            body["reasoning"] = {
                "enabled": True,
            }
        else:
            body["reasoning"] = {
                "effort": "none",
            }

    return body
