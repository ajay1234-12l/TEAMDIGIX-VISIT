from flask import Flask, request, jsonify
import json
import binascii
import os
import time
from datetime import date
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import aiohttp
import asyncio
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from google.protobuf.json_format import MessageToJson
import uid_generator_pb2
import like_count_pb2

app = Flask(__name__)

# ================= CONFIG =================
API_KEY = "TEAMDIGIX"
DAILY_LIMIT = 100
USAGE_FILE = "usage.json"

# ================= USAGE HANDLER =================
def load_usage():
    today = str(date.today())
    if not os.path.exists(USAGE_FILE):
        return {"date": today, "count": 0}

    with open(USAGE_FILE, "r") as f:
        data = json.load(f)

    if data.get("date") != today:
        return {"date": today, "count": 0}

    return data


def save_usage(data):
    with open(USAGE_FILE, "w") as f:
        json.dump(data, f)


# ================= TOKEN LOADER =================
def load_tokens(region):
    try:
        if region == "IND":
            file = "token_ind.json"
        elif region in {"BR", "US", "SAC", "NA"}:
            file = "token_sac.json"
        else:
            file = "token_bd.json"

        with open(file, "r") as f:
            return json.load(f)
    except:
        return None


# ================= ENCRYPTION =================
def encrypt_message(plaintext):
    key = b'Yg&tc%DEuh6%Zc^8'
    iv = b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded = pad(plaintext, AES.block_size)
    encrypted = cipher.encrypt(padded)
    return binascii.hexlify(encrypted).decode()


def create_protobuf(uid):
    msg = uid_generator_pb2.uid_generator()
    msg.saturn_ = int(uid)
    msg.garena = 1
    return msg.SerializeToString()


def enc(uid):
    return encrypt_message(create_protobuf(uid))


# ================= PROTO DECODE =================
def decode_protobuf(binary):
    info = like_count_pb2.Info()
    info.ParseFromString(binary)
    return info


# ================= ASYNC REQUEST =================
async def make_request_async(enc_uid, region, token, session):
    try:
        if region == "IND":
            url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
        elif region in {"BR", "US", "SAC", "NA"}:
            url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
        else:
            url = "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"

        headers = {
            "User-Agent": "Dalvik/2.1.0",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "ReleaseVersion": "OB51"
        }

        async with session.post(
            url,
            data=bytes.fromhex(enc_uid),
            headers=headers,
            ssl=False,
            timeout=5
        ) as r:
            if r.status != 200:
                return None

            raw = await r.read()
            return decode_protobuf(bytes.fromhex(raw.hex()))
    except:
        return None


# ================= MAIN API =================
@app.route("/visit", methods=["GET"])
async def visit():
    start_time = time.perf_counter()

    # 🔐 API KEY CHECK
    key = request.args.get("key")
    if key != API_KEY:
        return jsonify({"error": "Invalid API Key"}), 403

    # 📊 DAILY LIMIT
    usage = load_usage()
    if usage["count"] >= DAILY_LIMIT:
        return jsonify({
            "error": "Daily limit exceeded",
            "RequestsToday": f"{usage['count']}/{DAILY_LIMIT}"
        }), 429

    usage["count"] += 1
    save_usage(usage)

    uid = request.args.get("uid")
    region = request.args.get("region", "").upper()

    if not uid or not region:
        return jsonify({"error": "UID and region required"}), 400

    tokens = load_tokens(region)
    if not tokens:
        return jsonify({"error": "Token file missing"}), 500

    encrypted_uid = enc(uid)

    success = 0
    failed = 0
    name = None
    likes = 0

    async with aiohttp.ClientSession() as session:
        tasks = [
            make_request_async(encrypted_uid, region, t["token"], session)
            for t in tokens
        ]
        results = await asyncio.gather(*tasks)

    for r in results:
        if r:
            success += 1
            if not name:
                data = json.loads(MessageToJson(r))
                name = data.get("AccountInfo", {}).get("PlayerNickname", "")
                likes = int(
                    data.get("LikeInfo", {}).get("TotalLikes", 0)
                )
        else:
            failed += 1

    duration = round(time.perf_counter() - start_time, 2)

    return jsonify({
        "TotalVisits": len(tokens),
        "SuccessfulVisits": success,
        "FailedVisits": failed,
        "PlayerNickname": name,
        "UID": int(uid),
        "Likes": likes,
        "Duration": f"{duration}s",
        "RequestsToday": f"{usage['count']}/{DAILY_LIMIT}",
        "Key": "TEAMDIGIX"
    })


# ================= RUN =================
if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app.run(host="0.0.0.0", port=5000, debug=False)
