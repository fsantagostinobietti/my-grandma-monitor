"""
    Cloned from:
    https://github.com/ha0y/xiaomi_miot_raw/blob/master/custom_components/xiaomi_miot_raw/deps/xiaomi_cloud_new.py
"""
"""
    The base logic was taken from project https://github.com/squachen/micloud

    I had to rewrite the code to work asynchronously and handle timeouts for
    requests to the cloud.

    MIT License

    Copyright (c) 2020 Sammy Svensson

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import locale
import logging
import os
import random
import secrets
import string
import time

from aiohttp import ClientSession, ClientConnectorError
from Crypto.Cipher import ARC4

from token_extractor.token_extractor import XiaomiCloudConnector

_LOGGER = logging.getLogger(__name__)

SERVERS = ['cn', 'de', 'i2', 'ru', 'sg', 'us']
UA = "Android-7.1.1-1.0.0-ONEPLUS A3010-136-%s APP/xiaomi.smarthome APPV/62830"


class MiCloud:
    auth = None
    svr = None
    _fail_count = 0

    def __init__(self, session: ClientSession):
        self.session = session
        self.device_id = get_random_string(16)

    async def login(self, username: str, password: str):
        try:
            payload = await self._login_step1()
            if isinstance(payload, Exception):
                return (-2, payload)

            data = await self._login_step2(username, password, payload)
            if isinstance(data, Exception):
                return (-2, data)
            if 'notificationUrl' in data:
                return (-1, data['notificationUrl'])
            elif not data['location']:
                return (-1, None)

            token = await self._login_step3(data['location'])
            if isinstance(token, Exception):
                return (-2, token)

            self.auth = {
                'user_id': data['userId'],
                'ssecurity': data['ssecurity'],
                'service_token': token
            }
            return (0, None)

        except Exception as e:
            # There should be no exception here?
            _LOGGER.exception(f"Can't login to MiCloud: {e}")
            raise e from None

    def login_by_credientals(self, userId, serviceToken, ssecurity):
        self.auth = {
            'user_id': userId,
            'ssecurity': ssecurity,
            'service_token': serviceToken
        }

        return True

    async def _login_step1(self):
        _LOGGER.debug(f"Logging in to Xiaomi Cloud (1/3)...")
        try:
            r = await self.session.get(
                'https://account.xiaomi.com/pass/serviceLogin',
                cookies={'sdkVersion': '3.8.6', 'deviceId': self.device_id},
                headers={'User-Agent': UA % self.device_id},
                params={'sid': 'xiaomiio', '_json': 'true'})
            raw = await r.read()
            resp: dict = json.loads(raw[11:])
            return {k: v for k, v in resp.items()
                    if k in ('sid', 'qs', 'callback', '_sign')}
        except ClientConnectorError as ex:
            return ex

    async def _login_step2(self, username: str, password: str, payload: dict):
        _LOGGER.debug(f"Logging in to Xiaomi Cloud (2/3)...")
        payload['user'] = username
        payload['hash'] = hashlib.md5(password.encode()).hexdigest().upper()
        try:
            r = await self.session.post(
                'https://account.xiaomi.com/pass/serviceLoginAuth2',
                cookies={'sdkVersion': '3.8.6', 'deviceId': self.device_id},
                data=payload,
                headers={'User-Agent': UA % self.device_id},
                params={'_json': 'true'})
            raw = await r.read()
            resp = json.loads(raw[11:])
            return resp
        except ClientConnectorError as ex:
            return ex

    async def _login_step3(self, location):
        _LOGGER.debug(f"Logging in to Xiaomi Cloud (3/3)...")
        try:
            r = await self.session.get(location, headers={'User-Agent': UA})
            service_token = r.cookies['serviceToken'].value
            return service_token
        except ClientConnectorError as ex:
            return ex

    async def get_total_devices(self, servers: list):
        total = []
        for server in servers:
            devices = await self.get_devices(server)
            if devices is None:
                return None
            total += devices
        return total

    async def get_devices(self, server: str):
        assert server in SERVERS, "Wrong server: " + server
        baseurl = 'https://api.io.mi.com/app' if server == 'cn' \
            else f"https://{server}.api.io.mi.com/app"

        url = '/home/device_list'
        data = '{"getVirtualModel":false,"getHuamiDevices":0}'

        nonce = gen_nonce()
        signed_nonce = gen_signed_nonce(self.auth['ssecurity'], nonce)
        signature = gen_signature(url, signed_nonce, nonce, data)
        try:
            loc = locale.getdefaultlocale()[0] or "en_US"
        except Exception:
            loc = "en_US"
        try:
            r = await self.session.post(baseurl + url, cookies={
                'userId': self.auth['user_id'],
                'serviceToken': self.auth['service_token'],
                'locale': loc
            }, headers={
                'User-Agent': UA,
                'x-xiaomi-protocal-flag-cli': 'PROTOCAL-HTTP2'
            }, data={
                'signature': signature,
                '_nonce': nonce,
                'data': data
            }, timeout=5)

            resp = await r.json(content_type=None)
            assert resp['code'] == 0, resp
            assert 'result' in resp, resp
            return resp['result']['list']

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout while loading MiCloud device list")
        except ClientConnectorError:
            _LOGGER.error("Failed loading MiCloud device list")
        except Exception as ex:
            _LOGGER.exception(f"Can't load devices list: {ex}")

        return None

    async def devicepass(self, server: str, did: str):
        assert server in SERVERS, "Wrong server: " + server
        data = f'{{"did":"{did}"}}'
        resp = await self.request_miot_api('/device/devicepass', data, server)
        assert resp['code'] == 0, resp
        return resp['result']
    
    async def get_tutk_info(self, server: str, did: str):
        assert server in SERVERS, "Wrong server: " + server
        # app_pubkey ??? - can be any random hex string (length>0). It is used somehow by api server to produce 'sign' response (64 length hex string)
        app_pubkey = secrets.token_hex(32)
        data = f'{{"app_pubkey":"{app_pubkey}","did":"{did}","support_vendors":"TUTK_CS2"}}'
        resp = await self.request_miot_api('/v2/device/miss_get_vendor', data, server)
        assert resp['code'] == 0, resp
        return resp['result']


    async def request_miot_api(self, api, data = None, server: str = None):
        server = server or self.svr or 'cn'
        api_base = 'https://api.io.mi.com/app' if server == 'cn' \
            else f"https://{server}.api.io.mi.com/app"
        url = api_base+api

        nonce = gen_nonce()
        signed_nonce = gen_signed_nonce(self.auth['ssecurity'], nonce)
        signature = gen_signature(api, signed_nonce, nonce, data)
        headers = {
            'content-type': "application/x-www-form-urlencoded",
            'x-xiaomi-protocal-flag-cli': "PROTOCAL-HTTP2",
            'connection': "Keep-Alive",
            'accept-encoding': "gzip",
            'cache-control': "no-cache",
        }
        try:
            r = await self.session.post(url, cookies={
                'userId': self.auth['user_id'],
                'serviceToken': self.auth['service_token'],
            }, headers={
                'User-Agent': UA,
                'x-xiaomi-protocal-flag-cli': 'PROTOCAL-HTTP2'
            }, data={
                'signature': signature,
                '_nonce': nonce,
                'data': data
            }, timeout=5)

            self._fail_count = 0
            resp = await r.json(content_type=None)
            if resp.get('message') == 'auth err':
                _LOGGER.error("Invalid Xiaomi credentials")
                return None
            elif resp.get('code') != 0:
                _LOGGER.error(f"Response of {api} from cloud: {resp}")
                return resp
            else:
                # Note: Success here only means that the request is successful, but the control device may not be successful.
                # depends on the code in result
                _LOGGER.info(f"Response of {api} from cloud: {resp}")
                return resp

        except (asyncio.TimeoutError, ClientConnectorError) as ex:
            if self._fail_count < 3 and api == "/miotspec/prop/get":
                self._fail_count += 1
                _LOGGER.info(f"Error while requesting MIoT api {api} : {ex} ({self._fail_count})")
            else:
                _LOGGER.error(f"Error while requesting MIoT api {api} : {ex}")
        except:
            _LOGGER.exception(f"Can't request MIoT api")

    async def request_rpc(self, did, method, params: str = "", server: str = None):
        data = json.dumps({
            "id": 1,
            "method": method,
            "params": params,
        }, separators=(',', ':'))
        return await self.request_miot_api(f'/home/rpc/{did}', data, server)

    async def get_props(self, params: str = "", server: str = None, *, use_rpc = False):
        if not use_rpc:
            return await self.request_miot_api('/miotspec/prop/get', params, server)
        else:
            p = json.loads(params).get('params')
            if p:
                _LOGGER.warn(p)
                if 'did' in p[0]:
                    did = p[0]['did']
                    return await self.request_rpc(did, "get_properties", p, server)
            _LOGGER.error("Need did!")
            return None

    async def set_props(self, params: str = "", server: str = None, *, use_rpc = False):
        if not use_rpc:
            return await self.request_miot_api('/miotspec/prop/set', params, server)
        else:
            p = json.loads(params).get('params')
            if p:
                if 'did' in p[0]:
                    did = p[0]['did']
                    return await self.request_rpc(did, "set_properties", p, server)
            _LOGGER.error("Need did!")
            return None

    async def call_action(self, params: str = "", server: str = None, *, use_rpc = False):
        return await self.request_miot_api('/miotspec/action', params, server)

    async def get_user_device_data(self, did: str, key, type_, server: str = None, *, limit=5):
        data = {
            "uid": self.auth['user_id'],
            "did": did,
            "time_end": 9999999999,
            "time_start": 0,
            "limit": limit,
            "key": key,
            "type": type_,
        }
        params = json.dumps(data, separators=(',', ':'))
        return await self.request_miot_api('/user/get_user_device_data', params, server)

    async def devicepass(self, did: str, server: str):
        """Unknown the meaning of this function"""
        api = "/device/devicepass" 
        # 'toSignAppData' every value is the same
        params = {
            "data": f'{{"did":"{did}","toSignAppData":"494c7dce85faf3293a9385e20a8ac8c0985d9440aba3a4361c6a60f11b07f77a"}}'
            }
        return await self.execute_api_call_encrypted(api, params, server)
    
    async def miss_get_vendor(self, did: str, server: str):
        """TODO"""
        api = '/v2/device/miss_get_vendor'
        # 'app_pubkey' value changes the 'sign' of the response 
        params = {
            "data": f'{{"app_pubkey":"c538d719e8ee7babaaff4486789ed450a41849fe4994aa3c0a098827f4d59865","did":"{did}","support_vendors":"TUTK_CS2"}}'
            }
        return await self.execute_api_call_encrypted(api, params, server)
    
    async def execute_api_call_encrypted(self, api, params, server):
        server = server or self.svr or 'cn'
        api_base = 'https://api.io.mi.com/app' if server == 'cn' \
            else f"https://{server}.api.io.mi.com/app"
        url = api_base+api

        headers = {
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        cookies = {
            "userId": self.auth['user_id'],
            "serviceToken": self.auth['service_token'],
        }
        nonce = gen_nonce()
        ssecurity = self.auth['ssecurity']
        signed_nonce = gen_signed_nonce(ssecurity, nonce)
        fields = generate_enc_params(url, "POST", signed_nonce, nonce, params, ssecurity)
        r = await self.session.post(url, headers=headers, cookies=cookies, params=fields)
        body = await r.text()
        decoded = XiaomiCloudConnector.decrypt_rc4(signed_nonce, body)
        return json.loads(decoded)

def get_random_string(length: int):
    seq = string.ascii_uppercase + string.digits
    return ''.join((random.choice(seq) for _ in range(length)))


def gen_nonce() -> str:
    """Time based nonce."""
    nonce = os.urandom(8) + int(time.time() / 60).to_bytes(4, 'big')
    return base64.b64encode(nonce).decode()


def gen_signed_nonce(ssecret: str, nonce: str) -> str:
    """Nonce signed with ssecret."""
    m = hashlib.sha256()
    m.update(base64.b64decode(ssecret))
    m.update(base64.b64decode(nonce))
    return base64.b64encode(m.digest()).decode()

def gen_signature(url: str, signed_nonce: str, nonce: str, data: str) -> str:
    """Request signature based on url, signed_nonce, nonce and data."""
    sign = '&'.join([url, signed_nonce, nonce, 'data=' + data])
    signature = hmac.new(key=base64.b64decode(signed_nonce),
                         msg=sign.encode(),
                         digestmod=hashlib.sha256).digest()
    return base64.b64encode(signature).decode()

def generate_enc_params(url, method, signed_nonce, nonce, params, ssecurity):
    params['rc4_hash__'] = generate_enc_signature(url, method, signed_nonce, params)
    for k, v in params.items():
        params[k] = encrypt_rc4(signed_nonce, v)
    params.update({
        'signature': generate_enc_signature(url, method, signed_nonce, params),
        'ssecurity': ssecurity,
        '_nonce': nonce,
    })
    return params

def generate_enc_signature(url: str, method: str, signed_nonce: str, params: dict):
    signature_params = [str(method).upper(), url.split("com")[1].replace("/app/", "/")]
    for k, v in params.items():
        signature_params.append(f"{k}={v}")
    signature_params.append(signed_nonce)
    signature_string = "&".join(signature_params)
    return base64.b64encode(hashlib.sha1(signature_string.encode('utf-8')).digest()).decode()

def encrypt_rc4(password: str, payload: str) -> str:
    r = ARC4.new(base64.b64decode(password))
    r.encrypt(bytes(1024))
    return base64.b64encode(r.encrypt(payload.encode())).decode()

def decrypt_rc4(password: str, payload: str) -> bytes:
    r = ARC4.new(base64.b64decode(password))
    r.encrypt(bytes(1024))
    return r.encrypt(base64.b64decode(payload))