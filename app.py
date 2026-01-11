from flask import Flask, request, jsonify
import json, os, time, binascii, asyncio
from datetime import date
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import aiohttp
from google.protobuf.json_format import MessageToJson
import uid_generator_pb2
import like_count_pb2

app = Flask(__name__)

# ================= CONFIG =================
DAILY_LIMIT = 100
USAGE_FILE = "usage.json"

# ================= USAGE =================
def load_usage():
    today = str(date.today())
    if not os.path.exists(USAGE_FILE):
        return {"date": today, "count": 0}
    with open(USAGE_FILE) as f:
        data = json.load(f)
    if data.get("date") != today:
        return {"date": today, "count": 0}
    return data

def save_usage(data):
    with open(USAGE_FILE, "w") as f:
        json.dump(data, f)

# ================= TOKENS =================
def load_tokens(region):
    try:
        if region == "IND":
            file = "token_ind.json"
        elif region in {"BR", "US", "SAC", "NA"}:
            file = "token_sac.json"
        else:
            file = "token_bd.json"
        with open(file) as f:
            return json.load(f)
    except:
        return None

# ================= ENCRYPT =================
def encrypt_message(data):
    key = b'Yg&tc%DEuh6%Zc^8'
    iv = b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return binascii.hexlify(cipher.encrypt(pad(data, AES.block_size))).decode()

def enc(uid):
    msg = uid_generator_pb2.uid_generator()
    msg.saturn_ = int(uid)
    msg.garena = 1
    return encrypt_message(msg.SerializeToString())

# ================= PROTO =================
def decode(binary):
    info = like_count_pb2.Info()
    info.ParseFromString(binary)
    return info

async def hit(enc_uid, region, token, session):
    try:
        if region == "IND":
            url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
        elif region in {"BR", "US", "SAC", "NA"}:
            url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
        else:
            url = "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"

        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "Dalvik/2.1.0",
            "Content-Type": "application/x-www-form-urlencoded",
            "ReleaseVersion": "OB51"
        }

        async with session.post(
            url,
            data=bytes.fromhex(enc_uid),
            headers=headers,
            timeout=5,
            ssl=False
        ) as r:
            if r.status != 200:
                return None
            raw = await r.read()
            return decode(bytes.fromhex(raw.hex()))
    except:
        return None

async def process(uid, region, tokens):
    enc_uid = enc(uid)
    success = failed = 0
    name = None
    likes = 0

    async with aiohttp.ClientSession() as session:
        tasks = [hit(enc_uid, region, t["token"], session) for t in tokens]
        results = await asyncio.gather(*tasks)

    for r in results:
        if r:
            success += 1
            if not name:
                data = json.loads(MessageToJson(r))
                name = data.get("AccountInfo", {}).get("PlayerNickname", "")
                likes = int(data.get("LikeInfo", {}).get("TotalLikes", 0))
        else:
            failed += 1

    return success, failed, name, likes

# ================= ROUTE =================
@app.route("/visit")
def visit():
    start = time.perf_counter()

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
        return jsonify({"error": "UID & region required"}), 400

    tokens = load_tokens(region)
    if not tokens:
        return jsonify({"error": "Token file missing"}), 500

    success, failed, name, likes = asyncio.run(process(uid, region, tokens))
    duration = round(time.perf_counter() - start, 2)

    return jsonify({
        "TotalVisits": len(tokens),
        "SuccessfulVisits": success,
        "FailedVisits": failed,
        "PlayerNickname": name,
        "UID": int(uid),
        "Likes": likes,
        "Duration": f"{duration}s",
        "RequestsToday": f"{usage['count']}/{DAILY_LIMIT}"
    })

# ================= RUN =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
