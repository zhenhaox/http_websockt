// =====================================================================
// HTTP & WebSocket 知识演示平台 - 前端逻辑
// =====================================================================

let ws;
const btn = document.getElementById('startBtn');
const bar = document.getElementById('bar');
const tip = document.getElementById('tip');
const httpPanel = document.getElementById('httpPanel');
const wsPanel   = document.getElementById('wsPanel');

// ---- 工具函数 ----
function now() {
    return new Date().toLocaleTimeString('zh-CN', { hour12: false }) + '.' +
           String(new Date().getMilliseconds()).padStart(3, '0');
}

function escapeHtml(str) {
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function addLog(panel, tag, tagClass, content) {
    const div = document.createElement('div');
    div.innerHTML = `<span class="timestamp">${now()}</span>` +
                    `<span class="tag ${tagClass}">${tag}</span>` +
                    `<div class="detail-box">${escapeHtml(content)}</div>`;
    panel.appendChild(div);
    panel.scrollTop = panel.scrollHeight;
}

function clearPanel(type) {
    const el = type === 'http' ? httpPanel : wsPanel;
    el.innerHTML = '';
}

// ========== WebSocket 帧构造 (RFC 6455) ==========
const OPCODE_NAMES = {0:'continuation',1:'text',2:'binary',8:'close',9:'ping',10:'pong'};

function buildWsFrame(fin, opcode, payloadStr, mask) {
    const payloadBytes = new TextEncoder().encode(payloadStr);
    const len = payloadBytes.length;
    const frame = [];
    frame.push((fin << 7) | opcode);
    let maskBit = mask ? 0x80 : 0;
    if (len <= 125) {
        frame.push(maskBit | len);
    } else if (len <= 65535) {
        frame.push(maskBit | 126);
        frame.push((len >> 8) & 0xFF);
        frame.push(len & 0xFF);
    } else {
        frame.push(maskBit | 127);
        for (let i = 7; i >= 0; i--) frame.push((len >> (i*8)) & 0xFF);
    }
    let mk = null;
    if (mask) {
        mk = new Uint8Array(4);
        crypto.getRandomValues(mk);
        frame.push(...mk);
    }
    if (mask && mk) {
        const masked = new Uint8Array(len);
        for (let i = 0; i < len; i++) masked[i] = payloadBytes[i] ^ mk[i % 4];
        frame.push(...masked);
    } else {
        frame.push(...payloadBytes);
    }
    return new Uint8Array(frame);
}

function explainWsFrame(raw, direction) {
    const lines = [];
    lines.push(`方向: ${direction}`);
    lines.push(`帧总长度: ${raw.length} 字节`);
    const b0 = raw[0];
    const fin = (b0 >> 7) & 1;
    const opcode = b0 & 0x0F;
    const opName = OPCODE_NAMES[opcode] || `reserved(${opcode})`;
    lines.push('');
    lines.push(`── 第1字节 (0x${b0.toString(16).padStart(2,'0')}) ──`);
    lines.push(`  FIN    = ${fin}  (${fin ? '最后一帧' : '后续还有帧'})`);
    lines.push(`  RSV1-3 = 0`);
    lines.push(`  Opcode = ${opcode} (${opName})`);
    lines.push(`  二进制 = ${b0.toString(2).padStart(8,'0')}`);
    const b1 = raw[1];
    const hasMask = (b1 >> 7) & 1;
    let plen = b1 & 0x7F;
    let offset = 2;
    lines.push('');
    lines.push(`── 第2字节 (0x${b1.toString(16).padStart(2,'0')}) ──`);
    lines.push(`  MASK          = ${hasMask}  (${hasMask ? '客户端帧，需掩码' : '服务端帧，无掩码'})`);
    if (plen === 126) {
        const realLen = (raw[2] << 8) | raw[3];
        lines.push(`  扩展长度(126) = ${realLen} 字节`);
        offset = 4; plen = realLen;
    } else if (plen === 127) {
        let realLen = 0;
        for (let i = 0; i < 8; i++) realLen = (realLen << 8) | raw[2+i];
        lines.push(`  扩展长度(127) = ${realLen} 字节`);
        offset = 10; plen = realLen;
    } else {
        lines.push(`  Payload len   = ${plen}`);
    }
    if (hasMask) {
        const mk = raw.slice(offset, offset + 4);
        lines.push('');
        lines.push(`── Masking-Key (4字节) ──`);
        lines.push(`  ${Array.from(mk).map(b=>b.toString(16).padStart(2,'0')).join(' ')}`);
        offset += 4;
    }
    const payload = raw.slice(offset);
    lines.push('');
    lines.push(`── Payload 数据 (${payload.length} 字节) ──`);
    let displayPayload = payload;
    if (hasMask) {
        const mk = raw.slice(offset - 4, offset);
        displayPayload = new Uint8Array(payload.length);
        for (let i = 0; i < payload.length; i++) displayPayload[i] = payload[i] ^ mk[i % 4];
    }
    try {
        const text = new TextDecoder().decode(displayPayload);
        lines.push(`  文本: ${text}`);
    } catch(e) {}
    const hexStr = Array.from(displayPayload.slice(0,64)).map(b=>b.toString(16).padStart(2,'0')).join(' ');
    lines.push(`  Hex : ${hexStr}${displayPayload.length > 64 ? ' ...' : ''}`);
    lines.push('');
    lines.push('── 完整帧 Hex Dump ──');
    for (let i = 0; i < raw.length; i += 16) {
        const chunk = raw.slice(i, Math.min(i+16, raw.length));
        const hex = Array.from(chunk).map(b=>b.toString(16).padStart(2,'0')).join(' ');
        const ascii = Array.from(chunk).map(b => (b>=32 && b<127) ? String.fromCharCode(b) : '.').join('');
        lines.push(`  ${i.toString(16).padStart(4,'0')}  ${hex.padEnd(48)}  ${ascii}`);
    }
    return lines.join('\n');
}

// ========== 通用 API 调用（带报文拦截） ==========

async function apiRequest(method, url, options = {}) {
    const { body, headers: customHeaders, resultEl, rawResponse } = options;

    // 构造完整的请求报文（模拟浏览器实际发送的所有头）
    let reqText = `${method} ${url} HTTP/1.1\n`;
    // 标准请求头（浏览器自动附加的）
    const stdHeaders = [
        ['Host', 'localhost:8080'],
        ['Connection', 'keep-alive'],
        ['User-Agent', 'Mozilla/5.0 (compatible; DemoClient/1.0)'],
        ['Accept', '*/*'],
        ['Origin', location.origin],
        ['Sec-Fetch-Site', 'same-origin'],
        ['Sec-Fetch-Mode', 'cors'],
        ['Sec-Fetch-Dest', 'empty'],
        ['Referer', location.href],
        ['Accept-Encoding', 'gzip, deflate'],
        ['Accept-Language', 'zh-CN,zh;q=0.9'],
    ];
    for (const [k, v] of stdHeaders) {
        reqText += `${k}: ${v}\n`;
    }
    // 自定义头（覆盖标准头或追加）
    if (customHeaders) {
        for (const [k, v] of Object.entries(customHeaders)) {
            reqText += `${k}: ${v}\n`;
        }
    }
    // 请求体
    if (body && typeof body === 'string') {
        reqText += `Content-Length: ${body.length}\n`;
        reqText += `\n[请求体共 ${body.length} 字节]\n${body}`;
    } else if (body instanceof FormData) {
        reqText += `Content-Type: multipart/form-data; boundary=(浏览器自动生成)\n`;
        const entries = [];
        for (const [k, v] of body.entries()) {
            entries.push(`${k}: ${v} (file: ${(v instanceof File ? v.name : v.type || '')})`);
        }
        reqText += `[FormData 包含字段]\n${entries.join('\n')}`;
    }
    addLog(httpPanel, 'REQ', 'req', reqText);

    try {
        const fetchOpts = { method, headers: customHeaders || {} };
        if (body) fetchOpts.body = body;
        const resp = await fetch(url, fetchOpts);

        // 构造响应报文文本（完整输出）
        let resText = `HTTP/1.1 ${resp.status} ${resp.statusText}\n`;
        resp.headers.forEach((v, k) => { resText += `${k}: ${v}\n`; });
        
        // 如果需要原始 response（用于图片等二进制数据），不读 body 为 text
        if (rawResponse) {
            const contentLength = resp.headers.get('Content-Length');
            resText += `\n[响应体: ${contentLength ? contentLength + ' 字节' : '二进制数据'} - 已跳过文本读取，返回原始 Response]`;
            addLog(httpPanel, 'RES', 'res', resText);
            return { resp, body: null };
        }
        
        const respBody = await resp.text();
        if (respBody) {
            resText += `\n[响应体共 ${respBody.length} 字节]\n${respBody}`;
        } else {
            resText += `\n(无响应体)`;
        }
        addLog(httpPanel, 'RES', 'res', resText);

        // 更新结果区域（完整显示）
        if (resultEl) {
            const el = document.getElementById(resultEl);
            if (el) {
                try {
                    const data = JSON.parse(respBody);
                    el.textContent = JSON.stringify(data, null, 2);
                } catch {
                    el.textContent = respBody;
                }
            }
        }
        return { resp, body: respBody };
    } catch (err) {
        addLog(httpPanel, 'RES', 'res', `❌ 请求失败: ${err.message}`);
        return { resp: null, body: null };
    }
}

// ========== HTTP 方法演示 ==========

function apiGet(url) {
    return apiRequest('GET', url, { resultEl: 'itemsResult' });
}

function apiPost(url, data) {
    const body = JSON.stringify(data);
    return apiRequest('POST', url, {
        body,
        headers: { 'Content-Type': 'application/json' },
        resultEl: 'itemsResult',
    });
}

function apiPut(url, data) {
    const body = JSON.stringify(data);
    return apiRequest('PUT', url, {
        body,
        headers: { 'Content-Type': 'application/json' },
        resultEl: 'itemsResult',
    });
}

function apiPatch(url, data) {
    const body = JSON.stringify(data);
    return apiRequest('PATCH', url, {
        body,
        headers: { 'Content-Type': 'application/json' },
        resultEl: 'itemsResult',
    });
}

function apiDelete(url) {
    return apiRequest('DELETE', url, { resultEl: 'itemsResult' });
}

function apiHead(url) {
    return apiRequest('HEAD', url, { resultEl: 'itemsResult' });
}

function doPatch() {
    const id = document.getElementById('patchId').value;
    const name = document.getElementById('patchName').value.trim();
    const price = document.getElementById('patchPrice').value.trim();
    const data = {};
    if (name) data.name = name;
    if (price) data.price = parseFloat(price) || 0;
    if (!name && !price) { document.getElementById('itemsResult').textContent = '至少填写一个字段'; return; }
    return apiRequest('PATCH', '/items/' + id, {
        body: JSON.stringify(data),
        headers: { 'Content-Type': 'application/json' },
        resultEl: 'itemsResult',
    });
}

// ========== 状态码: 304 缓存 ==========
let _cacheEtag = null;

async function apiGetCache() {
    const headers = {};
    if (_cacheEtag) {
        headers['If-None-Match'] = _cacheEtag;
    }
    const { resp, body } = await apiRequest('GET', '/cache', {
        headers,
        resultEl: 'itemsResult',
    });
    if (resp && resp.status === 200) {
        const etag = resp.headers.get('ETag');
        if (etag) _cacheEtag = etag;
    }
}

// ========== 请求头: Authorization ==========
async function apiGetAuth() {
    return apiRequest('GET', '/auth', {
        headers: { 'Authorization': 'Bearer my-secret-token' },
        resultEl: 'itemsResult',
    });
}

// ========== Cookie ==========
// Cookie 操作使用默认 fetch（浏览器自动管理 Cookie）
async function apiGetCookie(url) {
    let reqText = `GET ${url} HTTP/1.1\nHost: localhost:8080`;
    addLog(httpPanel, 'REQ', 'req', reqText);

    try {
        const resp = await fetch(url);
        let resText = `HTTP/1.1 ${resp.status} ${resp.statusText}\n`;
        resp.headers.forEach((v, k) => { resText += `${k}: ${v}\n`; });
        const body = await resp.text();
        if (body) resText += `\n${body}`;
        addLog(httpPanel, 'RES', 'res', resText);

        const el = document.getElementById('cookieResult');
        if (el) {
            try {
                const data = JSON.parse(body);
                el.textContent = JSON.stringify(data, null, 2);
            } catch {
                el.textContent = body;
            }
        }
    } catch (err) {
        addLog(httpPanel, 'RES', 'res', `❌ 请求失败: ${err.message}`);
    }
}

// 覆盖 Cookie 按钮的 URL 路由
window.apiGet = function(url) {
    if (url.startsWith('/cookie/')) {
        return apiGetCookie(url);
    }
    return apiRequest('GET', url, { resultEl: 'itemsResult' });
};

// ========== x-www-form-urlencoded 表单 ==========
async function submitForm() {
    const name = document.getElementById('formName').value;
    const age = document.getElementById('formAge').value;
    const body = `name=${encodeURIComponent(name)}&age=${encodeURIComponent(age)}`;

    await apiRequest('POST', '/form', {
        body,
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        resultEl: 'formResult',
    });
}

// ========== CORS 演示 ==========
async function apiCorsDemo() {
    // 发一个带自定义头的 PUT 请求，触发 OPTIONS 预检
    await apiRequest('PUT', '/items/1', {
        body: JSON.stringify({ name: 'CORS测试', price: 99 }),
        headers: {
            'Content-Type': 'application/json',
            'X-Custom-Header': 'cors-demo',  // 自定义头会触发预检
        },
        resultEl: 'corsResult',
    });
}

// ========== 静态资源加载 ==========
// 客户端只发 GET /uploads/，服务端自动扫描文件夹，一次返回所有图片的 base64 数据
async function loadAllImages() {
    const el = document.getElementById('staticResult');
    el.textContent = '正在请求服务端扫描 uploads 文件夹...';
    
    try {
        // 1 次请求拿到所有图片
        const { resp, body: respBody } = await apiRequest('GET', '/uploads/', { resultEl: null });
        
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        
        const data = JSON.parse(respBody);
        if (!data.images || data.images.length === 0) {
            el.innerHTML = 'uploads 目录为空，请先上传一张图片';
            return;
        }
        
        // 构建图片预览（可点击页面内弹窗查看大图）
        let galleryHtml = `<div style="display:flex;flex-direction:column;gap:12px;margin-top:10px;">`;
        data.images.forEach((img, idx) => {
            const imgId = `previewImg${idx}`;
            galleryHtml += `
                <div class="img-card">
                    <img id="${imgId}" src="${img.data}" 
                         onclick="showBigImage(this,'${img.name}')"
                         title="点击查看大图" />
                    <div class="img-info">
                        <div class="img-name">${img.name}</div>
                        <div class="img-meta">${(img.size / 1024).toFixed(1)} KB · ${img.mime.split('/')[1].toUpperCase()}</div>
                        <div class="img-btns">
                            <button onclick="downloadImage('${img.data}','${img.name}')" class="img-btn">⬇ 下载</button>
                            <button onclick="showBigImage(document.getElementById('${imgId}'),'${img.name}')" class="img-btn">🔍 查看大图</button>
                        </div>
                    </div>
                </div>`;
        });
        galleryHtml += '</div>';
        el.innerHTML = `✅ 服务端返回 ${data.count} 张图片（1次请求搞定，无需关心文件名格式）${galleryHtml}`;
    } catch (err) {
        el.innerHTML = `❌ 加载失败: ${err.message}`;
    }
}

// ========== 图片大图弹窗 ==========
function showBigImage(imgEl, fileName) {
    // 创建遮罩层
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.8);z-index:9999;display:flex;align-items:center;justify-content:center;cursor:pointer;';
    
    // 大图
    const bigImg = document.createElement('img');
    bigImg.src = imgEl.src;
    bigImg.style.cssText = 'max-width:90vw;max-height:90vh;border-radius:8px;box-shadow:0 4px 30px rgba(0,0,0,0.5);';
    
    // 文件名
    const label = document.createElement('div');
    label.textContent = fileName;
    label.style.cssText = 'position:absolute;bottom:20px;color:#fff;font-size:14px;background:rgba(0,0,0,0.6);padding:6px 16px;border-radius:20px;';
    
    // 提示
    const hint = document.createElement('div');
    hint.textContent = '点击任意位置关闭';
    hint.style.cssText = 'position:absolute;top:16px;color:#aaa;font-size:12px;';
    
    overlay.appendChild(bigImg);
    overlay.appendChild(label);
    overlay.appendChild(hint);
    
    // 点击关闭
    overlay.addEventListener('click', () => document.body.removeChild(overlay));
    document.body.appendChild(overlay);
}

// ========== 下载图片 ==========
function downloadImage(dataUrl, fileName) {
    const link = document.createElement('a');
    link.href = dataUrl;
    link.download = fileName;
    link.click();
}

// ========== 图片上传 ==========
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const previewArea = document.getElementById('previewArea');
const uploadTip = document.getElementById('uploadTip');

dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.style.borderColor = '#1976d2';
    dropZone.style.background = '#e3f2fd';
});
dropZone.addEventListener('dragleave', () => {
    dropZone.style.borderColor = '#bbb';
    dropZone.style.background = '#fff';
});
dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.style.borderColor = '#bbb';
    dropZone.style.background = '#fff';
    if (e.dataTransfer.files.length > 0) handleFiles(e.dataTransfer.files);
});
fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) handleFiles(fileInput.files);
});

async function handleFiles(files) {
    for (const file of files) {
        if (!file.type.startsWith('image/')) {
            uploadTip.textContent = '仅支持图片文件';
            continue;
        }
        const reader = new FileReader();
        reader.onload = (e) => {
            const img = document.createElement('img');
            img.src = e.target.result;
            img.style.cssText = 'max-width:120px; max-height:120px; border-radius:6px; border:1px solid #ddd; object-fit:cover;';
            previewArea.appendChild(img);
        };
        reader.readAsDataURL(file);

        uploadTip.textContent = `正在上传 ${file.name}...`;
        const formData = new FormData();
        formData.append('file', file, file.name);

        const reqText = `POST /upload HTTP/1.1\nContent-Type: multipart/form-data; boundary=(自动生成)\nContent-Length: ${file.size + 300}(约)\n\n------boundary\nContent-Disposition: form-data; name="file"; filename="${file.name}"\nContent-Type: ${file.type}\n\n<二进制图片数据 ${file.size} 字节>\n------boundary--`;
        addLog(httpPanel, 'REQ', 'req', reqText);

        try {
            const resp = await fetch('/upload', { method: 'POST', body: formData });
            let resText = `HTTP/1.1 ${resp.status} ${resp.statusText}\n`;
            resp.headers.forEach((v, k) => { resText += `${k}: ${v}\n`; });
            const body = await resp.text();
            if (body) resText += `\n${body}`;
            addLog(httpPanel, 'RES', 'res', resText);
            uploadTip.textContent = resp.ok ? `${file.name} 上传成功！` : `${file.name} 上传失败: ${resp.status}`;
        } catch (err) {
            addLog(httpPanel, 'RES', 'res', `❌ 上传失败: ${err.message}`);
            uploadTip.textContent = `上传失败: ${err.message}`;
        }
    }
}

// ========== WebSocket 连接 ==========
function connect() {
    ws = new WebSocket('ws://localhost:8765');

    ws.onopen = () => {
        tip.textContent = "连接成功，可以点击开始";
        btn.disabled = false;
        addLog(wsPanel, 'OPEN', 'open',
            `握手完成：HTTP 101 Switching Protocols → 协议升级为 WebSocket\n` +
            `客户端 → 服务端 Upgrade: websocket\n` +
            `服务端 → 客户端 Sec-WebSocket-Accept: (由 Key+GUID 经 SHA-1 计算)`);
    };

    ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        const p = data.progress;

        if (p === 0 || p === 50 || p === 100) {
            const raw = buildWsFrame(1, 1, e.data, false);
            const explanation = explainWsFrame(raw, '服务端 → 客户端 (mask=False)');
            addLog(wsPanel, 'RECV', 'recv', explanation);
        } else if (p === 1) {
            addLog(wsPanel, 'RECV', 'recv', `... 进度帧持续推送中 (0~100) ...`);
        }

        bar.style.width = p + '%';
        bar.textContent = p + '%';
        if (p == 100) {
            tip.textContent = "✅ 推送完成！";
            btn.disabled = false;
        }
    };

    ws.onclose = (e) => {
        tip.textContent = "连接断开，正在重连...";
        btn.disabled = true;
        const closePayload = String.fromCharCode(e.code >> 8, e.code & 0xFF) + (e.reason || '');
        const raw = buildWsFrame(1, 8, closePayload, true);
        const explanation = explainWsFrame(raw, '客户端 → 服务端 (关闭帧)');
        addLog(wsPanel, 'CLOSE', 'close', explanation);
        setTimeout(connect, 1000);
    };

    ws.onerror = () => {
        tip.textContent = "连接失败";
        addLog(wsPanel, 'CLOSE', 'close', `❌ 连接发生错误`);
    };
}

btn.addEventListener('click', () => {
    btn.disabled = true;
    tip.textContent = "正在推送进度...";
    bar.style.width = '0%';
    bar.textContent = '0%';

    const raw = buildWsFrame(1, 1, 'start', true);
    const explanation = explainWsFrame(raw, '客户端 → 服务端 (mask=True)');
    addLog(wsPanel, 'SEND', 'send', explanation);

    ws.send('start');
});

// 页面加载就连接 WebSocket
connect();
