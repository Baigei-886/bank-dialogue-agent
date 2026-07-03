// ══════════════════════════════════════════════
//  配置
// ══════════════════════════════════════════════
const DIFY_URL = 'http://localhost/v1/chat-messages';
const DIFY_KEY = 'Bearer app-YOUR_DIFY_APP_KEY';  // ← 换成你的 Dify 应用 API Key
// ══════════════════════════════════════════════

// 开场白（按浏览器本地时间生成时段问候，准确且无时区问题）
function getOpening() {
    const h = new Date().getHours();
    const greet = (h >= 6 && h < 12) ? '早上好'
                : (h >= 12 && h < 18) ? '下午好'
                : '晚上好';
    return `${greet}，欢迎致电银行。\n我是您的专属服务顾问，请问今天有什么可以为您效劳？`;
}
const QUICK_HINTS = ['转账未到账怎么办', '银行卡被锁了', '查询理财产品'];

// 精致徽标（取代 emoji，提升质感）
const EMBLEM_SVG = `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="4.5" y="4.5" width="15" height="15" rx="3.2" stroke="#fff" stroke-width="1.5"/>
    <path d="M12 4.8v14.4M4.8 12h14.4" stroke="#fff" stroke-width="1.5"/>
    <circle cx="12" cy="12" r="1.6" fill="#fff"/>
</svg>`;

// ── 状态 ─────────────────────────────────────
let state = {
    currentId: null,          // 当前对话的本地 ID
    conversations: {},        // { localId: { id, difyId, title, messages[] } }
    waiting: false,
};

// ── 初始化 ────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
    loadFromStorage();
    applyTheme(localStorage.getItem('theme') || 'dark');
    renderSidebar();

    if (state.currentId && state.conversations[state.currentId]) {
        restoreChat(state.currentId);
    } else {
        startNewConv(false); // 不写入历史，直接新建
    }
});

// ── 新对话 ────────────────────────────────────
function newChat() {
    startNewConv(true);
    closeSidebar();
}

function startNewConv(saveOld) {
    const id = 'c' + Date.now();
    state.conversations[id] = {
        id,
        difyId: null,
        title: '新对话',
        messages: [],
    };
    state.currentId = id;
    saveToStorage();

    clearMessages();
    document.getElementById('chatTitle').textContent = '新对话';
    renderSidebar();

    setTimeout(() => {
        addBubble('agent', getOpening());
        addTimestamp();
        addQuickReplies();
    }, 500);
}

// ── 发送消息 ──────────────────────────────────
async function sendMessage() {
    const input = document.getElementById('userInput');
    const text = input.value.trim();
    if (!text || state.waiting) return;

    input.value = '';
    autoResize(input);
    removeQuickReplies();

    const conv = state.conversations[state.currentId];

    // 更新对话标题（取第一条用户消息）
    if (conv.messages.filter(m => m.role === 'user').length === 0) {
        conv.title = text.slice(0, 28) + (text.length > 28 ? '…' : '');
        document.getElementById('chatTitle').textContent = conv.title;
        renderSidebar();
    }

    const time = timeNow();
    conv.messages.push({ role: 'user', text, time });
    addBubble('user', text);
    addTimestamp(time);
    showTyping();
    setWaiting(true);

    try {
        const res = await fetch(DIFY_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': DIFY_KEY,
            },
            body: JSON.stringify({
                inputs: {},
                query: text,
                response_mode: 'blocking',
                conversation_id: conv.difyId || '',
                user: 'web-' + getSessionId(),
            }),
        });

        const data = await res.json();
        hideTyping();

        const answer = data.answer || '抱歉，出了点小问题，请稍后重试 🙏';
        const ansTime = timeNow();
        conv.difyId = data.conversation_id || conv.difyId;
        conv.messages.push({ role: 'agent', text: answer, time: ansTime });
        saveToStorage();

        addBubble('agent', answer);
        addTimestamp(ansTime);

    } catch {
        hideTyping();
        const errMsg = '网络异常，请确认 Dify 是否正常运行 🔧';
        addBubble('agent', errMsg);
        addTimestamp();
    }

    setWaiting(false);
}

// ── 恢复历史对话 ──────────────────────────────
function restoreChat(id) {
    state.currentId = id;
    const conv = state.conversations[id];
    clearMessages();
    document.getElementById('chatTitle').textContent = conv.title;
    renderSidebar();

    // 空对话（如刷新后的新对话）也展示开场白与预设问题
    if (!conv.messages || conv.messages.length === 0) {
        setTimeout(() => {
            addBubble('agent', getOpening());
            addTimestamp();
            addQuickReplies();
        }, 200);
        return;
    }

    conv.messages.forEach(m => {
        addBubble(m.role, m.text, false);
        addTimestamp(m.time, false);
    });
    scrollBottom();
}

function switchConv(id) {
    if (id === state.currentId) return;
    restoreChat(id);
    saveToStorage();
    closeSidebar();
}

// 复制 / 完成 图标
const COPY_SVG = `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="9" y="9" width="11" height="11" rx="2.2" stroke="currentColor" stroke-width="1.8"/>
    <path d="M5 15V5a2 2 0 012-2h8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
</svg>`;
const CHECK_SVG = `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M5 13l4 4L19 7" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;

// 去除标记和 markdown 符号，得到纯净可复制文本
function toPlain(raw) {
    return raw
        .replace('[VERIFY_FORM]', '')
        .replace(/\*\*(.*?)\*\*/g, '$1')
        .replace(/\*(.*?)\*/g, '$1')
        .replace(/`(.*?)`/g, '$1')
        .trim();
}

// 复制到剪贴板（兼容非安全上下文 file://）
function copyMessage(text, btn) {
    const done = () => {
        btn.classList.add('copied');
        btn.innerHTML = CHECK_SVG;
        setTimeout(() => {
            btn.classList.remove('copied');
            btn.innerHTML = COPY_SVG;
        }, 1400);
    };
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
    } else {
        fallbackCopy(text, done);
    }
}

function fallbackCopy(text, done) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); done(); } catch {}
    document.body.removeChild(ta);
}

// ── 文本渲染（markdown → HTML，防 XSS）────────
// 检测 [VERIFY_FORM] 标记并剥离，返回 { html, hasVerify }
function renderText(raw) {
    const hasVerify = raw.includes('[VERIFY_FORM]');
    const cleaned = raw.replace('[VERIFY_FORM]', '').trim();
    const esc = cleaned
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    const html = esc
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.*?)`/g, '<code>$1</code>')
        .replace(/\n/g, '<br>');
    return { html, hasVerify };
}

// ── DOM helpers ───────────────────────────────
function addBubble(role, text, animate = true) {
    const box = document.getElementById('messages');
    const row = document.createElement('div');
    row.className = `msg-row ${role}`;
    if (!animate) row.style.animation = 'none';

    if (role === 'agent') {
        const av = document.createElement('div');
        av.className = 'msg-av';
        av.innerHTML = EMBLEM_SVG;
        if (!animate) av.style.animation = 'none';
        row.appendChild(av);
    }

    const { html, hasVerify } = renderText(text);
    const b = document.createElement('div');
    b.className = `bubble ${role}`;
    b.innerHTML = html;
    row.appendChild(b);

    // 复制按钮（hover 显现）
    const copyBtn = document.createElement('button');
    copyBtn.className = 'copy-btn';
    copyBtn.title = '复制';
    copyBtn.innerHTML = COPY_SVG;
    copyBtn.onclick = (e) => {
        e.stopPropagation();
        copyMessage(toPlain(text), copyBtn);
    };
    row.appendChild(copyBtn);

    box.appendChild(row);

    // 仅在新消息（非历史回放）时显示核验表单
    if (hasVerify && role === 'agent' && animate) {
        addVerifyForm();
    }

    if (animate) scrollBottom();
}

// ── 身份核验表单 ──────────────────────────────
function addVerifyForm() {
    document.getElementById('verifyForm')?.remove();
    const box = document.getElementById('messages');
    const form = document.createElement('div');
    form.className = 'verify-form';
    form.id = 'verifyForm';
    form.innerHTML = `
        <div class="verify-card">
            <div class="vf-label">身份核验</div>
            <div class="vf-fields">
                <input class="vf-input" id="vfName"  placeholder="持卡人姓名"   type="text"  autocomplete="off">
                <input class="vf-input" id="vfCard"  placeholder="卡号后四位"   type="text"  maxlength="4" inputmode="numeric" autocomplete="off">
                <input class="vf-input" id="vfPhone" placeholder="注册手机号"   type="tel"   maxlength="11" autocomplete="off">
            </div>
            <button class="vf-submit" onclick="submitVerify()">提交核验</button>
        </div>
    `;
    box.appendChild(form);
    scrollBottom();
    setTimeout(() => document.getElementById('vfName')?.focus(), 80);
}

function submitVerify() {
    const name  = document.getElementById('vfName')?.value.trim();
    const card  = document.getElementById('vfCard')?.value.trim();
    const phone = document.getElementById('vfPhone')?.value.trim();

    // 高亮未填字段
    ['vfName','vfCard','vfPhone'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.toggle('vf-error', !el.value.trim());
    });
    if (!name || !card || !phone) return;

    document.getElementById('verifyForm')?.remove();

    // 将三项数据合成一条用户消息发送
    document.getElementById('userInput').value =
        `姓名：${name}，卡号后四位：${card}，手机号：${phone}`;
    sendMessage();
}

function addTimestamp(t, animate = true) {
    const box = document.getElementById('messages');
    const ts = document.createElement('div');
    ts.className = 'ts';
    ts.textContent = t || timeNow();
    if (!animate) ts.style.animation = 'none';
    box.appendChild(ts);
    if (animate) scrollBottom();
}

function addQuickReplies() {
    const box = document.getElementById('messages');
    const wrap = document.createElement('div');
    wrap.className = 'quick-replies';
    wrap.id = 'quickReplies';

    QUICK_HINTS.forEach(hint => {
        const btn = document.createElement('button');
        btn.className = 'quick-btn';
        btn.textContent = hint;
        btn.onclick = () => {
            document.getElementById('userInput').value = hint;
            sendMessage();
        };
        wrap.appendChild(btn);
    });

    box.appendChild(wrap);
    scrollBottom();
}

function removeQuickReplies() {
    document.getElementById('quickReplies')?.remove();
}

function showTyping() {
    const box = document.getElementById('messages');
    const row = document.createElement('div');
    row.id = 'typing'; row.className = 'msg-row agent';

    const av = document.createElement('div');
    av.className = 'msg-av'; av.innerHTML = EMBLEM_SVG;

    const b = document.createElement('div');
    b.className = 'bubble agent typing-shell';
    b.innerHTML = '<span class="dot"></span><span class="dot"></span><span class="dot"></span>';

    row.appendChild(av); row.appendChild(b);
    box.appendChild(row);
    scrollBottom();
}

function hideTyping()  { document.getElementById('typing')?.remove(); }
function clearMessages() { document.getElementById('messages').innerHTML = ''; }

function setWaiting(val) {
    state.waiting = val;
    document.getElementById('sendBtn').disabled = val;
}

function scrollBottom() {
    const box = document.getElementById('messages');
    requestAnimationFrame(() => box.scrollTo({ top: box.scrollHeight, behavior: 'smooth' }));
}

// ── 侧边栏渲染 ────────────────────────────────
function renderSidebar() {
    const list = document.getElementById('convList');
    list.innerHTML = '';

    const ids = Object.keys(state.conversations).reverse();
    if (ids.length === 0) {
        list.innerHTML = '<div class="conv-empty">暂无历史对话</div>';
        return;
    }
    ids.forEach(id => {
        const conv = state.conversations[id];
        const item = document.createElement('div');
        item.className = 'conv-item' + (id === state.currentId ? ' active' : '');
        item.innerHTML = `
            <svg class="conv-icon" width="14" height="14" viewBox="0 0 24 24" fill="none">
                <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"
                    stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
            </svg>
            <span>${conv.title}</span>
            <button class="conv-del" title="删除对话">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                    <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"
                        stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </button>
        `;
        item.onclick = () => switchConv(id);
        item.querySelector('.conv-del').onclick = (e) => {
            e.stopPropagation();
            deleteConv(id);
        };
        list.appendChild(item);
    });
}

// ── 删除对话 ──────────────────────────────────
function deleteConv(id) {
    const item = document.querySelector(`.conv-item`);
    delete state.conversations[id];

    // 如果删的是当前对话，切到下一个或新建
    if (id === state.currentId) {
        const remaining = Object.keys(state.conversations);
        if (remaining.length > 0) {
            restoreChat(remaining[remaining.length - 1]);
        } else {
            startNewConv(false);
        }
    }
    saveToStorage();
    renderSidebar();
}

// ── 侧边栏开关 ────────────────────────────────
function toggleSidebar() {
    const isMobile = window.matchMedia('(max-width:700px)').matches;
    if (isMobile) {
        const sb = document.getElementById('sidebar');
        const open = sb.classList.toggle('open');
        document.getElementById('overlay').classList.toggle('show', open);
    } else {
        // 桌面端：收起/展开侧边栏
        document.querySelector('.layout').classList.toggle('sidebar-collapsed');
    }
}
function closeSidebar() {
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('overlay').classList.remove('show');
}

// ── 主题切换 ──────────────────────────────────
function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    applyTheme(current === 'dark' ? 'light' : 'dark');
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    document.getElementById('iconMoon').style.display = theme === 'dark' ? 'block' : 'none';
    document.getElementById('iconSun').style.display  = theme === 'light' ? 'block' : 'none';
}

// ── 事件处理 ──────────────────────────────────
function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}

function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 130) + 'px';
}

// ── 持久化 ────────────────────────────────────
function saveToStorage() {
    try {
        localStorage.setItem('convs', JSON.stringify(state.conversations));
        localStorage.setItem('currentId', state.currentId);
    } catch {}
}

function loadFromStorage() {
    try {
        const raw = localStorage.getItem('convs');
        if (raw) state.conversations = JSON.parse(raw);
        state.currentId = localStorage.getItem('currentId');
    } catch {}
}

// ── 工具 ──────────────────────────────────────
function timeNow() {
    return new Date().toLocaleTimeString('zh-CN', { hour:'2-digit', minute:'2-digit' });
}

function getSessionId() {
    if (!sessionStorage.getItem('sid'))
        sessionStorage.setItem('sid', Math.random().toString(36).slice(2));
    return sessionStorage.getItem('sid');
}
