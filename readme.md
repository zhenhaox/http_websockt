# HTTP 与 WebSocket 知识汇总

---

## 一、HTTP 与 WebSocket 对比

| 特性 | HTTP | WebSocket |
|------|------|-----------|
| 通信模式 | 请求-响应（客户端主动，服务端被动） | 全双工（双方随时可发） |
| 连接生命周期 | 短连接（HTTP/1.0）/ Keep-Alive（HTTP/1.1） | 持久连接，直到主动关闭 |
| 握手 | TCP 三次握手即可 | TCP 握手 + HTTP Upgrade 握手 |
| 数据格式 | 请求行/状态行 + Header + Body | 二进制帧格式（opcode 区分文本/二进制/关闭等） |
| 状态 | 无状态（每次请求独立） | 有状态（连接保持） |
| 服务端能否主动推送 | 不能（只能被动响应） | 可以（全双工） |
| 典型场景 | 请求资源、提交表单、API 调用 | 实时推送、聊天、进度反馈、协同编辑 |

> **关键区别**：WebSocket 握手完成后，同一条 TCP 连接**不再使用 HTTP 协议**，切换为 WebSocket 二进制帧格式通信。但浏览器仍可通过其他 TCP 连接发 HTTP 请求，两者互不干扰。

---

## 二、HTTP 协议基础

### 2.1 HTTP 请求报文结构

```
请求行:    GET /index HTTP/1.1\r\n
请求头:    Host: www.example.com\r\n
           User-Agent: Mozilla/5.0\r\n
           Connection: keep-alive\r\n
           Accept: text/html\r\n
           \r_n              ← 空行表示头部结束
请求体:    (GET 通常没有请求体)
```

### 2.2 HTTP 响应报文结构

```
状态行:    HTTP/1.1 200 OK\r\n
响应头:    Content-Type: text/html\r\n
           Content-Length: 12\r\n
           Connection: keep-alive\r\n
           \r_n              ← 空行表示头部结束
响应体:    Hello World!
```

### 2.3 常见 HTTP 方法 (CRUD)

| 方法 | 用途 | 是否有请求体 | 是否幂等 | 对应 SQL |
|------|------|-------------|---------|----------|
| GET | 获取资源 | 无 | 是 | SELECT |
| POST | 提交数据/创建资源 | 有 | 否 | INSERT |
| PUT | **完整替换**资源 | 有 | 是 | UPDATE(整行) |
| PATCH | **部分更新**资源 | 有 | 否 | UPDATE(部分字段) |
| DELETE | 删除资源 | 可选 | 是 | DELETE |
| HEAD | 只获取响应头，不返回体 | 无 | 是 | - |
| OPTIONS | 查询支持的HTTP方法 | 无 | 是 | - |

> **PUT vs PATCH 的区别**：PUT 必须传完整字段，未传的字段会被清空；PATCH 只改传入的字段，其他保留不变。

### 2.4 常见 HTTP 状态码

#### 2xx 成功

| 状态码 | 含义 | 典型场景 |
|--------|------|---------|
| 200 | OK | 请求成功 |
| 201 | Created | POST 创建资源成功 |
| 204 | No Content | DELETE/PUT 成功但无内容需返回 |

#### 3xx 重定向 & 缓存

| 状态码 | 含义 | 浏览器行为 |
|--------|------|----------|
| 301 | Moved Permanently | 永久跳转到 Location 地址，下次直接访问新地址 |
| 302 | Found | 临时跳转到 Location 地址 |
| 304 | Not Modified | 使用本地缓存 |

> **301 vs 302**：搜索引擎对 301 会更新索引 URL，对 302 不会。

#### 4xx 客户端错误

| 状态码 | 含义 | 浏览器行为 |
|--------|------|----------|
| 400 | Bad Request | 请求格式错误 |
| 401 | Unauthorized | **弹出登录框**（可重试） |
| 403 | Forbidden | 直接拒绝（**不弹登录框**） |
| 404 | Not Found | 资源不存在 |
| 405 | Method Not Allowed | 该路径不支持此方法 |

> **401 vs 403**：401 = "我不知道你是谁，请登录"；403 = "我知道你是谁，但你没权限"。

#### 5xx 服务端错误

| 状态码 | 含义 |
|--------|------|
| 500 | Internal Server Error | 服务端代码出错了 |
| 502 | Bad Gateway | 网关/代理后端挂了 |
| 503 | Service Unavailable | 服务暂时不可用（维护中） |

> **状态码由 RFC 标准规定，不能随意自定义**。每个状态码有固定含义，浏览器会根据不同状态码执行内置行为。

---

## 三、重要 HTTP 头详解

### 3.1 Content-Type — 数据格式标识

告诉对方 body 的格式是什么，应该怎么解析。

| 值 | 用途 | 解析方式 |
|---|---|---|
| `text/html` | HTML 页面 | 浏览器渲染为网页 |
| `text/css` | CSS 样式 | 浏览器应用样式 |
| `application/javascript` | JS 脚本 | 浏览器执行脚本 |
| `application/json` | JSON 数据 | `json.loads()` 解析 |
| `multipart/form-data` | 多部分表单（含文件） | 按 boundary 分割解析 |
| `application/x-www-form-urlencoded` | 键值对表单 | 按 `&` 和 `=` 分割解析 |
| `image/png` | PNG 图片 | 显示图片 |

> **类比**：寄快递标注"易碎品/食品/文件"，收件人知道怎么处理。

### 3.2 Cookie & Set-Cookie — 身份凭证

Cookie 是服务端通过响应头发给浏览器的一小段数据，浏览器之后**自动**在每次请求中带上。

```
完整流程:

第1步: 设置 Cookie (服务端 → 浏览器)
  响应头:  Set-Cookie: session_id=abc123; Path=/; HttpOnly
  → 浏览器保存这张"通行证"

第2步: 自动携带 (浏览器 → 服务端, 之后每次请求都带)
  请求头:  Cookie: session_id=abc123
  → 服务端读取，识别身份

第3步: 清除 Cookie (服务端 → 浏览器)
  响应头:  Set-Cookie: session_id=; Max-Age=0
  → 浏览器删除这张通行证
```

| 属性 | 说明 | 示例 |
|------|------|------|
| `Path=/` | 在哪些路径下生效 | `Path=/admin` 只在 /admin 下发送 |
| `HttpOnly` | 防 XSS 攻击（JS 无法读取） | 安全建议开启 |
| `Max-Age=3600` | 有效期（秒） | 过期后浏览器自动删除 |
| `Secure` | 仅 HTTPS 传输 | 生产环境建议开启 |

> **类比**：超市会员卡——办卡(`Set-Cookie`)→购物出示(`Cookie`)→过期作废(`Max-Age=0`)。

### 3.3 Authorization — 认证信息

客户端在请求头中携带证明自己身份的凭据。

```
未认证的请求:
  GET /auth
  Authorization: (空)
  → 401 Unauthorized  ← "你是谁？"

已认证的请求:
  GET /auth
  Authorization: Bearer my-secret-token   ← "这是我的令牌"
  → 200 OK + 私密数据                      ← "确认身份，放行"
```

常见认证格式：

| 格式 | 写法 | 安全性 | 使用场景 |
|------|------|--------|---------|
| Bearer Token | `Bearer xxxxxx` | 较高 | JWT、OAuth2（现代主流） |
| Basic Auth | `Base64(用户名:密码)` | 低 | 简单内部系统（明文密码） |
| API Key | `Api-Key: xxxxx` | 中等 | 开放平台接口 |

> **类比**：进小区门禁——保安问"你有门禁卡吗？"，你刷卡(`Authorization`)验证后开门。

### 3.4 其他常见请求头

| 请求头 | 说明 | 示例 |
|--------|------|------|
| Host | 目标主机名+端口 | `Host: localhost:8080` |
| User-Agent | 客户端标识 | `User-Agent: Mozilla/5.0` |
| Accept | 可接受的响应类型 | `Accept: text/html` |
| Content-Length | 请求体字节长度 | `Content-Length: 1234` |
| Connection | 连接管理 | `Connection: keep-alive` |
| Origin | 请求来源（跨域时） | `Origin: http://example.com` |

### 3.5 其他常见响应头

| 响应头 | 说明 | 示例 |
|--------|------|------|
| Location | 重定向目标地址 | `Location: /new-url` |
| Cache-Control | 缓存策略 | `Cache-Control: max-age=3600` |
| ETag | 资源版本标识（配合 304） | `ETag: "v1-abc123"` |
| Access-Control-Allow-Origin | CORS 允许的源 | `Access-Control-Allow-Origin: *` |

---

## 四、表单提交格式

### 4.1 multipart/form-data（文件上传）

```
POST /upload HTTP/1.1
Host: localhost:8080
Content-Type: multipart/form-data; boundary=----WebKitFormBoundaryXXX
Content-Length: 12345

------WebKitFormBoundaryXXX
Content-Disposition: form-data; name="file"; filename="photo.png"
Content-Type: image/png

<二进制图片数据>
------WebKitFormBoundaryXXX--
```

> 浏览器通过 `FormData` API 自动构造，JS 只需 `formData.append('file', file)`。
>
> **特点**：适合传文件，用 boundary 分隔多个字段，结构复杂但功能强大。

### 4.2 application/x-www-form-urlencoded（普通表单）

```
POST /form HTTP/1.1
Host: localhost:8080
Content-Type: application/x-www-form-urlencoded
Content-Length: 18

name=zhenhao&age=20
```

> **特点**：纯键值对格式（`key=value&key=value`），简单轻量，但不支持文件。
>
> **解析方式**：按 `&` 分割每对，再按 `=` 分割 key 和 value，最后 `urldecode` 还原中文。

---

## 五、CORS 跨域资源共享

### 5.1 什么是跨域

浏览器的**同源策略**规定：JS 代码只能访问同源（协议+域名+端口完全相同）的资源。
跨域请求时，浏览器会先发 `OPTIONS` 预检请求。

```
同源: http://localhost:8080/page  ↔  http://localhost:8080/api     ✅ 同源，无限制
跨域: http://localhost:8080/page  ↔  http://localhost:9000/api     ❌ 跨域，需 CORS
跨域: http://example.com/page      ↔  http://localhost:8080/api     ❌ 跨域，需 CORS
```

### 5.2 CORS 预检流程

```
第1步: 浏览器自动发 OPTIONS 预检
  OPTIONS /api HTTP/1.1
  Origin: http://localhost:8080
  Access-Control-Request-Method: PUT
  Access-Control-Request-Headers: X-Custom-Header

第2步: 服务端返回允许的头
  204 No Content
  Access-Control-Allow-Origin: *
  Access-Control-Allow-Methods: GET, POST, PUT, DELETE
  Access-Control-Allow-Headers: Content-Type, Authorization

第3步: 预检通过，浏览器才发出真正的 PUT 请求
```

> **触发预检的条件**：非简单方法（PUT/DELETE/PATCH）或自定义请求头（如 `X-Custom-Header`）。简单的 GET/POST 不触发预检。
>
> **WebSocket 不受 CORS 限制**，但受 Origin 头检查限制。

---

## 六、RESTful API 设计规范

### 6.1 资源与 URL 设计

| 操作 | 方法 | URL | 返回状态码 |
|------|------|-----|----------|
| 列表 | GET | `/items` | 200 |
| 详情 | GET | `/items/:id` | 200 / 404 |
| 创建 | POST | `/items` | 201 |
| 替换 | PUT | `/items/:id` | 200 / 404 |
| 部分更新 | PATCH | `/items/:id` | 200 / 404 |
| 删除 | DELETE | `/items/:id` | 200 / 404 |

### 6.2 数据来源：静态文件 vs 内存 vs 数据库

| 方式 | 数据存储位置 | 特点 |
|------|------------|------|
| **硬编码** (`items = {...}`) | Python 字典变量 | 重启丢失，开发测试用 |
| **JSON 文件** (`items.json`) | 磁盘文件 | 重启保留，相当于简易数据库 |
| **真实数据库** (MySQL/PostgreSQL) | 数据库服务器 | 生产环境标准方案 |

> 你的演示项目目前使用 **items.json 文件**作为数据库：
> - 启动时用 `load_items()` 从文件加载
> - 每次 POST/PUT/PATCH/DELETE 后用 `save_items()` 写回文件
> - 加了 `threading.Lock()` 防止并发写入冲突

---

## 七、WebSocket 协议详解

### 7.1 WebSocket 只能由客户端发起升级

浏览器地址栏输入 URL 是**普通 HTTP 请求**，不会带上 `Upgrade: websocket` 头。只有 JS 执行 `new WebSocket('ws://...')` 才能触发握手升级。

### 7.2 WebSocket 握手流程

**第1步：客户端发送 HTTP Upgrade 请求**

```http
GET /ws HTTP/1.1
Host: example.com
Upgrade: websocket          ← 请求协议升级
Connection: Upgrade         ← 要求升级连接
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==   ← 随机 Base16 字节值
Sec-WebSocket-Version: 13                    ← WS 固定版本号
Origin: http://example.com
```

**第2步：服务端返回 101 Switching Protocols**

```http
HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=
                                    ↑
计算公式: base64(sha1(Sec-WebSocket-Key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"))
```

**第3步：握手完成 → 同一 TCP 连接切换为 WebSocket 二进制帧**

### 7.3 端口在哪里？

| 阶段 | 有端口吗？ | 说明 |
|------|-----------|------|
| **握手前** | 有 | TCP 三次握手连到指定端口 |
| **握手请求 (HTTP)** | 有 | `Host: localhost:8765` 头里包含端口 |
| **握手后的帧** | 没有 | 已建立 TCP 连接，帧只含协议层数据 |

> **类比**：打电话——拨号时指定号码（端口），接通后只管说话，不用再说"我在打给谁"。

### 7.4 多个 WebSocket 端口的路由

```javascript
let ws1 = new WebSocket('ws://localhost:8765');   // TCP 连接 A → 目标 8765
let ws2 = new WebSocket('ws://localhost:8766');   // TCP 连接 B → 目标 8766

ws1.send('hello');   // 走连接 A → 到达 8765
ws2.send('world');   // 走连接 B → 到达 8766
```

操作系统根据 **创建对象时绑定的 socket 连接** 自动路由，不需要每条消息再带端口。

### 7.5 WebSocket 帧格式（RFC 6455 Section 5.2）

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|F|R|R|R| opcode|M| Payload len | Extended payload len |
|I|S|S|S|  (4)  |A|     (7)     |       (16/64)        |
|N|V|V|V|       |S|             |  (if len==126/127)   |
| |1|2|3|       |K|             |                       |
+-+-+-+-+-+-+-+-+ - - - - - - - - - +- - - - - - - - - -+
|                 Masking-key (if MASK=1, 4 bytes)              |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                 Payload Data                               |
+ - - - - - - - - - - - - - - - - - - - - - - - - - - +
```

### 7.6 帧字段详解

| 字段 | 位数 | 说明 |
|------|------|------|
| FIN | 1 bit | 1=消息最后一帧，0=后续还有帧 |
| RSV1-3 | 3 bit | 保留，一般为0 |
| Opcode | 4 bit | 0=continuation, 1=text, 2=binary, 8=close, 9=ping, 10=pong |
| MASK | 1 bit | 1=客户端帧（必须掩码），0=服务端帧（无掩码） |
| Payload len | 7 bit | 0-125=实际长度，126=后跟2字节扩展，127=后跟8字节扩展 |
| Masking-Key | 0/4 byte | 仅 MASK=1 时存在，4字节随机值 |
| Payload Data | 变长 | 实际数据，如果 MASK=1 需解掩码 |

### 7.7 掩码算法

RFC 6455 规定：**客户端→服务端的帧必须设置 MASK=1**，服务端→客户端的帧 MASK=0。

```python
# 掩码/解掩码算法（XOR）
for i in range(len(payload)):
    unmasked[i] = payload[i] ^ masking_key[i % 4]
```

### 7.8 帧解析示例

**客户端发送文本 "hello"（MASK=1）：**

```
81 85 37 FA 21 3D 5F 98 42 5C 4D

81:  1xxxxxxx = FIN=1（一帧发完）
     xxxx0001 = opcode=1（文本）
85:  1xxxxxxx = MASK=1（客户端必须掩码）
     xxx0101  = 长度 5
37 FA 21 3D:  掩码 key
5F 98 42 5C 4D → 解掩码后就是 "hello"
```

**服务端返回文本 "hello"（MASK=0）：**

```
81 05 68 65 6C 6C 6F

81: FIN=1 + opcode=1（文本）
05: MASK=0，长度 5
68 65 6C 6C 6F = ASCII "hello"
```

### 7.9 浏览器端 WebSocket 解析流程

```
① TCP 收原始字节流 (81 0f 7b 22 70 72 6f 67 ...)
   ↓
② 第1字节 → FIN, RSV1-3, Opcode
   ↓
③ 第2字节 → MASK位 + Payload Length
   ↓
④ MASK=1? 读4字节 Masking-Key
   ↓
⑤ 解掩码 payload[i] ^= maskingKey[i % 4]
   ↓
⑥ Opcode分发:
   1(text)  → UTF-8解码 → ws.onmessage(e.data是string)
   2(binary) → ArrayBuffer
   8(close)  → ws.onclose
   9(ping)   → 自动回复pong
   ↓
⑦ 应用层 JSON.parse(e.data) → 业务逻辑
```

> 第①~⑥步由浏览器底层 C++ 代码完成，JS 无法访问原始帧字节。我们通过 `buildWsFrame()` 构造等效帧来展示其结构。

---

## 八、HTTP 与 WebSocket 共存架构

### 8.1 两个端口，两个服务器

| | HTTP 服务器 | WebSocket 服务器 |
|---|---|---|
| 端口 | 8080 | 8765 |
| 协议 | 始终是 HTTP | 握手后变为 WS 帧 |
| 用途 | 页面、API、上传、静态资源 | 实时推送 |
| 触发 | 地址栏 / fetch / 表单提交 | `new WebSocket()` |

### 8.2 浏览器加载页面的完整流程

```
浏览器访问 http://localhost:8080        ← 普通 HTTP GET
       ↓
拿到 upload.html → 解析执行 HTML/CSS/JS
       ↓
遇到 <link href="style.css">            ← 自动 GET /style.css
遇到 <script src="app.js">             ← 自动 GET /app.js
       ↓
JS 执行 new WebSocket('ws://localhost:8765')
       ↓
浏览器向 8765 发带 Upgrade 的 HTTP 请求 (握手)
       ↓
服务端返回 101 Switching Protocols
       ↓
该 TCP 连接升级为 WebSocket → 帧格式通信
       ↓
同时浏览器还可通过 8080 发 HTTP 请求:
  fetch('/items')   → GET /items (HTTP)
  fetch('/query')   → GET /query (HTTP)
  fetch('/upload')  → POST /upload (multipart, HTTP)
```

> 8080(HTTP) 和 8765(WS) 是两条独立的 TCP 连接，互不干扰。

---

## 九、缓存机制

### 9.1 缓存流程

```
第1次请求 GET /cache:
  请求: (无 If-None-Match)
  响应: 200 OK
        ETag: "v1-abc123"        ← 服务端给的"版本号"
        Cache-Control: max-age=3600  ← 可缓存1小时
        Body: {数据...}
        ↓ 浏览器缓存这份响应

第2次请求 GET /cache (1小时内):
  请求: If-None-Match: "v1-abc123"   ← "我有 v1 版本，变了吗？"
  响应: 304 Not Modified                  ← "没变，用你缓存的吧"
        (无 Body! 节省流量)
```

| 头部 | 方向 | 作用 |
|------|------|------|
| ETag | 响应 | 资源的"指纹"/版本号 |
| If-None-Match | 请求 | 客户端告诉服务端自己的 ETag |
| Cache-Control | 响应 | 缓存策略（max-age 等） |

---

## 十、HTTP 版本演进

| 版本 | 特点 |
|------|------|
| HTTP/1.0 | 每次请求新建 TCP 连接，完事断开 |
| HTTP/1.1 | 默认 Keep-Alive 长连接，管道化（但队头阻塞） |
| HTTP/2 | 多路复用（一个连接并行多请求），头部压缩，服务端推送 |
| HTTP/3 | 基于 QUIC(UDP)，彻底解决队头阻塞，0-RTT 建连 |

---

## 十一、实战注意事项

### 11.1 rfile 双读问题

`_dump_request()` 用于打印日志时会从 `rfile.read()` 读走请求体。如果后续处理方法再次 `rfile.read()` 就会读到空字符串。

**解决方案**：将第一次读取的内容缓存到 `self._cached_body`，后续通过 `_get_body()` 取缓存。

### 11.2 端口占用错误 `OSError: [Errno 10048]`

原因：上一次的服务器进程没有正常退出，端口还被占用。
解决：`netstat -ano | findstr :端口号` 找到 PID → `taskkill /F /PID xxx` 杀掉旧进程。
