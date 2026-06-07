from flask import Flask, request, jsonify
import json, os, aiohttp, asyncio, requests, binascii
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import like_pb2, like_count_pb2, uid_generator_pb2
from google.protobuf.message import DecodeError

app = Flask(__name__)

ACCOUNTS_FILE = 'accounts.json'
TOKEN_IND_FILE = 'token_ind.json'

# ✅ Load IND tokens for likes
def load_ind_tokens():
    if os.path.exists(TOKEN_IND_FILE):
        with open(TOKEN_IND_FILE, 'r') as f:
            return json.load(f)
    return []

# ✅ Encryption
def encrypt_message(plaintext):
    key = b'Yg&tc%DEuh6%Zc^8'
    iv = b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return binascii.hexlify(cipher.encrypt(pad(plaintext, AES.block_size))).decode()

# ✅ Protobuf helpers
def create_uid_proto(uid):
    pb = uid_generator_pb2.uid_generator()
    pb.saturn_ = int(uid)
    pb.garena = 1
    return pb.SerializeToString()

def create_like_proto(uid):
    pb = like_pb2.like()
    pb.uid = int(uid)
    return pb.SerializeToString()

def decode_protobuf(binary):
    try:
        pb = like_count_pb2.Info()
        pb.ParseFromString(binary)
        return pb
    except DecodeError:
        return None

# ✅ GetPlayerPersonalShow - uses accounts.json token
def make_request(enc_uid, token):
    url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'Expect': "100-continue",
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': "OB53"
    }
    try:
        res = requests.post(url, data=bytes.fromhex(enc_uid), headers=headers, verify=False)
        return decode_protobuf(res.content)
    except:
        return None

# ✅ LikeProfile - uses token_ind.json tokens
async def send_like_request(enc_uid, token):
    url = "https://client.ind.freefiremobile.com/LikeProfile"
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'Expect': "100-continue",
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': "OB53"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=bytes.fromhex(enc_uid), headers=headers, ssl=False) as r:
                return r.status
    except Exception as e:
        print(f"Error in send_like_request: {e}")
        return None

# ✅ Send 220 likes using token_ind.json tokens
async def send_likes(uid):
    ind_tokens = load_ind_tokens()
    if not ind_tokens:
        return []
    
    enc_uid = encrypt_message(create_like_proto(uid))
    
    # Use 220 tokens (cycle through if less available)
    tasks = []
    for i in range(220):
        token_data = ind_tokens[i % len(ind_tokens)]
        token = token_data["token"] if isinstance(token_data, dict) else token_data
        tasks.append(send_like_request(enc_uid, token))
    
    return await asyncio.gather(*tasks)

# ✅ Load accounts for GetPlayerPersonalShow
def load_accounts():
    if os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, 'r') as f:
            return json.load(f)
    return {}

async def fetch_token(session, uid, password):
    url = f"https://jwtforme.vercel.app/semy?uid={uid}&password={password}"
    try:
        async with session.get(url, timeout=10) as res:
            if res.status == 200:
                text = await res.text()
                try:
                    data = json.loads(text)
                    if isinstance(data, list) and len(data) > 0 and "token" in data[0]:
                        return data[0]["token"]
                    elif isinstance(data, dict) and "token" in data:
                        return data["token"]
                except:
                    return None
    except:
        return None
    return None

async def get_accounts_token():
    accounts = load_accounts()
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_token(session, uid, password) for uid, password in accounts.items()]
        results = await asyncio.gather(*tasks)
        return [token for token in results if token]

# ✅ Main endpoint
@app.route('/like', methods=['GET'])
def like_handler():
    uid = request.args.get("uid")
    if not uid:
        return jsonify({"error": "Missing UID"}), 400

    try:
        # Get token for GetPlayerPersonalShow
        acc_tokens = asyncio.run(get_accounts_token())
        if not acc_tokens:
            return jsonify({"error": "No valid account tokens"}), 401

        # Get player info BEFORE likes
        enc_uid = encrypt_message(create_uid_proto(uid))
        before = make_request(enc_uid, acc_tokens[0])
        if not before:
            return jsonify({"error": "Failed to retrieve player info"}), 500

        before_data = json.loads(MessageToJson(before))
        likes_before = int(before_data.get("AccountInfo", {}).get("Likes", 0))
        nickname = before_data.get("AccountInfo", {}).get("PlayerNickname", "Unknown")

        # SEND 220 LIKES using token_ind.json
        responses = asyncio.run(send_likes(uid))
        success_count = sum(1 for r in responses if r == 200)

        # Get player info AFTER likes
        after = make_request(enc_uid, acc_tokens[0])
        likes_after = likes_before
        if after:
            after_data = json.loads(MessageToJson(after))
            likes_after = int(after_data.get("AccountInfo", {}).get("Likes", 0))

        return jsonify({
            "PlayerNickname": nickname,
            "UID": uid,
            "LikesBeforecommand": likes_before,
            "LikesAftercommand": likes_after,
            "LikesGivenByAPI": likes_after - likes_before,
            "SuccessfulRequests": success_count,
            "TotalRequests": len(responses),
            "status": 1 if likes_after > likes_before else 2
        })

    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@app.route('/')
def home():
    return jsonify({"status": "online", "message": "Like API is running ✅"})

# Local run only
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)