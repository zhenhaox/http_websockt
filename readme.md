# HTTP & WebSocket 知识演示平台 — 文档汇总

---

## 零、项目概览

### 0.1 项目文件结构

```
web-server/
├── server.py       # HTTP(8080) + WebSocket(8765) 双协议服务器
├── upload.html     # 前端页面（演示入口）
├── app.js          # 前端逻辑（所有交互代码）
├── style.css       # 样式文件
├── items.json      # 数据库文件（RESTful CRUD 的数据源）
├── http_log.txt    # 运行时自动生成的报文日志（重启清空）
├── uploads/        # 上传图片的存储目录
└── readme.md       # 本文档
```

### 0.2 页面加载时的 4 个 HTTP 请求

浏览器访问 `http://localhost:8080` 时，**按顺序**自动/手动发起以下请求：

| 序号 | 方法 | 路由 | 触发方式 | 功能 |
|------|------|------|---------|------|
| **1** | `GET` | `/` | **自动**（地址栏输入后） | 返回 `upload.html` 页面 |
| **2** | `GET` | `/style.css` | **自动**（浏览器解析 HTML 发现 `<link>`） | 获取 CSS 样式表 |
| **3** | `GET` | `/app.js` | **自动**（浏览器解析 HTML 发现 `<script>`） | 获取 JS 逻辑代码 |
| **4** | `GET` | `/uploads` | **手动**（用户点击"加载全部图片"按钮） | 服务端扫描 uploads 文件夹，返回所有图片 base64 数据 |

> **前 3 个是浏览器自动发的**：HTML → 解析发现引用 → 自动去拿。这就是"静态资源多请求"的本质。
>
> **第 4 个是用户主动触发的**：点击按钮才发一次 API 请求。

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

## 三、完整 API 路由表（基于 server.py）

### 3.1 GET 路由

| 路径 | 功能说明 | Content-Type | 状态码 |
|------|---------|-------------|--------|
| `/` | 返回首页 HTML (`upload.html`) | text/html | 200 |
| `/query` | JSON API，返回服务器用户名 | application/json | 200 |
| `/logs` | 返回完整的 HTTP 报文日志内容 | text/plain | 200 |
| `/items` | 返回所有物品列表 (JSON 数组) | application/json | 200 |
| `/items/{id}` | 返回单个物品详情（ID 不存在则 404） | application/json | 200 / 404 |
| `/redirect/301` | **301 永久重定向**到 `/items` | - | 301 + Location 头 |
| `/redirect/302` | **302 临时重定向**到 `/items` | - | 302 + Location 头 |
| `/cache` | **缓存演示**：判断 If-None-Match，返回 304 或带 ETag 的 200 | application/json | 304 / 200 |
| `/auth` | **认证演示**：检查 Authorization 头 | application/json | 200 / 401 |
| `/forbidden` | **403 Forbidden 演示** | application/json | 403 |
| `/error/500` | **500 错误演示** | - | 500 |
| `/cookie/set` | **设置 Cookie**：Set-Cookie 写入 session_id | application/json | 200 |
| `/cookie/get` | **读取 Cookie**：从请求头读取并返回 | application/json | 200 |
| `/cookie/clear` | **清除 Cookie**：Max-Age=0 删除 | application/json | 200 |
| `/uploads` 或 `/uploads/` | **扫描文件夹**：返回所有图片的 base64 数据列表 | application/json | 200 |
| `/uploads/{filename}` | **单张图片访问**（支持中文 URL 编码解码） | image/* | 200 / 404 |
| `*.js` | **静态资源**：JavaScript 文件 | application/javascript | 200 |
| `*.css` | **静态资源**：CSS 样式表 | text/css | 200 |
| *(其他)* | 兜底 404 | - | 404 |

### 3.2 POST 路由

| 路径 | 功能说明 | Content-Type | 状态码 |
|------|---------|-------------|--------|
| `/upload` | **文件上传**：multipart/form-data → 保存到 uploads/ | multipart/form-data | 200 |
| `/items` | **创建物品**：JSON body → 自增 ID → 写入 items.json | application/json | 201 |
| `/log/clear` | **清空日志文件** `http_log.txt` | - | 200 |
| `/form` | **普通表单提交**：x-www-form-urlencoded 解析 | x-www-form-urlencoded | 200 |
| *(其他)* | 兜底 405 | - | 405 |

### 3.3 PUT / PATCH / DELETE 路由

| 方法 | 路径 | 功能说明 | 状态码 |
|------|------|---------|--------|
| PUT | `/items/{id}` | **整体替换**：必须传 name+price，未传字段被覆盖 | 200 / 404 |
| PATCH | `/items/{id}` | **部分更新**：只更新传入的字段 | 200 / 404 |
| DELETE | `/items/{id}` | **删除**：移除并持久化到 items.json | 200 / 404 |

### 3.4 OPTIONS / HEAD 路由

| 方法 | 说明 |
|------|------|
| OPTIONS * | CORS 预检处理，返回 204 + 允许的头 |
| HEAD `/` | 仅返回首页响应头，**无响应体** |

### 3.5 数据持久化

- 所有 CRUD 操作（POST/PUT/PATCH/DELETE `/items*`）**实时写入 `items.json`**
- 使用 `threading.Lock()` 防止并发写入冲突
- 启动时从 `items.json` 加载，相当于简易数据库
- 所有 HTTP 交互日志追加写入 `http_log.txt`，可通过 `GET /logs` 查看

---

## 四、重要 HTTP 头详解

### 4.1 Content-Type — 数据格式标识

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

### 4.2 Cookie & Set-Cookie — 身份凭证

Cookie 是服务端通过响应头发给浏览器的一小段数据，浏览器之后**自动**在每次请求中带上。

```
第1步: 设置 Cookie (服务端 → 浏览器)
  响应头: Set-Cookie: session_id=abc123; Path=/; HttpOnly
  → 浏览器保存这张"通行证"

第2步: 自动携带 (浏览器 → 服务端, 之后每次请求都带)
  请求头: Cookie: session_id=abc123
  → 服务端读取，识别身份

第3步: 清除 Cookie (服务端 → 浏览器)
  响应头: Set-Cookie: session_id=; Max-Age=0
  → 浏览器删除这张通行证
```

| 属性 | 说明 | 示例 |
|------|------|------|
| `Path=/` | 在哪些路径下生效 | `Path=/admin` 只在 /admin 下发送 |
| `HttpOnly` | 防 XSS 攻击（JS 无法读取） | 安全建议开启 |
| `Max-Age=3600` | 有效期（秒） | 过期后浏览器自动删除 |
| `Secure` | 仅 HTTPS 传输 | 生产环境建议开启 |

> **类比**：超市会员卡——办卡(`Set-Cookie`)→购物出示(`Cookie`)→过期作废(`Max-Age=0`)。

### 4.3 Authorization — 认证信息

客户端在请求头中携带证明自己身份的凭据。

```
未认证:
  Authorization: (空)
  → 401 Unauthorized  ← "你是谁？"

已认证:
  Authorization: Bearer my-secret-token
  → 200 OK             ← "确认身份，放行"
```

| 格式 | 写法 | 安全性 | 使用场景 |
|------|------|--------|---------|
| Bearer Token | `Bearer xxxxxx` | 较高 | JWT、OAuth2（现代主流） |
| Basic Auth | `Base64(用户名:密码)` | 低 | 简单内部系统 |

### 4.4 其他常见头

**请求头**

| 请求头 | 说明 |
|--------|------|
| Host | 目标主机名+端口 |
| User-Agent | 客户端标识 |
| Accept | 可接受的响应类型 |
| Content-Length | 请求体字节长度 |
| Connection | 连接管理 (keep-alive) |
| Origin | 请求来源（跨域时） |

**响应头**

| 响应头 | 说明 |
|--------|------|
| Location | 重定向目标地址 |
| ETag | 资源版本标识（配合 304 缓存） |
| Cache-Control | 缓存策略 |
| Access-Control-Allow-Origin | CORS 允许的源 |

---

## 五、表单提交格式

### 5.1 multipart/form-data（文件上传）

```
POST /upload HTTP/1.1
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
> **服务端日志会智能解析**：按 boundary 切分 Part，区分 📎文件字段 和 📝文本字段，显示头部信息和数据预览。

### 5.2 application/x-www-form-urlencoded（普通表单）

```
POST /form HTTP/1.1
Content-Type: application/x-www-form-urlencoded
Content-Length: 18

name=zhenhao&age=20
```

> 特点：纯键值对格式（`key=value&key=value`），简单轻量，但不支持文件。
>
> **特殊字符需要编码**：中文→URL 编码（%E4%BC%81），`&`=`等保留符也要编码。

---

## 六、CORS 跨域资源共享

浏览器的**同源策略**规定：JS 代码只能访问同源（协议+域名+端口完全相同）的资源。
跨域请求时，浏览器会先发 `OPTIONS` 预检请求。

### 6.1 触发预检的条件

- 非 GET/POST 的方法（PUT/DELETE/PATCH）
- 自定义请求头（如 `X-Custom-Header`）
- 简单 GET/Post **不触发**预检

### 6.2 本项目的 CORS 配置

```python
# OPTIONS 预检统一返回：
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, PUT, DELETE, PATCH, OPTIONS
Access-Control-Allow-Headers: Content-Type, Authorization, X-Custom-Header
Access-Control-Max-Age: 86400   ← 预检结果缓存 24 小时
```

> **WebSocket 不受 CORS 限制**，但受 Origin 头检查限制。

---

## 七、WebSocket 协议详解

### 7.1 握手流程

**第1步：客户端发送 HTTP Upgrade 请求**

```http
GET / HTTP/1.1
Host: localhost:8765
Upgrade: websocket          ← 请求协议升级
Connection: Upgrade         ← 要求升级连接
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==
Sec-WebSocket-Version: 13
```

**第2步：服务端返回 101**

```http
HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOko=
```

**第3步：握手完成 → 同一 TCP 连接切换为 WebSocket 二进制帧**

### 7.2 帧格式（RFC 6455 Section 5.2）

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

| 字段 | 位数 | 说明 |
|------|------|------|
| FIN | 1 bit | 1=消息最后一帧，0=后续还有帧 |
| Opcode | 4 bit | 1=text, 2=binary, 8=close, 9=ping, 10=pong |
| MASK | 1 bit | 1=客户端帧（必须掩码），0=服务端帧 |
| Payload len | 7 bit | 0-125=实际长度，126=2字节扩展，127=8字节扩展 |
| Masking-Key | 0/4 byte | 仅 MASK=1 时存在 |
| Payload Data | 变长 | 实际数据（MASK=1 时需 XOR 解掩码）|

### 7.3 掩码算法（RFC 强制要求）

```python
# 客户端→服务端的帧必须 MASK=1
for i in range(len(payload)):
    unmasked[i] = payload[i] ^ masking_key[i % 4]
```

### 7.4 多端口共存架构

| | HTTP 服务器 | WebSocket 服务器 |
|---|---|---|
| 端口 | 8080 | 8765 |
| 协议 | 始终是 HTTP | 握手后变为 WS 帧 |
| 用途 | 页面/API/上传/静态资源 | 实时进度推送 |

> 两者是独立的 TCP 连接，互不干扰。

---

## 八、缓存机制

### 8.1 流程

```
第1次 GET /cache:
  响应: 200 OK
        ETag: "v1-abc123"        ← 服务端给的"版本号"
        Body: {数据...}
        ↓ 浏览器缓存这份响应

第2次 GET /cache (缓存有效期内):
  请求: If-None-Match: "v1-abc123"   ← "我有 v1 版本，变了吗？"
  响应: 304 Not Modified                  ← "没变，用你缓存的吧"
        (无 Body! 节省流量)
```

---

## 九、HTTP 版本演进

| 版本 | 特点 |
|------|------|
| HTTP/1.0 | 每次请求新建 TCP 连接，完事断开 |
| HTTP/1.1 | 默认 Keep-Alive 长连接，管道化（队头阻塞） |
| HTTP/2 | 多路复用（一个连接并行多请求），头部压缩，服务端推送 |
| HTTP/3 | 基于 QUIC(UDP)，彻底解决队头阻塞，0-RTT 建连 |

---

## 十、实战注意事项

### 10.1 rfile 双读问题

`_dump_request()` 打印日志时会从 `rfile.read()` 读走请求体。如果后续再读就为空。

**解决方案**：将第一次读取的内容缓存到 `self._cached_body`，后续通过 `_get_body()` 取缓存。

### 10.2 端口占用错误 `OSError: [Errno 10048]`

原因：上一次的服务器进程没有正常退出，端口还被占用。
解决：`netstat -ano | findstr :端口` 找到 PID → `taskkill /F /PID xxx` 杀掉旧进程。

### 10.3 URL 中文编码问题

磁盘上的文件名是中文（如 `企业微信截图.png`），浏览器请求时会 URL 编码为 `%E4%BC%81...`。服务端必须用 `unquote()` 解码才能找到真实文件。

### 10.4 JSON 双重编码陷阱

```python
# ❌ 错误：双重编码
result = json.dumps({"images": [...]})     # 第1次
_send_json(200, result)                     # 第2次！
# → 客户端收到的是字符串 "{\"images\": [...]}" 不是对象

# ✅ 正确：只编码一次
_send_json(200, {"images": [...]})         # _send_json 内部编码
```

---

## 十一、功能对照表（每个功能对应哪个知识点）

| 页面功能 | HTTP/WS 知识点 | 涉及的路由/操作 |
|----------|---------------|-----------------|
| WebSocket 进度条 | WS 握手 + 帧格式 | `new WebSocket('ws://localhost:8765')` |
| GET/POST/PUT/DELETE/PATCH 按钮 | HTTP 方法 + RESTful | `/items`, `/items/:id` |
| 状态码演示按钮 (200/201/301/302/304/401/403/404/500) | 状态码含义 + 浏览器内置行为 | 各自对应路由 |
| 查询用户名 | GET + JSON API | `GET /query` |
| x-www-form-urlencoded 表单 | 表单编码格式 | `POST /form` |
| 图片上传 | multipart/form-data + 文件保存 | `POST /upload` |
| Cookie 演示 | Set-Cookie / Cookie 头 | `/cookie/set` `/cookie/get` `/cookie/clear` |
| CORS 预检按钮 | OPTIONS + 自定义头触发预检 | `OPTIONS *` |
| 加载全部图片 | 静态资源加载 + base64 传输 | `GET /uploads` |
| 查看完整日志 | 日志文件读写 | `GET /logs` / `POST /log/clear` |
| HTTP 报文面板 | 实时拦截展示所有请求/响应 | 全局 `_dump_request()` / `_dump_response()` |
| WS 报文面板 | 实时展示 WS 帧 | 全局 `log_ws()` + 帧构造/解析 |
