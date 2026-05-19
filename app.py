from flask import Flask, request, jsonify
import httpx, os, json, threading, traceback

app = Flask(__name__)

FEISHU_APP_ID = os.environ["FEISHU_APP_ID"]
FEISHU_APP_SECRET = os.environ["FEISHU_APP_SECRET"]
CLAUDE_API_KEY = os.environ["CLAUDE_API_KEY"]
CLAUDE_BASE_URL = os.environ.get("CLAUDE_BASE_URL", "https://api.anthropic.com")

conversations = {}
roles = {}

HELP_TEXT = """可用指令：
/新话题 — 开始新对话（保留历史）
/清除 — 清除对话历史
/总结 — 总结当前对话
/历史 — 查看对话轮数
/导出 — 导出当前对话
/角色 [描述] — 设置机器人角色
/重置角色 — 恢复默认角色
/翻译 [文字] — 快速翻译
/润色 [文字] — 润色文章
/功能 — 查看此帮助"""

@app.route("/", methods=["GET"])
def health():
    return "ok"

def get_feishu_token():
    r = httpx.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                   json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    return r.json()["tenant_access_token"]

def call_claude(messages):
    r = httpx.post(f"{CLAUDE_BASE_URL}/v1/messages",
                   headers={"x-api-key": CLAUDE_API_KEY, "anthropic-version": "2023-06-01"},
                   json={"model": "claude-sonnet-4-6", "max_tokens": 8096, "messages": messages},
                   timeout=60)
    return r.json()["content"][0]["text"]

def ask_claude(open_id, text):
    if open_id not in conversations:
        conversations[open_id] = []
    if open_id not in roles:
        roles[open_id] = None

    cmd = text.strip()

    if cmd == "/新话题":
        conversations[open_id].append({"role": "user", "content": "【系统】新话题开始"})
        conversations[open_id].append({"role": "assistant", "content": "好的，我们开始新话题 ✓"})
        return "新话题已开始 ✓（历史记录已保留）"

    if cmd == "/清除":
        conversations[open_id] = []
        roles[open_id] = None
        return "对话历史已清除 ✓"

    if cmd == "/功能":
        return HELP_TEXT

    if cmd == "/历史":
        count = len([m for m in conversations[open_id] if m["role"] == "user"])
        role_info = f"\n当前角色：{roles[open_id]}" if roles[open_id] else ""
        return f"当前对话共 {count} 轮{role_info}"

    if cmd == "/导出":
        if not conversations[open_id]:
            return "当前没有对话记录。"
        lines = []
        for m in conversations[open_id]:
            if m["role"] == "user" and not m["content"].startswith("【系统】"):
                lines.append(f"我：{m['content']}")
            elif m["role"] == "assistant":
                lines.append(f"AI：{m['content']}")
        return "\n\n".join(lines)

    if cmd == "/重置角色":
        roles[open_id] = None
        return "已恢复默认角色 ✓"

    if cmd.startswith("/角色 "):
        roles[open_id] = cmd[4:].strip()
        return f"角色已设置：{roles[open_id]} ✓"

    if cmd.startswith("/翻译 "):
        content = cmd[4:].strip()
        return call_claude([{"role": "user", "content": f"请将以下内容翻译成中文（如果是中文则翻译成英文），只输出翻译结果：\n{content}"}])

    if cmd.startswith("/润色 "):
        content = cmd[4:].strip()
        return call_claude([{"role": "user", "content": f"请润色以下文字，使其更流畅自然，只输出润色后的结果：\n{content}"}])

    messages = conversations[open_id].copy()
    if roles[open_id]:
        messages = [{"role": "user", "content": f"请扮演：{roles[open_id]}"},
                    {"role": "assistant", "content": "好的，我会扮演这个角色。"}] + messages
    messages.append({"role": "user", "content": text})

    reply = call_claude(messages[-40:])
    conversations[open_id].append({"role": "user", "content": text})
    conversations[open_id].append({"role": "assistant", "content": reply})
    return reply

def reply_feishu(open_id, text):
    token = get_feishu_token()
    httpx.post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
               headers={"Authorization": f"Bearer {token}"},
               json={"receive_id": open_id, "msg_type": "text",
                     "content": json.dumps({"text": text})})

def handle_async(open_id, text):
    try:
        reply = ask_claude(open_id, text)
        reply_feishu(open_id, reply)
    except Exception as e:
        print(f"ERROR: {traceback.format_exc()}")
        reply_feishu(open_id, f"出错了：{str(e)}")

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})
    event = data.get("event", {})
    msg = event.get("message", {})
    if msg.get("message_type") != "text":
        return "ok"
    text = json.loads(msg["content"])["text"]
    open_id = event["sender"]["sender_id"]["open_id"]
    threading.Thread(target=handle_async, args=(open_id, text)).start()
    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
