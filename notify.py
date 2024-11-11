import asyncio
import os
from telethon import TelegramClient, events, sync

# You must get your own api_id and
# api_hash from https://my.telegram.org, under API Development.
# 'MyGrandmaMonitor' app
api_id = int(os.environ['API_ID'])
api_hash = os.environ['API_HASH']

# 'MyGrandmaMonitorBot'
bot_token = os.environ['BOT_TOKEN']

# get the chat_id of a telegram group to which 'MyGrandmaMonitorBot' belongs to
# (see https://gist.github.com/zapisnicar/247d53f8e3980f6013a221d8c7459dc3)
# Group 'MyMonitor'
chat_id = int(os.environ['CHAT_ID']) 

client = TelegramClient('cli', api_id, api_hash)
if os.environ.get('TELETHON_PROXY_IP') and os.environ.get('TELETHON_PROXY_PORT'):
    client.set_proxy(['http', os.environ['TELETHON_PROXY_IP'], int(os.environ['TELETHON_PROXY_PORT'])]) 

async def _notify(msg: str=None, img_path: str=None):
    #print(client.get_me().stringify())
    if msg:
        await client.send_message(chat_id, msg)
    if img_path:
        await client.send_file(chat_id, img_path)

def notify(msg: str=None, img_path: str=None):
    # hack to avoid "There is no current event loop in thread 'MainThread'" error
    # in telethon library
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    with client:
        client.loop.run_until_complete(_notify(msg, img_path))