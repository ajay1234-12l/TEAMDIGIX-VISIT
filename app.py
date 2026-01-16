from flask import Flask, request, jsonify
import json
import binascii
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import aiohttp
import asyncio
import urllib3
import random
import time
from concurrent.futures import ThreadPoolExecutor
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from google.protobuf.json_format import MessageToJson
import uid_generator_pb2
import like_count_pb2

app = Flask(__name__)

# Thread pool for parallel processing
executor = ThreadPoolExecutor(max_workers=50)

# Token management
TOKENS = {
    "IND": [],
    "SAC": [],  # For BR, US, SAC, NA
    "BD": []   # For other regions
}

# Load all tokens at startup
def load_all_tokens():
    try:
        # IND tokens
        with open("token_ind.json", "r") as f:
            tokens_data = json.load(f)
            if isinstance(tokens_data, list):
                TOKENS["IND"] = [token['token'] for token in tokens_data if 'token' in token]
            print(f"Loaded {len(TOKENS['IND'])} IND tokens")
    except:
        print("No IND tokens found")
        TOKENS["IND"] = []
    
    try:
        # SAC tokens (for BR, US, SAC, NA)
        with open("token_sac.json", "r") as f:
            tokens_data = json.load(f)
            if isinstance(tokens_data, list):
                TOKENS["SAC"] = [token['token'] for token in tokens_data if 'token' in token]
            print(f"Loaded {len(TOKENS['SAC'])} SAC tokens")
    except:
        print("No SAC tokens found")
        TOKENS["SAC"] = []
    
    try:
        # BD tokens (for other regions)
        with open("token_bd.json", "r") as f:
            tokens_data = json.load(f)
            if isinstance(tokens_data, list):
                TOKENS["BD"] = [token['token'] for token in tokens_data if 'token' in token]
            print(f"Loaded {len(TOKENS['BD'])} BD tokens")
    except:
        print("No BD tokens found")
        TOKENS["BD"] = []
    
    # Print summary
    total_tokens = len(TOKENS["IND"]) + len(TOKENS["SAC"]) + len(TOKENS["BD"])
    print(f"Total tokens loaded: {total_tokens}")

# Load tokens on startup
load_all_tokens()

def encrypt_message(plaintext):
    try:
        key = b'Yg&tc%DEuh6%Zc^8'
        iv = b'6oyZDr22E3ychjM%'
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_message = pad(plaintext, AES.block_size)
        encrypted_message = cipher.encrypt(padded_message)
        return binascii.hexlify(encrypted_message).decode('utf-8')
    except Exception as e:
        print(f"Encryption error: {e}")
        return None

def create_protobuf(uid):
    try:
        message = uid_generator_pb2.uid_generator()
        message.saturn_ = int(uid)
        message.garena = 1
        return message.SerializeToString()
    except Exception as e:
        print(f"Protobuf creation error: {e}")
        return None

def enc(uid):
    protobuf_data = create_protobuf(uid)
    if protobuf_data is None:
        return None
    encrypted_uid = encrypt_message(protobuf_data)
    return encrypted_uid

def decode_protobuf(binary):
    try:
        items = like_count_pb2.Info()
        items.ParseFromString(binary)
        return items
    except Exception as e:
        print(f"Protobuf decode error: {e}")
        return None

def get_tokens_for_region(region, count=2000):
    """Get tokens for specific region, up to count"""
    region_upper = region.upper()
    
    if region_upper == "IND":
        tokens = TOKENS["IND"]
    elif region_upper in {"BR", "US", "SAC", "NA"}:
        tokens = TOKENS["SAC"]
    else:
        tokens = TOKENS["BD"]
    
    # If we have less tokens than requested, we can reuse them
    if len(tokens) >= count:
        return random.sample(tokens, count)
    else:
        # Reuse tokens to reach requested count
        result = []
        needed = count
        while needed > 0:
            if needed >= len(tokens):
                result.extend(tokens)
                needed -= len(tokens)
            else:
                result.extend(random.sample(tokens, needed))
                needed = 0
        return result[:count]

def get_url_for_region(region):
    region_upper = region.upper()
    
    if region_upper == "IND":
        return "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    elif region_upper in {"BR", "US", "SAC", "NA"}:
        return "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    else:
        return "https://clientbp.ggwhitehawk.com/GetPlayerPersonalShow"

async def make_request_with_retry(encrypted_target_uid, region, token, session, retries=3):
    """Make request with retry mechanism"""
    url = get_url_for_region(region)
    edata = bytes.fromhex(encrypted_target_uid)
    
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'Expect': "100-continue",
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': "OB52"
    }
    
    for attempt in range(retries):
        try:
            async with session.post(url, data=edata, headers=headers, 
                                   ssl=False, timeout=10) as response:
                if response.status == 200:
                    hex_data = await response.read()
                    binary = bytes.fromhex(hex_data.hex())
                    decode = decode_protobuf(binary)
                    return decode, True
                elif response.status == 429:  # Too many requests
                    await asyncio.sleep(1)  # Wait before retry
                else:
                    print(f"Request failed with status: {response.status}")
        except asyncio.TimeoutError:
            print(f"Timeout on attempt {attempt + 1}")
        except Exception as e:
            print(f"Request error on attempt {attempt + 1}: {e}")
        
        # Exponential backoff
        if attempt < retries - 1:
            await asyncio.sleep(2 ** attempt)
    
    return None, False

def extract_player_info(info):
    """Extract player information from protobuf response"""
    if info is None:
        return None, None, None, None
    
    try:
        jsone = MessageToJson(info)
        data_info = json.loads(jsone)
        
        # Player basic info
        player_name = str(data_info.get('AccountInfo', {}).get('PlayerNickname', ''))
        player_uid = int(data_info.get('AccountInfo', {}).get('UID', 0))
        
        # Get level
        player_level = data_info.get('AccountInfo', {}).get('PlayerLevel', 0)
        if player_level == 0:
            player_level = data_info.get('AccountInfo', {}).get('PlayerExperience', {}).get('PlayerLevel', 0)
        if player_level == 0:
            player_level = data_info.get('AccountInfo', {}).get('ExperienceInfo', {}).get('Level', 0)
        
        # Search recursively for level
        if player_level == 0:
            def find_level(data):
                if isinstance(data, dict):
                    for key, value in data.items():
                        if key.lower() == 'level' or key.lower() == 'playerlevel':
                            return value
                        result = find_level(value)
                        if result:
                            return result
                elif isinstance(data, list):
                    for item in data:
                        result = find_level(item)
                        if result:
                            return result
                return 0
            
            player_level = find_level(data_info)
        
        player_level = int(player_level) if player_level else 0
        
        # Get likes
        player_likes = data_info.get('LikeInfo', {}).get('TotalLikes', 0)
        if player_likes == 0:
            player_likes = data_info.get('PersonalShowInfo', {}).get('Likes', 0)
        if player_likes == 0:
            player_likes = data_info.get('AccountInfo', {}).get('TotalLikes', 0)
        
        # Search recursively for likes
        if player_likes == 0:
            def find_likes(data):
                if isinstance(data, dict):
                    for key, value in data.items():
                        if 'like' in key.lower():
                            return value
                        result = find_likes(value)
                        if result:
                            return result
                elif isinstance(data, list):
                    for item in data:
                        result = find_likes(item)
                        if result:
                            return result
                return 0
            
            player_likes = find_likes(data_info)
        
        player_likes = int(player_likes) if player_likes else 0
        
        return player_name, player_uid, player_level, player_likes
        
    except Exception as e:
        print(f"Error extracting player info: {e}")
        return None, None, None, None

async def process_batch(tokens_batch, encrypted_target_uid, region, session, batch_number):
    """Process a batch of tokens"""
    batch_results = []
    for token in tokens_batch:
        info, success = await make_request_with_retry(encrypted_target_uid, region, token, session)
        batch_results.append((info, success))
    return batch_results

@app.route('/visit', methods=['GET'])
async def visit():
    start_time = time.time()
    
    target_uid = request.args.get("uid")
    region = request.args.get("region", "").upper()
    
    # Get number of visits from query parameter, default to 2000
    visits_requested = int(request.args.get("visits", 2000))
    
    if not target_uid or not region:
        return jsonify({"error": "Target UID and region are required"}), 400
    
    if visits_requested > 5000:  # Safety limit
        visits_requested = 5000
    
    try:
        # Encrypt target UID
        encrypted_target_uid = enc(target_uid)
        if encrypted_target_uid is None:
            return jsonify({"error": "Failed to encrypt UID"}), 400
        
        # Get tokens for the region
        tokens = get_tokens_for_region(region, visits_requested)
        
        if not tokens:
            return jsonify({"error": f"No tokens available for region {region}"}), 400
        
        total_tokens = len(tokens)
        print(f"Starting {total_tokens} visits for UID {target_uid} in region {region}")
        
        # Initialize counters
        success_count = 0
        failed_count = 0
        player_info_set = False
        player_name = None
        player_uid = None
        player_level = None
        player_likes = None
        
        # Create semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(100)  # Max 100 concurrent requests
        
        async def process_token(token):
            nonlocal player_info_set, player_name, player_uid, player_level, player_likes
            async with semaphore:
                info, success = await make_request_with_retry(encrypted_target_uid, region, token, session)
                
                if success and info and not player_info_set:
                    name, uid, level, likes = extract_player_info(info)
                    if name and uid:
                        player_name = name
                        player_uid = uid
                        player_level = level
                        player_likes = likes
                        player_info_set = True
                
                return success
        
        # Process all tokens
        async with aiohttp.ClientSession() as session:
            tasks = [process_token(token) for token in tokens]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Count results
        for result in results:
            if isinstance(result, bool):
                if result:
                    success_count += 1
                else:
                    failed_count += 1
            else:
                failed_count += 1
        
        # Calculate time taken
        time_taken = time.time() - start_time
        
        # Prepare response
        summary = {
            "status": "success",
            "message": "Visits completed successfully",
            "data": {
                "target_uid": target_uid,
                "region": region,
                "total_visits_attempted": total_tokens,
                "successful_visits": success_count,
                "failed_visits": failed_count,
                "success_rate": f"{(success_count/total_tokens)*100:.2f}%" if total_tokens > 0 else "0%",
                "player_info": {
                    "nickname": player_name,
                    "uid": player_uid,
                    "level": player_level,
                    "likes": player_likes
                },
                "performance": {
                    "time_taken_seconds": round(time_taken, 2),
                    "visits_per_second": round(success_count/time_taken, 2) if time_taken > 0 else 0
                }
            }
        }
        
        print(f"Completed {success_count}/{total_tokens} visits in {time_taken:.2f} seconds")
        return jsonify(summary)
        
    except Exception as e:
        print(f"Error in visit endpoint: {e}")
        return jsonify({
            "status": "error",
            "message": str(e),
            "data": None
        }), 500

@app.route('/visit_legacy', methods=['GET'])
async def visit_legacy():
    """Legacy endpoint for backward compatibility"""
    target_uid = request.args.get("uid")
    region = request.args.get("region", "").upper()
    
    if not target_uid or not region:
        return jsonify({"error": "Target UID and region are required"}), 400
    
    try:
        # Use 1000 visits for legacy endpoint
        request.args = request.args.copy()
        request.args["visits"] = 1000
        
        # Call the main visit function
        return await visit()
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/stats', methods=['GET'])
def stats():
    """Get token statistics"""
    return jsonify({
        "status": "success",
        "data": {
            "tokens_available": {
                "IND": len(TOKENS["IND"]),
                "SAC": len(TOKENS["SAC"]),
                "BD": len(TOKENS["BD"]),
                "total": len(TOKENS["IND"]) + len(TOKENS["SAC"]) + len(TOKENS["BD"])
            },
            "max_visits_per_request": 5000,
            "default_visits": 2000,
            "concurrent_limit": 100
        }
    })

@app.route('/reload_tokens', methods=['POST'])
def reload_tokens():
    """Reload tokens from files"""
    try:
        load_all_tokens()
        return jsonify({
            "status": "success",
            "message": "Tokens reloaded successfully",
            "data": {
                "IND": len(TOKENS["IND"]),
                "SAC": len(TOKENS["SAC"]),
                "BD": len(TOKENS["BD"])
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Health check endpoint
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "service": "freefire_visits_api"})

if __name__ == '__main__':
    print("=" * 50)
    print("FreeFire Visits API Started")
    print("=" * 50)
    print(f"Available endpoints:")
    print(f"  GET  /visit?uid=<uid>&region=<region>&visits=<count>")
    print(f"  GET  /visit_legacy?uid=<uid>&region=<region>")
    print(f"  GET  /stats")
    print(f"  POST /reload_tokens")
    print(f"  GET  /health")
    print("=" * 50)
    
    # Run the app
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
