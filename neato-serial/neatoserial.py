"""Serial interface for Neato."""
from config import settings
import serial
import os
import time
import RPi.GPIO as GPIO
import logging
import sys

class PrintAndLogLogger(logging.Logger):    
    def __init__(self, name, level=logging.NOTSET):
        super(PrintAndLogLogger, self).__init__(name, level)

        # Create a handler for console output
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.getLogLevel())  # Set the desired level for console output

        # Create a formatter and add it to the handler
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)

        # Add the console handler to the logger
        self.addHandler(console_handler)

        # Add file handler
        file_handler = logging.FileHandler("neato-debug.log")
        file_handler.setLevel(self.getLogLevel())
        file_handler.setFormatter(formatter)
        self.addHandler(file_handler)

    def getLogLevel(self):
        if 'log_level_warning' in settings['serial'] and settings['serial']['log_level_warning']:
            return logging.WARN
        return logging.DEBUG

class NeatoSerial:
    """Serial interface to Neato."""
    
    def __init__(self):
        """Initialize serial connection to Neato."""
        self.isUsbEnabled = True
        self.log = PrintAndLogLogger(__name__)

        if settings['serial']['usb_switch_mode'] == 'relay':
            # use relay to temporarily disconnect neato to trigger clean
            self.pin = int(settings['serial']['relay_gpio'])
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self.pin, GPIO.OUT)
            GPIO.output(self.pin, GPIO.HIGH)
        self.isConnected = self.connect()

    def connect(self):
        """Connect to serial port."""
        devices = settings['serial']['serial_device'].split(',')
        for dev in devices:
            if not self.isUsbEnabled:
                self.log.debug("Usb is manually disabled, stop trying to connect.")
                return False
            
            try:
                self.ser = serial.Serial(dev, 115200,
                                         serial.EIGHTBITS, serial.PARITY_NONE,
                                         serial.STOPBITS_ONE,
                                         settings['serial']['timeout_seconds'])
                self.open()
                self.log.info("Connected to Neato at "+dev)
                return True
            except:
                self.log.error("Could not connect to device "+dev+". "
                               + "Trying next device.")
        return False

    def getIsConnected(self):
        """Return if connected."""
        return self.isConnected

    def open(self):
        """Open serial port and flush the input."""
        self.log.info("Entering OPEN()")
        if self.ser is None:
            return
        else:
            self.ser.isOpen()
            self.ser.flushInput()
        self.log.info("Leaving OPEN()")

    def close(self):
        """Close serial port."""
        self.log.info("Entering CLOSE()")
        self.ser.close()
        self.isConnected = False
        self.log.info("Leaving CLOSE, isConnected= "+str(self.isConnected))

    def read_all(self, port, chunk_size=200):
        """Read all characters on the serial port and return them."""
        if not port.timeout:
            raise TypeError('Port needs to have a timeout set!')
        read_buffer = b''
        while True:
            # Read in chunks. Each chunk will wait as long as specified by
            # timeout. Increase chunk_size to fail quicker
            byte_chunk = port.read(size=chunk_size)
            read_buffer += byte_chunk
            if not len(byte_chunk) == chunk_size:
                break
        return read_buffer

    def enableDisableUsb(self, isEnabled):
        """Enables or disables usb"""
        if isEnabled:
            self.log.info("Enabling USB.")
            self.isUsbEnabled = True
            GPIO.output(self.pin, GPIO.HIGH)
        else:
            self.log.info("Disabling USB.")
            self.isUsbEnabled = False
            GPIO.output(self.pin, GPIO.LOW)

    def toggleusb(self):
        """Toggle USB connection to Neato."""
        self.log.info("Entering TOGGLEUSB()")
        if settings['serial']['usb_switch_mode'] == 'direct':
            self.log.info("Direct connection specified.")
            # disable and re-enable usb ports to trigger clean
            os.system('sudo ./hub-ctrl -h 0 -P 2 -p 0 ; sleep 1; '
                      + 'sudo ./hub-ctrl -h 0 -P 2 -p 1 ')
        elif settings['serial']['usb_switch_mode'] == 'relay':
            self.log.debug("Relay connection specified")
            # use relay to temporarily disconnect neato to trigger clean
            GPIO.output(self.pin, GPIO.LOW)
            time.sleep(1)
            GPIO.output(self.pin, GPIO.HIGH)
            self.log.info("Relay toggled.")
        if settings['serial']['reboot_after_usb_switch']:
            os.system('sudo reboot')
        self.log.info("Leaving TOGGLEUSB()")

    def reconnect(self):
        """Close and reconnect connection to Neato."""
        self.log.info("Entering RECONNECT()")
        self.log.debug("Reconnecting to Neato")
        self.isConnected = False
        time.sleep(5)
        self.close()
        self.isConnected = self.connect()
        self.open()
        self.log.info("Leaving RECONNECT(),  isConnected = "+str(self.isConnected))

    def handleCleanMessage(self, msg):
        """Handle sending and extra activities for Clean messages."""
        self.log.info("Entering HANDLECLEANMESSAGE(), msg = "+str(msg))
        out = self.cleanWithUsbToggle(msg)
        self.log.info("Leaving HANDLECLEANMESSAGE(), out="+str(out)[:10])
        return out

    def raw_write(self,msg):
        """Write message to serial and return output."""
        self.log.info("Entering RAW_WRITE(), msg = "+str(msg))
        out = ''
        if self.isConnected:
            inp = msg+"\n"
            self.ser.write(inp.encode('utf-8'))
            time.sleep(1)
            while self.ser.inWaiting() > 0:
                out += self.read_all(self.ser).decode('utf-8')
        self.log.info("Leaving RAW_WRITE()")
        return out

    def write(self, msg):
        """Write message to serial and return output. Handles Clean message."""
        self.log.info("Entering WRITE, msg = "+msg)
        if self.isConnected:
            # wake up neato by sending something random
            try:
                self.log.info("Sending Wake-up msg.")
                out = self.raw_write("wake-up")
                # now send the real message
                if msg.lower() == "clean" or msg.lower() == "clean spot":
                    out = self.handleCleanMessage(msg)
                else:
                    out = self.raw_write(msg)
                if out != '':
                    self.log.info("Leaving WRITE(), out = "+str(out)[:10])
                    return out
            except OSError as ex:
                self.log.error("Exception in 'write' method: "+str(ex))
                if not self.isUsbEnabled:
                    self.log.warn("Planned disconnection of USB → UART occurred, no need to reconnect")
                    self.close()
                else:
                    self.log.info("Calling RECONNECT()")
                    self.reconnect()
        else:
            if self.isUsbEnabled:
                self.log.info("Not connected in WRITE() - calling CONNECT()")
                self.isConnected = self.connect()
            else:
                self.log.info("Usb is manually disabled, can't communicate yet.");
    
    def cleanWithUsbToggle(self, msg = None):
        """Stopping, Clearing Error, in case someone paused it and wants to start again"""
        self.raw_write("Clean Stop")
        self.raw_write("GetErr Clear")
        if msg == None:
            msg = "Clean"
        out = self.raw_write(msg)
        self.log.info("Toggling USB")
        self.toggleusb()
        self.log.info("Reconnecting")
        self.reconnect()
        return out

    def getError(self):
        """Return error message if available."""
        self.log.info("Entering GETERROR()")
        output = self.write("GetErr")
        if output is not None:
            outputsplit = output.split('\r\n')
            if len(outputsplit) == 3:
                err = outputsplit[1]
                if ' - ' in err:
                    errsplit = err.split(' - ')
                    if int(errsplit[0]) == 220:
                        # if err is 220 (unplug usb before cleaning) handle it
                        self.log.info("Errorcode is 220. Let's stop clean and start it fresh")
                        self.cleanWithUsbToggle()
                    self.log.info("Leaving GETERROR(), errsplit = "+str(errsplit))
                    return errsplit[0], errsplit[1]
            else:
                self.log.info("Leaving GETERROR(), return None since no output split.")
                return None
        else:
            self.log.info("Leaving GETERROR(), return None since Output is None.")
            return None

    def getBatteryLevel(self, getChargerResult = None):
        """Return battery level."""
        if getChargerResult == None:
            getChargerResult = self.getCharger()
        if getChargerResult:
            return int(getChargerResult.get("FuelPercent", 0))
        else:
            return 0

    def getChargingActive(self, getChargerResult = None):
        """Return true if device is currently charging."""
        if getChargerResult == None:
            getChargerResult = self.getCharger()
        if getChargerResult:
            return bool(int(getChargerResult.get("ChargingActive", False)))
        else:
            return False

    def getExtPwrPresent(self, getChargerResult=None):
        """Return true if device is currently docked."""
        if getChargerResult == None:
            getChargerResult = self.getCharger()
        if getChargerResult:
            return bool(int(getChargerResult.get("ExtPwrPresent", False)))
        else:
            return False

    def getAccel(self):
        """Get accelerometer info."""
        return self.parseOutput(self.write("GetAccel"))

    def getAnalogSensors(self):
        """Get analog sensor info."""
        return self.parseOutput(self.write("GetAnalogSensors"))

    def getButtons(self):
        """Get button info."""
        return self.parseOutput(self.write("GetButtons"))

    def getCalInfo(self):
        """Get calibration info."""
        return self.parseOutput(self.write("GetCalInfo"))

    def getCharger(self):
        """Get charger info."""
        return self.parseOutput(self.write("GetCharger"))

    def getDigitalSensors(self):
        """Get digital sensor info."""
        return self.parseOutput(self.write("GetDigitalSensors"))

    def getLDSScan(self):
        """Get lidar scan."""
        return self.parseOutput(self.write("GetLDSScan"))

    def getMotors(self):
        """Get motor info."""
        return self.parseOutput(self.write("GetMotors"))

    def getSerialNumber(self, getVersionResult=None):
        if getVersionResult == None:
            getVersionResult = self.getVersion()
        if getVersionResult:
            return getVersionResult.get("Serial Number", "1234")
        else:
            return str(1234)

    def getSoftwareVersion(self, getVersionResult=None):
        if getVersionResult == None:
            getVersionResult = self.getVersion()
        if getVersionResult:
            return getVersionResult.get("MainBoard Software", "1234")
        else:
            return str(1234)

    def getVersion(self):
        """Get version info."""
        return self.parseOutput(self.write("GetVersion"))

    def getVacuumRPM(self, getMotorsResult = None):
        """Get vacuum RPM."""
        if getMotorsResult == None:
            getMotorsResult = self.getMotors()
        if getMotorsResult:
            return int(getMotorsResult.get("Vacuum_RPM", 0))
        else:
            return 0

    def getCleaning(self, getMotorsResult = None):
        """Return true is device is currently cleaning."""
        return self.getVacuumRPM(getMotorsResult) > 0

    def parseOutput(self, output):
        """Parse the raw output of the serial port into a dictionary."""
        if output is None:
            return None
        else:
            lines = output.splitlines()
            dict = {}
            for l in lines:
                lsplit = l.split(',')
                if len(lsplit) > 1:
                    dict[lsplit[0]] = lsplit[1]
            return dict
        
    def getCombinedState(self):
        """Gets combined info by calling methods as few times as possible"""

        getVersionResult = self.getVersion()
        getChargerResult = self.getCharger()
        getMotorsResult = self.getMotors()

        combinedState = CombinedState()
        combinedState.serial_number = self.getSerialNumber(getVersionResult)
        combinedState.software_version = self.getSoftwareVersion(getVersionResult)
        combinedState.is_docked = self.getExtPwrPresent(getChargerResult)
        combinedState.is_cleaning = self.getCleaning(getMotorsResult)
        combinedState.is_charging = self.getChargingActive(getChargerResult)
        combinedState.fan_speed = self.getVacuumRPM(getMotorsResult)
        combinedState.battery_level = self.getBatteryLevel(getChargerResult)
        combinedState.error = self.getError()

        return combinedState

class CombinedState:
    def __init__(self):
        self.serial_number = None 
        self.software_version: str = None
        self.is_docked = False
        self.is_cleaning = False
        self.is_charging = False
        self.fan_speed = 0
        self.battery_level = 0
        self.error: tuple[str, str] = None

if __name__ == '__main__':
    ns = NeatoSerial()
    ns.log.info("Enter commands. Enter 'exit' to quit")
    while 1:
        inp = input("? ")
        if inp == 'exit':
            ns.close()
            exit()
        else:
            try:
                ns.log.info(">> "+ns.write(inp))
            except:
                ns.log.info("No result returned.")