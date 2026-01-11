from flask import Flask, request, jsonify
import json
import binascii
import time
import asyncio
import aiohttp
import urllib3

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson

import uid_generator_pb2
import like_count_pb2

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# ---------- Load Tokens ----------
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


# ---------- Encryption ----------
def encrypt_message(plaintext):
    key = b'Yg&tc%DEuh6%Zc^8'
    iv = b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded = pad(plaintext, AES.block_size)
    encrypted = cipher.encrypt(padded)
    return binascii.hexlify(encrypted).decode()


# ---------- Protobuf ----------
def create_protobuf(uid):
    msg = uid_generator_pb2.uid_generator()
    msg.saturn_ = int(uid)
    msg.garena = 1
    return msg.SerializeToString()


def enc(uid):
    return encrypt_message(create_protobuf(uid))


# ---------- Decode ----------
def decode_protobuf(binary):
    info = like_count_pb2.Info()
    info.ParseFromString(binary)
    return info


# ---------- Async Request ----------
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
            "Content-Type": "application/x-www-form-urlencoded"
        }

        async with session.post(
            url,
            data=bytes.fromhex(enc_uid),
            headers=headers,
            ssl=False,
            timeout=6
        ) as r:
            if r.status != 200:
                return None
            raw = await r.read()
            return decode_protobuf(raw)

    except:
        return None


# ---------- Route ----------
@app.route("/visit", methods=["GET"])
async def visit():
    start_time = time.time()  # ⏱️ START DURATION

    uid = request.args.get("uid")
    region = request.args.get("region", "").upper()

    if not uid or not region:
        return jsonify({"error": "uid and region required"}), 400

    tokens = load_tokens(region)
    if not tokens:
        return jsonify({"error": "Token load failed"}), 500

    encrypted_uid = enc(uid)

    success = 0
    failed = 0
    nickname = None
    likes = 0

    async with aiohttp.ClientSession() as session:
        tasks = [
            make_request_async(encrypted_uid, region, t["token"], session)
            for t in tokens
        ]
        results = await asyncio.gather(*tasks)

    for res in results:
        if res:
            success += 1
            if not nickname:
                data = json.loads(MessageToJson(res))
                nickname = data.get("AccountInfo", {}).get("PlayerNickname", "")
                likes = (
                    data.get("LikeInfo", {}).get("TotalLikes")
                    or data.get("AccountInfo", {}).get("TotalLikes", 0)
                )
        else:
            failed += 1

    duration = round(time.time() - start_time, 2)  # ⏱️ END DURATION

    return jsonify({
        "UID": int(uid),
        "Region": region,
        "TotalVisits": len(tokens),
        "SuccessfulVisits": success,
        "FailedVisits": failed,
        "PlayerNickname": nickname,
        "Likes": int(likes),
        "DurationSeconds": duration   # ✅ ADDED
    })


# ---------- Run ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
