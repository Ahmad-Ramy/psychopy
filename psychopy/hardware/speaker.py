import io
import sys
import contextlib
import psychtoolbox.audio as ptb
from psychopy.preferences import prefs
from psychopy.hardware import BaseDevice
from psychopy import logging


class BaseSpeakerDevice(BaseDevice):
    streams = {}

    def __init__(self, index=None, name=None):
        # try simple integerisation of index
        if isinstance(index, str):
            try:
                index = int(index)
            except ValueError:
                pass
        # if index is default, get default
        if index in (-1, None):
            pref = prefs.hardware['audioDevice']
            if isinstance(pref, (list, tuple)):
                pref = pref[0]
            index = pref
        # store name and index
        self.name = name
        self.index = index
    
    def createStream(self):
        """
        Create the underlying object for playing audio from the sound backend (psychtoolbox, 
        pygame, etc.)

        Attributes
        ----------
        Calling this method will set the following attributes:

        stream : object
            Underlying audio object from the backend. The type of this object will differ between 
            backends.
        profile : object
            The profile from the sound backend. The type of this object will differ between 
            backends.
        index : int
            A numeric index referring to the device. This may differ from the value of `index` this 
            object was initialised with, as this will be the numeric index of the actual physical 
            speaker best matching what was requested.
        name : str
            A string name referring to the device. This may differ from the value of `name` this 
            object was initialised with, as this will be the system-reported name of the actual 
            physical speaker best matching what was requested.
        """
        raise NotImplementedError()

    def open(self):
        """
        Open the audio stream for this speaker so that sound can be played to it.
        """
        raise NotImplementedError()
    
    def close(self):
        """
        Close the audio stream for this speaker.
        """
        raise NotImplementedError()
    
    @property
    def isOpen(self):
        """
        Is this speaker "open", i.e. is it active and ready for a Sound to play tracks on it
        """
        raise NotImplementedError()
    
    def isSameDevice(self, other):
        """
        Determine whether this object represents the same physical speaker as a given other object.

        Parameters
        ----------
        other : SpeakerDevice, dict
            Other SpeakerDevice to compare against, or a dict of params (which must include
            `index` as a key)

        Returns
        -------
        bool
            True if the two objects represent the same physical device
        """
        if isinstance(other, type(self)):
            # if given another object, get index
            index = other.index
        elif isinstance(other, dict) and "index" in other:
            # if given a dict, get index from key
            index = other['index']
        else:
            # if the other object is the wrong type or doesn't have an index, it's not this
            return False

        return index in (self.index, self.name)

    def testDevice(self):
        """
        Play a simple sound to check whether this device is working.
        """
        from psychopy.sound import Sound
        import time
        # create a basic sound
        snd = Sound(
            speaker=self,
            value="A",
            stereo=self.channels > 1,
            sampleRate=self.sampleRateHz
        )
        # play the sound for 1s
        snd.play()
        time.sleep(1)
        snd.stop()

    @staticmethod
    def getAvailableDevices():
        raise NotImplementedError()


class PTBSpeakerDevice(BaseSpeakerDevice):
    # dict of extant streams, by numeric index
    streams = {}

    def createStream(self):
        """
        Create the psychtoolbox audio stream

        Attributes
        ----------
        Calling this method will set the following attributes:

        profile : dict
            The profile from psychtoolbox, a dict with the following keys: Active, State, 
            RequestedStartTime, StartTime, CaptureStartTime, RequestedStopTime, EstimatedStopTime, 
            CurrentStreamTime, ElapsedOutSamples, PositionSecs, RecordedSecs, ReadSecs, 
            SchedulePosition, XRuns, TotalCalls, TimeFailed, BufferSize, CPULoad, PredictedLatency, 
            LatencyBias, SampleRate, OutDeviceIndex, InDeviceIndex
        index : int
            A numeric index referring to the device. This may differ from the value of `index` this 
            object was initialised with, as this will be the numeric index of the actual physical 
            speaker best matching what was requested.
        name : str
            A string name referring to the device. This may differ from the value of `name` this 
            object was initialised with, as this will be the system-reported name of the actual 
            physical speaker best matching what was requested.
        """
        # find ptb profile for this device
        self.profile = None
        for thisProfile in ptb.get_devices(device_type=13):
            # skip input-only devices (microphones)
            if thisProfile['NrOutputChannels'] == 0:
                continue
            # if profile matches device name or index, use it
            if thisProfile['DeviceName'] in (self.name, self.index) or (
                self.index == thisProfile['DeviceIndex'] and self.name is None
            ):
                self.profile = thisProfile
                break
        # raise error if device not found
        if self.profile is None:
            raise ValueError(
                "No speaker device found with index {}".format(self.index)
            )
        # if physical device already has a stream, use it rather than making a new one
        if self.profile['DeviceIndex'] in PTBSpeakerDevice.streams:
            self.stream = PTBSpeakerDevice.streams['DeviceIndex']
        else:
            self.stream = None
        # try to connect using profile at various sample rates
        for sampleRateHz in (
            # start with the rate from profile (this will usually work)
            self.profile['DefaultSampleRate'], 
            # if that fails, try some common sample rates
            48000,
            44100, 
            22050, 
            16000
        ):
            # stop trying new options once we have a stream
            if self.stream is not None:
                continue
            # try this sample rate
            try:
                # redirect stderr to a buffer to avoid ptb error spam
                outBuff = io.StringIO()
                errBuff = io.StringIO()
                with contextlib.redirect_stdout(outBuff):
                    with contextlib.redirect_stderr(errBuff):
                        self.stream = ptb.Stream(
                            mode=1+8,
                            device_id=self.profile['DeviceIndex'],
                            freq=sampleRateHz,
                            channels=self.profile['NrOutputChannels'],
                            latency_class=[1],
                        )
                # if it worked, set own parameters
                self.index = self.profile['DeviceIndex']
                self.name = self.profile['DeviceName']
                self.sampleRateHz = sampleRateHz
                self.channels = self.profile['NrOutputChannels']
                self.latencyClass = 1
                # ...and log/print the stderr from psychtoolbox (only if successful!)
                logs = errBuff.getvalue() + outBuff.getvalue()
                for line in logs.split("\n"):
                    if line.startswith("PTB-INFO: "):
                        logging.info(line[10:])
                    elif line.startswith("PTB-ERROR: "):
                        logging.error(line[11:])
                    elif line.strip():
                        print(line)
            except:
                pass
        # if everything failed, raise an error
        if self.stream is None:
            raise ConnectionError(
                "Failed to setup a PsychToolBox audio stream for device %(DeviceName)s "
                "(%(DeviceIndex)s)." % self.profile
            )
    
    def open(self):
        """
        Open the audio stream for this speaker so that sound can be played to it.
        """
        if not self.isOpen:
            self.stream.start(0, 0, 1)
    
    def close(self):
        """
        Close the audio stream for this speaker.
        """
        if self.isOpen:
            self.stream.close()
    
    @property
    def isOpen(self):
        """
        Is this speaker "open", i.e. is it active and ready for a Sound to play tracks on it
        """
        return bool(self.stream.status['Active'])
    
    @staticmethod
    def getAvailableDevices():
        # only show WASAPI drivers for Windows
        if sys.platform == 'win32':
            deviceType = 13
        else:
            deviceType = None
        
        devices = []
        for profile in ptb.get_devices(device_type=deviceType):
            # skip input-only devices (microphones)
            if profile['NrOutputChannels'] == 0:
                continue
            # construct profile
            device = {
                'deviceName': profile.get('DeviceName', "Unknown Speaker"),
                'index': profile.get('DeviceIndex', None),
                'name': profile.get('DeviceName', None)
            }
            devices.append(device)

        return devices
