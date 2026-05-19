from flask import Flask, request, jsonify
import httpx, os, json, threading

app = Flask(__name__)

FEISHU_APP_ID = os.environ["FEISHU_APP_ID"]
FEISHU_APP_SECRET = os.environ["FEISHU_APP_SECRET"]
CLAUDE_API_KEY = os.environ["CLAUDE_API_KEY"]
CLAUDE_BASE_URL = os.environ.get("CLAUDE_BASE_URL", "https://api.anthropic.com")

def get_feishu_token():
    r = httpx.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                   json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    return r.json()["tenant_access_token"]

def ask_claude(text):
    r = httpx.post(f"{CLAUDE_BASE_URL}/v1/messages",
                   headers={"x-api-key": CLAUDE_API_KEY, "anthropic-version": "2023-06-01"},
                   json={"model": "claude-3-5-sonnet-20241022", "max_tokens": 1024,
                         "messages": [{"role": "user", "content": text}]},
                   timeout=30)
    return r.json()["content"][0]["text"]

def reply_feishu(open_id, text):
    token = get_feishu_token()
    httpx.post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
               headers={"Authorization": f"Bearer {token}"},
               json={"receive_id": open_id, "msg_type": "text",
                     "content": json.dumps({"text": text})})

def handle_async(open_id, text):
    try:
        reply = ask_claude(text)
        reply_feishu(open_id, reply)
    except Exception as e:
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
