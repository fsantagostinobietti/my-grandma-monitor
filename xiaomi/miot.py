from http.client import responses

# https://iot.mi.com/new/doc/accesses/direct-access/other-platform-access/control-api
# Status code format (-70xxxyzzz) where:
#   xxx: HTTP standard status code, y: the location where the error occurred, zzz: error code
LOCS = {
    '0': 'client',
    '1': 'Open platform',
    '2': 'Device Cloud',
    '3': 'equipment',
    '4': 'MIOT-SPEC'
}
ERROR_CODES = {
    '000': 'Unknown',
    '001': 'Device does not exist',
    '002': 'Service does not exist',
    '003': 'Property does not exist',
    '004': 'Event does not exist',
    '005': 'Action does not exist',
    '006': 'Device description not found',
    '007': 'Device cloud not found',
    '008': 'Invalid IID (PID, SID, AID, etc.)',
    '009': 'Scene does not exist',
    '011': 'Device offline',
    '013': 'Property is not readable',
    '023': 'Property is not writable',
    '033': 'Property cannot be subscribed',
    '043': 'Property value error',
    '034': 'Action return value error',
    '015': 'Action execution error',
    '025': 'The number of action parameters does not match',
    '035': 'Action parameter error',
    '036': 'Device operation timeout',
    '100': 'The device cannot be operated in its current state',
    '101': 'IR device does not support this operation',
    '901': 'Token does not exist or expires',
    '902': 'Token is invalid',
    '903': 'Authorization expired',
    '904': 'Unauthorized voice device',
    '905': 'Device not bound',
    '999': 'Feature not online',
    '-4001': 'Property is not readable',
    '-4002': 'Property is not writable',
    '-4003': 'Property/Action/Event does not exist',
    '-4004': 'Other internal errors',
    '-4005': 'Property value error',
    '-4006': 'Action in parameters error',
    '-4007': 'did error',
}

def spec_error(errno: int) -> str:
    err = f'{errno}'
    cod = err
    if err[:3] == '-70':
        http = err[3:6]
        loc = err[6:7]
        cod = err[-3:]
        err += f' {responses[int(http)]}: "{ERROR_CODES.get(cod)}" generated in {LOCS.get(loc)}'
    elif cod in ERROR_CODES:
        err += f' {ERROR_CODES.get(cod)}'
    return err