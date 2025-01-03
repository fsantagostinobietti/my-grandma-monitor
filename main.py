import ollama
from ollama import generate
import cv2
import base64
import logging
import time
import os
from log import patch_logging, init_logging
from xiaomi.camera import ts_from_hls, capture_frame_from_camera
from notify import notify



patch_logging()
init_logging(logging.TRACE) # TRACE, DEBUG, ...

logger = logging.getLogger(__name__)

def display_img(img: cv2.typing.MatLike):
    logger.info('Image display. Hit any key to continue ...')
    cv2.imshow("Image", img)
    cv2.waitKey(0)
    cv2.destroyAllWindows() 

def img2b64(img: cv2.typing.MatLike) -> str:
    """Convert OpenCV image into base64 encoding"""
    # Encode raw image as a JPEG
    _, buffer = cv2.imencode('.jpg', img)
    # Convert the buffer to a base64 string
    image_base64 = base64.b64encode(buffer).decode('utf-8')
    return image_base64

def split_img(img: cv2.typing.MatLike) -> list[cv2.typing.MatLike]:
    """Split input image into multiple square images"""
    h, w, _ = img.shape
    # assumption: w > h
    crop_left = img[0:h, 0:h]
    crop_right = img[0:h, w-h:w]
    return [crop_left, crop_right]

class Conversation2:
    """Conversation with AI multi-modal model.

    NB: This implementation leverages the Ollama context parameter to avoid redundant data transmission 
        (image and previous prompts) with every ask() invocation.
        (cfr. https://stephencowchau.medium.com/ollama-context-at-generate-api-output-what-are-those-numbers-b8cbff140d95)
    """
    def __init__(self, model: str):
        self.model = model
        self.context = None

    def ask(
        self,
        msg: str,
        img: cv2.typing.MatLike = None
    ) -> str:
        img_list = None if img is None else [img2b64(img)]
        res = generate(
            model=self.model,
            prompt=msg,
            context=self.context,
            images=img_list
        )
        # update context
        self.context = res['context']
        return res['response'].strip()

class Conversation:
    """Conversation with AI multi-modal model."""
    def __init__(self, model: str):
        self.model = model
        self.messages = []

    def ask(
        self,
        msg: str, 
        img: cv2.typing.MatLike = None
    ) -> str:
        img_list = None if img is None else [img2b64(img)]
        self.messages.append(
            {
                'role': 'user',
                'images': img_list,
                'content': msg,
            }
        )
        response = ollama.chat(
            model=self.model,
            messages=self.messages
        )
        # update conversation history
        self.messages.append( response['message'] )
        return response['message']['content'].strip()

STANCES = {
    'A': 'lying on the floor',
    'B': 'sitting on a chair',
    'C': 'sitting on a couch',
    'D': 'lying on a couch',
    'E': 'standing'
}

def _stances_options() -> str:
    return '\n'.join( [ f'{k}) {v}' for k,v in STANCES.items()] )

def person_in_danger(full_image: cv2.typing.MatLike) -> tuple[bool, str]:
    logger.debug(f'Full image has {full_image.shape} shape')
    valid_stance = None
    for img in split_img(full_image):
        logger.debug(f'Analizing partial image {img.shape} ...')
        # new conversation
        conv = Conversation2('grandma:latest')

        msg='Picture is from a home security camera. Give a description of the picture, with focus on people'
        ans = conv.ask(msg=msg, img=img)
        logger.trace(f'Q: [{msg}] - A: [{ans}]\n')

        msg='How many people are present in the room?'
        ans = conv.ask(msg=msg)
        logger.trace(f'Q: [{msg}] - A: [{ans}]\n')

        msg='Give me a single number that represents how many people are present in the room'
        ans = conv.ask(msg=msg)
        logger.trace(f'Q: [{msg}] - A: [{ans}]\n')
        if ans!='1':
            # '0' - no people in the room => no danger
            # '2', '3', ... people  => care-givers already in the room => no danger
            logger.debug(f'There are {ans} people in the room. No further questions on this partial image.')
            continue # skip remaining questions
        
        msg='Describe the posture and stance of the person.'
        ans = conv.ask(msg=msg)
        logger.trace(f'Q: [{msg}] - A: [{ans}]\n')

        msg="""Choose one of the following state for the person:
""" + _stances_options() + """
Only answer with corresponding capital letter"""
        ans = conv.ask(msg=msg)
        logger.trace(f'Q: [{msg}] - A: [{ans}]\n')
        logger.debug(f"Detected person's state ({ans})")
        if ans=='A':
            # 'lying on the floor' => DANGER
            return True, STANCES[ans]
        valid_stance = ans
        
    # image has been analized and no danger has been recognised
    return False, STANCES[valid_stance] if valid_stance else 'missing'


CAMERA_NAME = os.environ['CAMERA_NAME']
frame = capture_frame_from_camera(CAMERA_NAME)
if frame is not None:
    frame_path = f"history/{CAMERA_NAME}_{int(time.time())}.jpg"
    cv2.imwrite(frame_path, frame)
    danger, stance = person_in_danger(frame)
    msg = f'DANGER! Person is {stance}' if danger else f'All right! Person is {stance}'
    notify(msg, frame_path)


