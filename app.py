from flask import Flask, request, jsonify
import json, binascii, asyncio, aiohttp, urllib3, time
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import uid_generator_pb2
import like_count_pb2

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# ================= CONFIG =================
TARGET_VISITS = 1000        # 🔥 FIXED VISITS
MAX_DURATION = 60           # ⏱ seconds safety
AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV = b'6oyZDr22E3ychjM%'
# ==========================================


# -------- Token Loader --------
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
        return []


# -------- Encrypt UID --------
def encrypt_message(data: bytes):
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    encrypted = cipher.encrypt(pad(data, AES.block_size))
    return binascii.hexlify(encrypted).decode()


def create_protobuf(uid):
    msg = uid_generator_pb2.uid_generator()
    msg.saturn_ = int(uid)
    msg.garena = 1
    return msg.SerializeToString()


def enc(uid):
    return encrypt_message(create_protobuf(uid))


# -------- Decode Response --------
def decode_protobuf(binary):
    info = like_count_pb2.Info()
    info.ParseFromString(binary)
    return info


# -------- Request Sender --------
async def make_request(encrypted_uid, region, token, session):
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
            "X-Unity-Version": "2018.4.11f1"
        }

        async with session.post(
            url,
            data=bytes.fromhex(encrypted_uid),
            headers=headers,
            ssl=False,
            timeout=5
        ) as r:
            if r.status != 200:
                return None
            raw = await r.read()
            return decode_protobuf(raw)

    except:
        return None


# ================= API =================
@app.route("/visit", methods=["GET"])
async def visit():
    uid = request.args.get("uid")
    region = request.args.get("region", "").upper()

    if not uid or not region:
        return jsonify({"error": "uid & region required"}), 400

    tokens = load_tokens(region)
    if not tokens:
        return jsonify({"error": "No tokens available"}), 500

    encrypted_uid = enc(uid)

    success = 0
    failed = 0
    player_name = None
    player_uid = None
    likes = 0

    start_time = time.time()

    async with aiohttp.ClientSession() as session:
        while success < TARGET_VISITS:
            if time.time() - start_time >= MAX_DURATION:
                break

            tasks = [
                make_request(encrypted_uid, region, t["token"], session)
                for t in tokens
            ]

            results = await asyncio.gather(*tasks)

            for info in results:
                if success >= TARGET_VISITS:
                    break

                if info:
                    if not player_name:
                        data = json.loads(MessageToJson(info))
                        player_name = data.get("AccountInfo", {}).get("PlayerNickname")
                        player_uid = data.get("AccountInfo", {}).get("UID")
                        likes = (
                            data.get("LikeInfo", {}).get("TotalLikes")
                            or data.get("PersonalShowInfo", {}).get("Likes")
                            or 0
                        )
                    success += 1
                else:
                    failed += 1

    return jsonify({
        "Target": TARGET_VISITS,
        "Success": success,
        "Failed": failed,
        "Duration": round(time.time() - start_time, 2),
        "Player": player_name,
        "UID": player_uid,
        "Likes": likes
    })


# ================= RUN =================
if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app.run(host="0.0.0.0", port=5000, debug=False)
