import asyncio
import aiohttp
import subprocess
import cv2
import time
import json
import m3u8
import logging
import os
from os import path
from requests import get
from xiaomi.cloud import MiCloud
from xiaomi.miot import spec_error

logger = logging.getLogger(__name__)

# xiaomi server
EU = 'de' # european server
# cache for login authentication
AUTH_CACHE = '.auth_cache.json'

def get_did(devices: list[dict], device_name: str) -> str:
    dids = [ e['did'] for e in devices if e['name'] == device_name ]
    if len(dids)==0:
        return None # no device with name 'device_name'
    return dids[0]

def check_errors(obj):
    assert obj['code']==0, f'Error {spec_error(obj['code'])}'
    """ for res in obj['result']:
        assert res['code']==0, f'Error {spec_error(res['code'])}' """

def ts_from_hls(url: str) -> str|None:
    """Extract ts_url from hls_url"""
    # see https://github.com/marcosroriz/fetch-hls-stream/blob/master/fetch_hls_stream.py
    try:
        logger.debug(url)
        m = m3u8.load(url)
        logger.trace('[['+m.dumps()+']]')
        if m.playlists:
            # in multiple playlists select last, which usually has highest resolution
            playlist = m.playlists[-1]
            return ts_from_hls(playlist.absolute_uri)
        if m.segments:
            return m.segments[-1].absolute_uri
        return None
    except Exception as err:
        logger.error(err)
        return None
    
def _cv2_read_frame(ts_url: str, try_hack: bool=False) -> cv2.typing.MatLike|None:
    try:
        cap = cv2.VideoCapture(ts_url)
        if cap.isOpened() == False:
            return None
        if try_hack:
            cap.set(cv2.CAP_PROP_POS_FRAMES,10) # skip 10 frames
        # read one frame
        ret, frame = cap.read()
        return frame
    except Exception as err:
        logger.error(err)
        return None
    
def get_frame_from_hls(hls_url: str) -> cv2.typing.MatLike|None:
    try:
        ts_url = ts_from_hls(hls_url)
        logger.debug(ts_url)
        if not ts_url:
            return None
        frame = _cv2_read_frame(ts_url)
        if frame is None:
            frame = _cv2_read_frame(ts_url, try_hack=True)
        return frame
    except Exception as err:
        logger.error(err)
        with open('test_err.ts','wb') as fp:
            response = get(ts_url)
            fp.write(response.content)
        return None

async def camera_status(mi_cloud: MiCloud, did: str):
    siid = 2 # Camera Control
    piid = 1 # Switch Status
    # params is json string like: '{"params":[ {"did": "296579832", "siid": 2, "piid": 1} ]}'
    # did: Device Id - device unique identifier 
    # siid: Service Id 
    # piid: Property Id
    props = await mi_cloud.get_props(params=f'{{"params":[{{"did": "{did}", "siid": {siid}, "piid": {piid}}}]}}', server=EU) 
    print(props)
    check_errors(props)

async def alexa_stream_status(mi_cloud: MiCloud, did: str):
    # siid = 2 # Camera Control
    # piid = 1 # Switch Status
    siid = 3 # Camera Stream Management for Amazon Alexa
    piid = 1 # Stream Status
    #piid = 3 # Video Attribute
    # params is json string like: '{"params":[ {"did": "296579832", "siid": 2, "piid": 1} ]}'
    # did: Device Id - device unique identifier 
    # siid: Service Id 
    # piid: Property Id
    props = await mi_cloud.get_props(params=f'{{"params":[{{"did": "{did}", "siid": {siid}, "piid": {piid}}}]}}', server=EU) 
    print(props)
    check_errors(props)

async def alexa_start_stream(mi_cloud: MiCloud, did: str):
    siid = 3 # Camera Stream Management for Amazon Alexa
    aiid = 1 # Start Camera Stream for Alexa
    #aiid = 3 # Get Stream Configuration of Camera
    ain = 0  # video-attribute|auto
    # params is json string like: '{"params":{"did": "296579832", "siid": 3, "aiid": 1, "in": [0]}}'
    # aiid: Action Id
    # in: action input (as a list with one element)
    res = await mi_cloud.call_action(params=f'{{"params":{{"did": "{did}", "siid": {siid}, "aiid": {aiid}, "in": [{ain}]}}}}', server=EU)
    print(res)
    check_errors(res)

async def google_start_stream(mi_cloud: MiCloud, did: str) -> str:
    siid = 4 # Camera Stream Management for Google Home
    aiid = 1 # Start Camera Stream for Google
    #ain = 0  # video-attribute|auto
    ain = 1  # video-attribute|1920_1080_20
    # params is json string like: '{"params":{"did": "296579832", "siid": 3, "aiid": 1, "in": [0]}}'
    # aiid: Action Id
    # in: action inputs (as a list)
    res = await mi_cloud.call_action(params=f'{{"params":{{"did": "{did}", "siid": {siid}, "aiid": {aiid}, "in": [{ain}]}}}}', server=EU)
    print(res)
    check_errors(res)
    return res['result']['out'][0] # 'stream_address'

async def google_stop_stream(mi_cloud: MiCloud, did: str):
    siid = 4 # Camera Stream Management for Google Home
    aiid = 2 # Stop Camera Stream for Google
    # params is json string like: '{"params":{"did": "296579832", "siid": 3, "aiid": 1, "in": [0]}}'
    # aiid: Action Id
    # in: action inputs (as a list)
    res = await mi_cloud.call_action(params=f'{{"params":{{"did": "{did}", "siid": {siid}, "aiid": {aiid}, "in": []}}}}', server=EU)
    print(res)
    check_errors(res)

async def _capture_frame_from_camera(camera_name: str) -> cv2.typing.MatLike|None:
    async with aiohttp.ClientSession(trust_env=True) as session: # enable accessing proxy env vars
        mi_cloud = MiCloud(session)

        if path.isfile(AUTH_CACHE):
            print(f'Skip login. Use auth token in {AUTH_CACHE}')
            with open(AUTH_CACHE, 'r', encoding='utf-8') as fp:
                mi_cloud.auth = json.load(fp)
        else:
            ACCOUNT = os.environ['ACCOUNT']
            PASSWORD = os.environ['PASSWORD']
            code, opt = await mi_cloud.login(ACCOUNT, PASSWORD)
            assert code==0, f'code: {code} - Msg: {opt}'
            #print(code, opt)
            # cache auth to avoid login next time
            with open(AUTH_CACHE, 'w', encoding='utf-8') as fp:
                json.dump(mi_cloud.auth, fp)

        # get Device ID for specified camera
        devices = await mi_cloud.get_devices(EU)
        if devices is None:
            return None

        #print(devices)
        did = get_did(devices, device_name=camera_name)
        assert did is not None, 'device not found!'

        print(f'Camera [{did}] status:')
        await camera_status(mi_cloud, did)

        print('\nStart Google Home stream:')
        stream_url = await google_start_stream(mi_cloud, did)

        # capure image frame from video stream
        time.sleep(10)
        #subprocess.run(['/opt/homebrew/bin/ffplay', stream_url]) # 'https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8']) OK
        frame = get_frame_from_hls(stream_url)

        print('\nStop Google Home stream:')
        await google_stop_stream(mi_cloud, did)

        return frame

def capture_frame_from_camera(camera_name: str) -> cv2.typing.MatLike|None:
    """Sync method to capture a single froma from camera"""
    return asyncio.run(_capture_frame_from_camera(camera_name))

