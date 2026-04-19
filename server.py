from http.server import BaseHTTPRequestHandler, HTTPServer
import asyncio
import threading
import json
import struct
import os
import uuid
import re
from websockets.asyncio.server import serve as ws_serve
from websockets.exceptions import ConnectionClosed
import datetime
from datetime import timezone
import hashlib
import base64

import threading

# 存储所有连接的客户端
connected_clients = set()

# ========== 文件数据库 ==========
ITEMS_FILE = "items.json"
items_lock = threading.Lock()  # 文件读写锁，防止并发冲突


def load_items():
    """从 items.json 读取数据"""
    try:
        with open(ITEMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 转为 {id: item} 格式，方便按 id 查找
            return {str(item["id"]): item for item in data}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_items(items_dict):
    """将数据写入 items.json（只存列表）"""
    with open(ITEMS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(items_dict.values()), f, ensure_ascii=False, indent=2)


# 初始加载
items = load_items()  # 相当于 "连接数据库"

print(f"📦 已从 {ITEMS_FILE} 加载 {len(items)} 条记录")

# 模拟用户会话 (用于演示 Cookie)
sessions = {}

# ========== 报文拦截日志 ==========
SEP = "═" * 70

def log_http(direction, content):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"\n╔{SEP}╗")
    print(f"║ [{ts}] 📡 HTTP {direction}")
    print(f"╚{SEP}╝")
    print(content)
    print(f"╔{SEP}╗\n")

def log_ws(direction, content):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"\n╔{SEP}╗")
    print(f"║ [{ts}] 🔌 WS {direction}")
    print(f"╚{SEP}╝")
    print(content)
    print(f"╔{SEP}╗\n")

# ==========================================================================
# WebSocket 帧构造与解析 (RFC 6455)
# ==========================================================================

OPCODE_NAMES = {
    0: "continuation", 1: "text", 2: "binary",
    8: "close", 9: "ping", 10: "pong",
}

def build_ws_frame(fin, opcode, payload, mask=False):
    """按照 RFC 6455 构造一个完整的 WebSocket 帧（原始字节）。"""
    frame = bytearray()
    byte0 = (fin << 7) | opcode
    frame.append(byte0)
    payload_bytes = payload.encode("utf-8") if isinstance(payload, str) else payload
    length = len(payload_bytes)
    mask_bit = 0x80 if mask else 0x00
    if length <= 125:
        frame.append(mask_bit | length)
    elif length <= 65535:
        frame.append(mask_bit | 126)
        frame.extend(struct.pack("!H", length))
    else:
        frame.append(mask_bit | 127)
        frame.extend(struct.pack("!Q", length))
    if mask:
        masking_key = os.urandom(4)
        frame.extend(masking_key)
        masked = bytearray(payload_bytes)
        for i in range(len(masked)):
            masked[i] ^= masking_key[i % 4]
        frame.extend(masked)
    else:
        frame.extend(payload_bytes)
    return bytes(frame)


def explain_ws_frame(raw_bytes, direction_label):
    """将 WebSocket 帧的原始字节逐字段拆解，返回可读的完整报文结构说明。"""
    lines = []
    lines.append(f"方向: {direction_label}")
    lines.append(f"帧总长度: {len(raw_bytes)} 字节")

    byte0 = raw_bytes[0]
    fin    = (byte0 >> 7) & 1
    rsv1   = (byte0 >> 6) & 1
    rsv2   = (byte0 >> 5) & 1
    rsv3   = (byte0 >> 4) & 1
    opcode = byte0 & 0x0F
    op_name = OPCODE_NAMES.get(opcode, f"reserved({opcode})")

    lines.append("")
    lines.append(f"── 第1字节 (0x{byte0:02X}) ──")
    lines.append(f"  FIN    = {fin}  ({'最后一帧' if fin else '后续还有帧'})")
    lines.append(f"  RSV1   = {rsv1}")
    lines.append(f"  RSV2   = {rsv2}")
    lines.append(f"  RSV3   = {rsv3}")
    lines.append(f"  Opcode = {opcode} ({op_name})")
    lines.append(f"  二进制 = {byte0:08b}")

    byte1 = raw_bytes[1]
    mask  = (byte1 >> 7) & 1
    plen  = byte1 & 0x7F

    lines.append("")
    lines.append(f"── 第2字节 (0x{byte1:02X}) ──")
    lines.append(f"  MASK          = {mask}  ({'客户端帧，需掩码' if mask else '服务端帧，无掩码'})")
    lines.append(f"  Payload len   = {plen}")

    offset = 2
    if plen == 126:
        real_len = struct.unpack("!H", raw_bytes[2:4])[0]
        lines.append(f"  扩展长度(126) = {real_len} 字节  (2字节扩展)")
        offset = 4
    elif plen == 127:
        real_len = struct.unpack("!Q", raw_bytes[2:10])[0]
        lines.append(f"  扩展长度(127) = {real_len} 字节  (8字节扩展)")
        offset = 10
    else:
        real_len = plen

    if mask:
        mk = raw_bytes[offset:offset+4]
        lines.append("")
        lines.append("── Masking-Key (4字节) ──")
        lines.append(f"  {mk.hex(' ')}")
        offset += 4

    payload_raw = raw_bytes[offset:]
    lines.append("")
    lines.append(f"── Payload 数据 ({len(payload_raw)} 字节) ──")

    if mask:
        unmasked = bytearray(payload_raw)
        mk = raw_bytes[offset-4:offset]
        for i in range(len(unmasked)):
            unmasked[i] ^= mk[i % 4]
        payload_display = bytes(unmasked)
    else:
        payload_display = payload_raw

    try:
        text = payload_display.decode("utf-8")
        lines.append(f"  文本: {text}")
    except Exception:
        lines.append("  (非UTF-8文本)")

    hex_parts = [f"{payload_display[i]:02x}" for i in range(min(len(payload_display), 64))]
    hex_str = " ".join(hex_parts)
    if len(payload_display) > 64:
        hex_str += " ..."
    lines.append(f"  Hex : {hex_str}")

    lines.append("")
    lines.append("── 完整帧 Hex Dump ──")
    for i in range(0, len(raw_bytes), 16):
        chunk = raw_bytes[i:i+16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"  {i:04x}  {hex_part:<48s}  {ascii_part}")

    return "\n".join(lines)

# ========== WebSocket 握手拦截 ==========
WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

async def process_request(connection, request):
    req_lines = []
    req_lines.append(f"GET {request.path} HTTP/1.1")
    for name, value in request.headers.raw_items():
        req_lines.append(f"{name}: {value}")
    log_ws("握手请求 ◀ (HTTP Upgrade)", "\n".join(req_lines))

    key = request.headers.get("Sec-WebSocket-Key", "")
    accept_val = base64.b64encode(
        hashlib.sha1((key + WS_MAGIC).encode()).digest()
    ).decode()

    resp_lines = []
    resp_lines.append("HTTP/1.1 101 Switching Protocols")
    resp_lines.append("Upgrade: websocket")
    resp_lines.append("Connection: Upgrade")
    resp_lines.append(f"Sec-WebSocket-Accept: {accept_val}")
    log_ws("握手响应 ▶ (101 Upgrade)", "\n".join(resp_lines))

    return None

# ========== WebSocket 服务端 ==========
async def websocket_server():
    async with ws_serve(
        websocket_handler,
        "localhost",
        8765,
        process_request=process_request,
    ):
        await asyncio.Future()

async def websocket_handler(websocket):
    print("✅ WebSocket 连接已建立（握手完成）")
    connected_clients.add(websocket)
    try:
        async for msg in websocket:
            raw_in = build_ws_frame(fin=1, opcode=1, payload=msg, mask=True)
            explanation = explain_ws_frame(raw_in, "客户端 → 服务端 (mask=True)")
            log_ws("接收帧 ◀ 完整报文结构", explanation)

            if msg == "start":
                print("🔄 开始推送进度 0~100")
                for i in range(0, 101):
                    payload = json.dumps({"progress": i})
                    if i in (0, 50, 100):
                        raw_out = build_ws_frame(fin=1, opcode=1, payload=payload, mask=False)
                        explanation = explain_ws_frame(raw_out, "服务端 → 客户端 (mask=False)")
                        log_ws("发送帧 ▶ 完整报文结构", explanation)
                    await websocket.send(payload)
                    await asyncio.sleep(0.05)
    except ConnectionClosed as e:
        close_payload = struct.pack("!H", e.code) + (e.reason or "").encode("utf-8")
        raw_close = build_ws_frame(fin=1, opcode=8, payload=close_payload, mask=True)
        explanation = explain_ws_frame(raw_close, "客户端 → 服务端 (关闭帧)")
        log_ws("关闭帧 ■ 完整报文结构", explanation)
    finally:
        connected_clients.discard(websocket)
        print("❌ 客户端已断开")

# ========== HTTP 服务器 ==========
class Handler(BaseHTTPRequestHandler):

    def _dump_request(self):
        """拦截并格式化 HTTP 请求报文，同时缓存 body 供后续使用。"""
        lines = []
        lines.append(f"{self.command} {self.path} {self.request_version}")
        for header, value in self.headers.items():
            lines.append(f"{header}: {value}")
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            # 读一次并缓存，避免后续再读时 rfile 已空
            raw_body = self.rfile.read(content_length)
            body = raw_body.decode("utf-8", errors="replace")
            self._cached_body = raw_body  # 缓存原始 bytes
            lines.append("")
            lines.append(body)
        else:
            self._cached_body = b""
            body = ""
        log_http("请求报文 ▶ 客户端 → 服务端", "\n".join(lines))
        return body

    def _get_body(self):
        """获取缓存的请求体（bytes），如果没缓存则返回 b"""""
        return getattr(self, '_cached_body', b"")

    def _dump_response(self, status_code, reason, extra_headers, body=""):
        """拦截并格式化 HTTP 响应报文（完整输出，不截断）"""
        lines = []
        lines.append(f"HTTP/1.1 {status_code} {reason}")
        # send_response 自动追加的标准头
        lines.append("Server: BaseHTTP/0.6 Python/3.x")
        lines.append(f"Date: {datetime.datetime.now(datetime.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')}")
        # 业务头 (按原始顺序)
        for k, v in extra_headers.items():
            lines.append(f"{k}: {v}")
        # 响应体 (完整输出，不截断)
        if body:
            lines.append("")
            lines.append(f"[响应体共 {len(body)} 字节]")
            lines.append(body)
        else:
            lines.append("(无响应体)")
        log_http("响应报文 ◀ 服务端 → 客户端", "\n".join(lines))

    def _send_json(self, code, reason, data, extra_headers=None):
        result = json.dumps(data, ensure_ascii=False)
        resp_headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(result.encode("utf-8"))),
            "Access-Control-Allow-Origin": "*",
        }
        if extra_headers:
            resp_headers.update(extra_headers)
        self.send_response(code)
        for k, v in resp_headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(result.encode("utf-8"))
        self._dump_response(code, reason, resp_headers, result)

    def _send_empty(self, code, reason, extra_headers=None):
        resp_headers = {"Content-Length": "0"}
        if extra_headers:
            resp_headers.update(extra_headers)
        self.send_response(code)
        for k, v in resp_headers.items():
            self.send_header(k, v)
        self.end_headers()
        self._dump_response(code, reason, resp_headers)

    # ========== OPTIONS (CORS 预检) ==========
    def do_OPTIONS(self):
        """处理 CORS 预检请求 (OPTIONS)"""
        self._dump_request()
        resp_headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "86400",
        }
        self.send_response(204)
        for k, v in resp_headers.items():
            self.send_header(k, v)
        self.end_headers()
        self._dump_response(204, "No Content", resp_headers)

    # ========== HEAD ==========
    def do_HEAD(self):
        """HEAD 方法：只返回响应头，不返回响应体"""
        self._dump_request()
        if self.path == "/":
            with open("upload.html", "r", encoding="utf-8") as f:
                body = f.read()
            resp_headers = {
                "Content-Type": "text/html; charset=utf-8",
                "Content-Length": str(len(body.encode("utf-8"))),
            }
            self.send_response(200)
            for k, v in resp_headers.items():
                self.send_header(k, v)
            self.end_headers()
            self._dump_response(200, "OK", resp_headers, "(HEAD: 无响应体)")
        else:
            self._send_empty(404, "Not Found")

    # ========== GET ==========
    def do_GET(self):
        self._dump_request()

        # ---- 首页 ----
        if self.path == "/":
            with open("upload.html", "r", encoding="utf-8") as f:
                body = f.read()
            resp_headers = {
                "Content-Type": "text/html; charset=utf-8",
                "Content-Length": str(len(body.encode("utf-8"))),
            }
            self.send_response(200)
            for k, v in resp_headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))
            self._dump_response(200, "OK", resp_headers, body)

        # ---- 查询用户名 (JSON API) ----
        elif self.path == "/query":
            self._send_json(200, "OK", {"username": "zhenhao_server"})

        # ---- 资源列表 (GET /items) ----
        elif self.path == "/items":
            self._send_json(200, "OK", {"items": list(items.values())})

        # ---- 单个资源 (GET /items/1) ----
        elif self.path.startswith("/items/"):
            item_id = self.path.split("/")[-1]
            if item_id in items:
                self._send_json(200, "OK", items[item_id])
            else:
                self._send_json(404, "Not Found", {"error": f"物品 {item_id} 不存在"})

        # ---- 301 永久重定向 ----
        elif self.path == "/redirect/301":
            resp_headers = {"Location": "/items"}
            self.send_response(301)
            for k, v in resp_headers.items():
                self.send_header(k, v)
            self.end_headers()
            self._dump_response(301, "Moved Permanently", resp_headers)

        # ---- 302 临时重定向 ----
        elif self.path == "/redirect/302":
            resp_headers = {"Location": "/items"}
            self.send_response(302)
            for k, v in resp_headers.items():
                self.send_header(k, v)
            self.end_headers()
            self._dump_response(302, "Found", resp_headers)

        # ---- 304 Not Modified (缓存演示) ----
        elif self.path == "/cache":
            if_none_match = self.headers.get("If-None-Match", "")
            etag = '"v1-abc123"'
            if if_none_match == etag:
                # 缓存未修改，返回 304 不带 body
                resp_headers = {"ETag": etag}
                self.send_response(304)
                for k, v in resp_headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self._dump_response(304, "Not Modified", resp_headers)
            else:
                result = json.dumps({"message": "这是缓存演示数据", "time": datetime.datetime.now().isoformat()}, ensure_ascii=False)
                resp_headers = {
                    "Content-Type": "application/json; charset=utf-8",
                    "Content-Length": str(len(result.encode("utf-8"))),
                    "ETag": etag,
                    "Cache-Control": "max-age=3600",
                }
                self.send_response(200)
                for k, v in resp_headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(result.encode("utf-8"))
                self._dump_response(200, "OK", resp_headers, result)

        # ---- 401 Unauthorized ----
        elif self.path == "/auth":
            auth = self.headers.get("Authorization", "")
            if auth == "Bearer my-secret-token":
                self._send_json(200, "OK", {"message": "认证成功！欢迎 zhenhao_server", "secret": "🎉 这是需要登录才能看到的数据"})
            else:
                self._send_json(401, "Unauthorized", {"error": "未认证，请提供 Authorization: Bearer my-secret-token"})

        # ---- 403 Forbidden ----
        elif self.path == "/forbidden":
            self._send_json(403, "Forbidden", {"error": "你没有权限访问此资源"})

        # ---- 500 Internal Server Error ----
        elif self.path == "/error/500":
            self._send_json(500, "Internal Server Error", {"error": "服务器内部错误（模拟）"})

        # ---- Cookie 演示: 设置 Cookie ----
        elif self.path == "/cookie/set":
            session_id = uuid.uuid4().hex[:8]
            sessions[session_id] = {"user": "zhenhao", "login_time": datetime.datetime.now().isoformat()}
            result = json.dumps({"message": "Cookie 已设置", "session_id": session_id}, ensure_ascii=False)
            resp_headers = {
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(result.encode("utf-8"))),
                "Set-Cookie": f"session_id={session_id}; Path=/; HttpOnly",
            }
            self.send_response(200)
            for k, v in resp_headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(result.encode("utf-8"))
            self._dump_response(200, "OK", resp_headers, result)

        # ---- Cookie 演示: 读取 Cookie ----
        elif self.path == "/cookie/get":
            cookie_str = self.headers.get("Cookie", "")
            cookies = {}
            if cookie_str:
                for part in cookie_str.split(";"):
                    part = part.strip()
                    if "=" in part:
                        k, v = part.split("=", 1)
                        cookies[k.strip()] = v.strip()
            session_id = cookies.get("session_id", "")
            if session_id and session_id in sessions:
                self._send_json(200, "OK", {"cookie": cookies, "session": sessions[session_id]})
            else:
                self._send_json(200, "OK", {"cookie": cookies, "session": None, "tip": "请先访问 /cookie/set 设置 Cookie"})

        # ---- Cookie 演示: 删除 Cookie ----
        elif self.path == "/cookie/clear":
            result = json.dumps({"message": "Cookie 已清除"}, ensure_ascii=False)
            resp_headers = {
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(result.encode("utf-8"))),
                "Set-Cookie": "session_id=; Path=/; Max-Age=0",
            }
            self.send_response(200)
            for k, v in resp_headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(result.encode("utf-8"))
            self._dump_response(200, "OK", resp_headers, result)

        # ---- 上传文件访问 ----
        elif self.path.startswith("/uploads/"):
            file_path = os.path.join(".", self.path.lstrip("/"))
            if os.path.isfile(file_path):
                ext = os.path.splitext(file_path)[1].lower()
                mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}.get(ext, "application/octet-stream")
                with open(file_path, "rb") as f:
                    data = f.read()
                resp_headers = {"Content-Type": mime, "Content-Length": str(len(data))}
                self.send_response(200)
                for k, v in resp_headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)
                self._dump_response(200, "OK", resp_headers, f"<图片 {len(data)} 字节>")
            else:
                self._send_empty(404, "Not Found")

        # ---- 静态资源 ----
        elif self.path.endswith(".js"):
            file_path = os.path.join(".", self.path.lstrip("/"))
            if os.path.isfile(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    body = f.read()
                resp_headers = {
                    "Content-Type": "application/javascript; charset=utf-8",
                    "Content-Length": str(len(body.encode("utf-8"))),
                }
                self.send_response(200)
                for k, v in resp_headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))
                self._dump_response(200, "OK", resp_headers, f"<JS {len(body.encode('utf-8'))} 字节>")
            else:
                self._send_empty(404, "Not Found")
        elif self.path.endswith(".css"):
            file_path = os.path.join(".", self.path.lstrip("/"))
            if os.path.isfile(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    body = f.read()
                resp_headers = {
                    "Content-Type": "text/css; charset=utf-8",
                    "Content-Length": str(len(body.encode("utf-8"))),
                }
                self.send_response(200)
                for k, v in resp_headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))
                self._dump_response(200, "OK", resp_headers, f"<CSS {len(body.encode('utf-8'))} 字节>")
            else:
                self._send_empty(404, "Not Found")
        else:
            self._send_empty(404, "Not Found")

    # ========== POST ==========
    def do_POST(self):
        if self.path == "/upload":
            content_type = self.headers.get("Content-Type", "")
            content_length = int(self.headers.get("Content-Length", 0))

            # 打印完整的 multipart 请求报文（含 boundary 结构预览）
            boundary_match = re.search(r'boundary=([^\s;]+)', content_type)
            if not boundary_match:
                self.send_error(400, "Missing boundary")
                return
            boundary = boundary_match.group(1).encode()
            req_lines = []
            req_lines.append(f"POST {self.path} {self.request_version}")
            for header, value in self.headers.items():
                req_lines.append(f"{header}: {value}")
            req_lines.append("")
            
            # 读取完整请求体用于日志展示
            raw_body = self._get_body() or self.rfile.read(content_length)
            if raw_body:
                # 尝试文本解码，能解则全显示（如 urlencoded/JSON）
                try:
                    body_text = raw_body.decode("utf-8", errors="strict")
                    req_lines.append(f"[请求体共 {content_length} 字节，以下为完整内容]")
                    req_lines.append("")
                    req_lines.append(body_text)
                except UnicodeDecodeError:
                    # 二进制数据（如图文件）显示前 3000 字节 hex 预览
                    preview_len = min(len(raw_body), 3000)
                    preview = raw_body[:preview_len]
                    req_lines.append(f"[请求体共 {content_length} 字节，二进制数据，以下为前 {preview_len} 字节 hex 预览]")
                    req_lines.append("")
                    req_lines.append(preview.hex(" ", 2))
                    if content_length > preview_len:
                        req_lines.append(f"... (省略 {content_length - preview_len} 字节二进制数据)")
            else:
                req_lines.append(f"[请求体共 {content_length} 字节]")
            log_http("请求报文 ▶ 客户端 → 服务端", "\n".join(req_lines))

            # 用已读取的 body（优先缓存，否则重新读）
            raw_body = self._get_body()
            if not raw_body:
                raw_body = self.rfile.read(content_length)
                self._cached_body = raw_body

            separator = b"--" + boundary
            parts = raw_body.split(separator)

            upload_dir = os.path.join(".", "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            saved_files = []

            for part in parts:
                if not part or part.strip() in (b"", b"--", b"\r\n"):
                    continue
                header_end = part.find(b"\r\n\r\n")
                if header_end == -1:
                    continue
                header_bytes = part[:header_end]
                data_bytes = part[header_end + 4:]
                if data_bytes.endswith(b"\r\n"):
                    data_bytes = data_bytes[:-2]

                header_str = header_bytes.decode("utf-8", errors="replace")
                fn_match = re.search(r'filename="([^"]*)"', header_str)
                if not fn_match:
                    continue
                filename = fn_match.group(1)
                if not filename:
                    continue

                name_match = re.search(r'name="([^"]*)"', header_str)
                field_name = name_match.group(1) if name_match else "file"

                ct_match = re.search(r'Content-Type:\s*(\S+)', header_str, re.IGNORECASE)
                mime_type = ct_match.group(1) if ct_match else "application/octet-stream"

                unique_name = f"{uuid.uuid4().hex[:8]}_{filename}"
                save_path = os.path.join(upload_dir, unique_name)
                with open(save_path, "wb") as f:
                    f.write(data_bytes)

                file_size = os.path.getsize(save_path)
                saved_files.append({
                    "original": filename,
                    "saved": unique_name,
                    "type": mime_type,
                    "size": file_size,
                    "url": f"/uploads/{unique_name}",
                })
                print(f"📸 文件已保存: {save_path} ({mime_type}, {file_size} 字节)")

            self._send_json(200, "OK", {"ok": True, "files": saved_files})

        # ---- POST /items (创建资源, 返回 201) ----
        elif self.path == "/items":
            body = self._dump_request()
            try:
                data = json.loads(body) if body else {}
                with items_lock:
                    new_id = str(max(int(k) for k in items.keys()) + 1) if items else "1"
                    new_item = {"id": new_id, "name": data.get("name", "未命名"), "price": data.get("price", 0)}
                    items[new_id] = new_item
                    save_items(items)
                self._send_json(201, "Created", new_item)
            except Exception:
                self._send_json(400, "Bad Request", {"error": "JSON 格式错误"})

        # ---- POST /form (x-www-form-urlencoded 表单提交) ----
        elif self.path == "/form":
            body = self._dump_request()
            # 解析 urlencoded: name=xxx&age=18
            fields = {}
            if body:
                for pair in body.split("&"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        from urllib.parse import unquote_plus
                        fields[unquote_plus(k)] = unquote_plus(v)
            self._send_json(200, "OK", {"message": "表单数据已接收", "fields": fields, "content_type": "application/x-www-form-urlencoded"})

        else:
            body = self._dump_request()
            self._send_json(405, "Method Not Allowed", {"error": f"POST {self.path} 不支持"})

    # ========== PUT (替换资源) ==========
    def do_PUT(self):
        self._dump_request()
        if self.path.startswith("/items/"):
            item_id = self.path.split("/")[-1]
            if item_id not in items:
                self._send_json(404, "Not Found", {"error": f"物品 {item_id} 不存在"})
                return
            body_bytes = self._get_body()
            try:
                data = json.loads(body_bytes.decode("utf-8") if body_bytes else "{}")
                with items_lock:
                    items[item_id] = {"id": item_id, "name": data.get("name", ""), "price": data.get("price", 0)}
                    save_items(items)
                self._send_json(200, "OK", items[item_id])
            except Exception:
                self._send_json(400, "Bad Request", {"error": "JSON 格式错误"})
        else:
            self._send_json(405, "Method Not Allowed", {"error": f"PUT {self.path} 不支持"})

    # ========== PATCH (部分更新) ==========
    def do_PATCH(self):
        self._dump_request()
        if self.path.startswith("/items/"):
            item_id = self.path.split("/")[-1]
            if item_id not in items:
                self._send_json(404, "Not Found", {"error": f"物品 {item_id} 不存在"})
                return
            body_bytes = self._get_body()
            try:
                data = json.loads(body_bytes.decode("utf-8") if body_bytes else "{}")
                with items_lock:
                    for k, v in data.items():
                        if k != "id":
                            items[item_id][k] = v
                    save_items(items)
                self._send_json(200, "OK", items[item_id])
            except Exception:
                self._send_json(400, "Bad Request", {"error": "JSON 格式错误"})
        else:
            self._send_json(405, "Method Not Allowed", {"error": f"PATCH {self.path} 不支持"})

    # ========== DELETE (删除资源) ==========
    def do_DELETE(self):
        self._dump_request()
        if self.path.startswith("/items/"):
            item_id = self.path.split("/")[-1]
            if item_id in items:
                with items_lock:
                    deleted = items.pop(item_id)
                    save_items(items)
                self._send_json(200, "OK", {"message": f"物品 {item_id} 已删除", "deleted": deleted})
            else:
                self._send_json(404, "Not Found", {"error": f"物品 {item_id} 不存在"})
        else:
            self._send_json(405, "Method Not Allowed", {"error": f"DELETE {self.path} 不支持"})

    def log_message(self, format, *args):
        """覆盖默认日志，避免重复输出"""
        pass

# 启动 WebSocket（后台线程）
def run_ws():
    asyncio.run(websocket_server())

if __name__ == "__main__":
    threading.Thread(target=run_ws, daemon=True).start()
    print("✅ WebSocket 已启动：ws://localhost:8765")
    print("✅ HTTP 服务已启动：http://localhost:8080")
    print("📡 报文拦截已开启，所有 HTTP/WS 通信将被记录到控制台\n")
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
