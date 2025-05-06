
"""MQTT interface for Neato Serial."""
from config import settings
import json
import time
import sys
import paho.mqtt.client as mqtt
from neatoserial import NeatoSerial, CombinedState
import logging
import threading
from restartMqtt import RestartMqtt

ns = NeatoSerial()
restartMqtt = RestartMqtt()
state: CombinedState = None

#Function utilized when MQTT Autodiscovery is used - uses "state" schema in Homeassistant
def discovery_payload():
    config_data = {
        'availability': [{'topic': f'neato_serial_{state.serial_number}/state'}],
        'command_topic': settings['mqtt']['command_topic'],
        'device': {
            'identifiers': [f'Neato_serial_{state.serial_number}'],
            'name': 'neato_serial_vacuum',
            'manufacturer': 'Neato Robotics',
            'model': 'XV Series',
            'sw_version': state.software_version
        },
        'name': 'neato_serial',
        'unique_id': f'neato_serial_{state.serial_number}',
        'payload_clean_spot': 'Clean Spot',
        'payload_locate': 'PlaySound 19',
        'payload_start': 'Clean',
        'payload_stop': 'Clean Stop',
        'schema': 'state',
        'state_topic': settings['mqtt']['state_topic'],
        'json_attributes_topic': f'vacuum/neato_serial_{state.serial_number}/attributes',
        'supported_features': ['start', 'stop', 'battery', 'status', 'locate', 'clean_spot']
    }
    state_data = {}
    attributes_data = {}
    state_data["battery_level"] = state.battery_level
    if not ns.isUsbEnabled:
        state_data["battery_icon"] = "mdi:battery-unknown"
        
    state_data["fan_speed"] = state.fan_speed
    attributes_data["charging"] = state.is_charging
    attributes_data["USB Enabled"] = ns.isUsbEnabled
    if state.is_docked:
        state_data["state"] = "docked"
    elif state.is_cleaning:
        state_data["state"] = "cleaning"
    elif state.error:
        log.debug(f"Error from Neato: {str(state.error[1])}")
        attributes_data["error"] = state.error[1]
        state_data["state"] = "error"
    else:
        state_data["state"] = "idle"

    #Convert config, state, and attributes payloads to json + publish them
    json_config_data = json.dumps(config_data)
    json_state_data = json.dumps(state_data)
    json_attributes_data = json.dumps(attributes_data)
    log.debug(f"Sending MQTT Config Message: {str(json_config_data)}")
    client.publish(settings['mqtt']['discovery_topic'] + f'/vacuum/neato_serial_{state.serial_number}/config', json_config_data)
    log.debug(f"Sending vacuum state message: {str(json_state_data)}")
    client.publish(settings['mqtt']['state_topic'], json_state_data)
    log.debug(f"Sending vacuum attributes message: {str(json_attributes_data)}")
    client.publish(f'vacuum/neato_serial_{state.serial_number}/attributes', json_attributes_data)
    time.sleep(settings['mqtt']['publish_wait_seconds'])

#Function utilized when manual MQTT configuration is used - uses "legacy" schema in Homeassistant
def legacy_payload():
    legacy_data = {}
    legacy_data["battery_level"] = state.battery_level
    legacy_data["docked"] = state.is_docked
    legacy_data["cleaning"] = state.is_cleaning
    legacy_data["charging"] = state.is_charging
    legacy_data["fan_speed"] = state.fan_speed
    error = ns.getError()
    if error:
        log.debug(f"Error from Neato: {str(error)}")
        legacy_data["error"] = error[1]
    json_legacy_data = json.dumps(legacy_data)
    log.debug(f"Sending vacuum state message: {str(json_legacy_data)}")
    client.publish(settings['mqtt']['state_topic'], json_legacy_data)
    time.sleep(settings['mqtt']['publish_wait_seconds'])

def __publish_status(publishStatus: str):
    """Publishes the json with status on message received"""
    if state is None:
        log.warning(f"While publising status '{publishStatus}', the state was None, so not publishing.")
        return
    
    on_message_data={}
    on_message_data["battery_level"] = state.battery_level
    on_message_data["fan_speed"] = state.fan_speed
    on_message_data["state"] = publishStatus
    json_on_message_data = json.dumps(on_message_data)
    #Use secondary client connection to set state to idle before Pi reboots (Can't publish with primary client whithin callback function)
    cleaning_client.publish(settings['mqtt']['state_topic'], json_on_message_data)

def on_message(client, userdata, msg):
    """Message received."""
    inp = msg.payload.decode('ascii')
    log.info(f"Message received: {inp}")
    if 'discovery_topic' in settings['mqtt']:
        if (inp == "Clean") or (inp == "Clean Spot"):
            __publish_status("cleaning")
            feedback = ns.write(inp)
            log.info(f"Feedback from device: {feedback}")
        elif inp == "Clean Stop":
            __publish_status("idle")
            feedback = ns.write(inp)
            log.info(f"Feedback from device: {feedback}")
        elif inp.lower() == "enable usb":
            ns.enableDisableUsb(True)
            __publish_status("USB Enabled")
        elif inp.lower() == "disable usb":
            ns.enableDisableUsb(False)
            __publish_status("USB Disabled")
        else:
            feedback = ns.write(inp)
            log.info(f"Feedback from device: {feedback}")
    else:
        log.error("Non-discovery topic is obsolete and not supported")

def on_connect(client, userdata, flags, rc):
    """Broker responded to connection request"""
    if rc == 0:
        log.info("Connection to broker successful")
        client.subscribe(settings['mqtt']['command_topic'], qos=1)
    else:
        log.info("Problem connecting to broker")

def on_disconnect(client, userdata, rc):
    """Handle MQTT client disconnect."""
    #Set availability to offline if disconnected from MQTT Broker
    try:
        cleaning_client.publish(f'neato_serial_{state.serial_number}/state', 'offline', qos=0, retain=True)
        
        log.warning(f"Disconnected with code {rc}, attempting to reconnect...")
        
        if rc != 0:
            def reconnect_forever():
                while True:
                    try:
                        client.reconnect()
                        log.info("Reconnected successfully.")
                        return  # Done reconnecting
                    except Exception as e:
                        log.error(f"Reconnect failed: {e}")
                        time.sleep(30)

            # Start the reconnect thread so we don't block the main thread
            threading.Thread(target=reconnect_forever, daemon=True).start()
        else:
            log.info("Disconnected normally. Not trying to reconnect.")
            client.loop_stop(force=False)
    except Exception as outer_exc:
        log.exception(f"Exception on_disconnect: {outer_exc}")

# def on_publish(client, userdata, mid):
#     log.debug("on_publish, mid {}".format(mid))

#logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
if settings['serial']['log_level_warning']:
    log.setLevel(logging.WARN)
else:
    log.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)
log.addHandler(ch)
fh = logging.FileHandler('neatoserial.log')
log = logging.getLogger(__name__)
if settings['serial']['log_level_warning']:
    fh.setLevel(logging.WARN)
else:
    fh.setLevel(logging.DEBUG)
fh.setFormatter(formatter)
log.addHandler(fh)

log.debug("Starting")
#Primary Client
client = mqtt.Client()
#Secondary client that will handle publishing the "cleaning state" when on_message callback is called
cleaning_client = mqtt.Client()
client.on_message = on_message
client.on_disconnect = on_disconnect
client.on_connect = on_connect
#client.on_publish = on_publish
client.username_pw_set(settings['mqtt']['username'],
                       settings['mqtt']['password'])
cleaning_client.username_pw_set(settings['mqtt']['username'],
                       settings['mqtt']['password'])
log.debug("Connecting")
client.connect(settings['mqtt']['host'], settings['mqtt']['port'])
cleaning_client.connect(settings['mqtt']['host'], settings['mqtt']['port'])
log.debug("Ready")
client.loop_start()
cleaning_client.loop_start()
while True:
    # try:
    #if not ns.getIsConnected():
    #    ns.reconnect()
    if ns.isUsbEnabled:
        state = ns.getCombinedState()
        restartMqtt.checkAndRestart()
    #Determine whether end-user is using MQTT Autodiscovery or Manual configuration
    if 'discovery_topic' in settings['mqtt']:
        client.publish(f'neato_serial_{state.serial_number}/state', 'online', qos=0, retain=True)
        discovery_payload()
    else:
        client.publish(f'neato_serial_{state.serial_number}/state', 'online', qos=0, retain=True)
        legacy_payload()
        # except Exception as ex:
        #     log.error("Error getting status: "+str(ex))
    
    # Sleep our loop
    time.sleep(2)