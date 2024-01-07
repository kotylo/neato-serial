from config import settings
import requests
import json
import logging
import os

class RestartMqtt:
    """Class to fetch state from Home Assistant and restart MQTT service automatically """
    def __init__(self):
        self.log = logging.getLogger(__name__)

        baseUrl = settings["mqtt"]["home_assistant"]["base_url"]
        self.url = f"{baseUrl}/api/states/binary_sensor.is_neato_mqtt_connected"
        token = settings["mqtt"]["home_assistant"]["token"]
        self.headers = {
            "Authorization": f"Bearer {token}",
            "content-type": "application/json",
        }

    def checkAndRestart(self):
        response = requests.get(self.url, headers=self.headers)

        self.log.debug(response.text)
        print(response.text)

        jContent = json.loads(response.text)
        isOff = jContent["state"] == "off"
        if isOff:
            print("Restarting the mqtt service")
            os.popen("sudo systemctl restart neatoserialmqtt")
        else:
            print("All good, service lives")

if __name__ == '__main__':
    app = RestartMqtt()
    app.checkAndRestart()