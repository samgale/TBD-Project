# -*- coding: utf-8 -*-
"""
Superclass for behavioral task control

"""

from __future__ import division
import math, os, random, time
import h5py
import numpy as np
from psychopy import monitors, visual
import ProjectorWindow
import nidaq
from threading import Timer


class TaskControl():
    
    def __init__(self):
        self.rig = 'pilot' # 'pilot' or 'np3'
        self.subjectName = None
        self.saveParams = True # if True, saves all attributes not starting with underscore
        self.saveFrameIntervals = True
        self.saveMovie = False
        self.screen = 1 # monitor to present stimuli on
        self.drawDiodeBox = True
        self.nidaqDevice = 'USB-6009'
        self.wheelRotDir = 1 # 1 or -1
        self.wheelSpeedGain = 50 # arbitrary scale factor
        self.rewardDur = 0.1 # duration in seconds of analog output pulse controlling reward size
        if self.rig=='pilot':
            self.saveDir = 'C:\Users\SVC_CCG\Desktop\Data' # path where parameters and data saved
            self.monWidth = 47.0 # cm
            self.monDistance = 61.09 # cm
            self.monGamma = None # float or None
            self.monSizePix = (1680,1050)
            self.flipScreenHorz = False
            self.warp = 'Disabled' # one of ('Disabled','Spherical','Cylindrical','Curvilinear','Warpfile')
            self.warpFile = None
            self.diodeBoxSize = 50
            self.diodeBoxPosition = (815,-500)
        elif self.rig=='np3':
            pass
        self.pixelsPerDeg = self.monSizePix[0]/(2*math.tan(self.monWidth/2/self.monDistance)*180/math.pi)
            
    def visStimFlip(self):
        if self.drawDiodeBox:
            self._diodeBox.fillColor = -self._diodeBox.fillColor
            self._diodeBox.draw()
        self.setFrameSignal(1)
        self._win.flip()
        if self.saveMovie:
            self._win.getMovieFrame()
        self.setFrameSignal(0)
        
    def prepareRun(self):
        self.startTime = time.strftime('%Y%m%d_%H%M%S')
        
        self.prepareWindow()

        self._diodeBox = visual.Rect(self._win,
                                    units='pix',
                                    width=self.diodeBoxSize,
                                    height=self.diodeBoxSize,
                                    lineColor=0,
                                    fillColor=1, 
                                    pos=self.diodeBoxPosition)
        
        self.numpyRandomSeed = random.randint(0,2**32)
        self._numpyRandom = np.random.RandomState(self.numpyRandomSeed)
        
        self.startNidaqDevice()
        self.rotaryEncoderRadians = []
        self.lickInput = []
        self.cam1Saving = []
        self.cam2Saving = []
        self.cam1Exposure = []
        self.cam2Exposure = []
        
    def prepareWindow(self):
        self._mon = monitors.Monitor('monitor1',
                                     width=self.monWidth,
                                     distance=self.monDistance,
                                     gamma=self.monGamma)
        self._mon.setSizePix(self.monSizePix)
        self._mon.saveMon()
        self._win =  ProjectorWindow.ProjectorWindow(monitor=self._mon,
                                                     screen=self.screen,
                                                     fullscr=True,
                                                     flipHorizontal=self.flipScreenHorz,
                                                     warp=getattr(ProjectorWindow.Warp,self.warp),
                                                     warpfile=self.warpFile,
                                                     units='pix')
        self.frameRate = self._win.getActualFrameRate() # do this before recording frame intervals
        self._win.setRecordFrameIntervals(self.saveFrameIntervals)
                                               
    def completeRun(self):
        subjName = '' if self.subjectName is None else self.subjectName
        fileBaseName = os.path.join(self.saveDir,self.__class__.__name__+'_'+subjName+'_'+self.startTime)
        if self.saveMovie:
            self._win.saveMovieFrames(os.path.join(fileBaseName+'.mp4'))
        self._win.close()
        self.stopNidaqDevice()
        if self.saveParams:
            fileOut = h5py.File(fileBaseName+'.hdf5','w')
            saveParameters(fileOut,self.__dict__)
            if self.saveFrameIntervals:
                fileOut.create_dataset('frameIntervals',data=self._win.frameIntervals)
            fileOut.close()
        
    def startNidaqDevice(self):
        # rotary encoder: AI0
        sampRate = 1000.0
        bufferSize = int((1 / self.frameRate * sampRate))
        self._rotEncoderInput = nidaq.AnalogInput(device='Dev1',channel=0,voltageRange=(0,5),
                                                  sampRate=sampRate,bufferSize=bufferSize)
        self._rotEncoderInput.StartTask()
        
        # digital inputs (port 0)
        # line 0.0: lick detector
        # line 0.1: cam1 saving
        # line 0.2: cam2 saving
        # line 0.3: cam1 exposure
        # line 0.4: cam2 exposure
        self._digInputs = nidaq.DigitalInputs(device='Dev1',port=0)
        self._digInputs.StartTask()
        
        # digital outputs (port 1)
        # line 0: frame signal
        # line 1: reward solenoid
        # line 2: sound trigger
        self._digOutputs = nidaq.DigitalOutputs(device='Dev1',port=1,initialState='low')
        self._digOutputs.StartTask()
        self._digOutputs.Write(self._digOutputs.lastOut)
    
    def stopNidaqDevice(self):
        for task in (self._rotEncoderInput,self._digInputs,self._digOutputs):
            task.StopTask()
            task.ClearTask()
            
    def getNidaqData(self):
        # analog
        encoderAngle = self._rotEncoderInput.data[:] * 2 * math.pi / 5
        self.rotaryEncoderRadians.append(np.arctan2(np.mean(np.sin(encoderAngle)),np.mean(np.cos(encoderAngle))))
        
        # digital
        di = self._digInputs.Read()
        self.lickInput.append(di[0])
        self.cam1Saving.append(di[1])
        self.cam2Saving.append(di[2])
        self.cam1Exposure.append(di[3])
        self.cam2Exposure.append(di[4])        
        
    def translateEndoderChange(self):
        # translate encoder angle change to number of pixels to move visual stimulus
        if len(self.rotaryEncoderRadians) < 2:
            pixelsToMove = 0
        else:
            angleChange = self.rotaryEncoderRadians[-1] - self.rotaryEncoderRadians[-2]
            if angleChange < -math.pi:
                angleChange += 2 * math.pi
            elif angleChange > math.pi:
                angleChange -= 2 * math.pi
            pixelsToMove = angleChange * self.wheelRotDir * self.wheelSpeedGain
        return pixelsToMove
        
    def setFrameSignal(self,level):
        self._digOutputs.WriteBit(0,level)

    def deliverReward(self):
        self.digitalTrigger(1,self.rewardDur)
        
    def triggerSound(self):
        self.digitalTrigger(2,self.rewardDur)
    
    def digitalTrigger(self,ch,dur):
        self._digOutputs.WriteBit(ch,1)
        t = Timer(dur,self.digitalTriggerOff,args=[ch])
        t.start()

    def digitalTriggerOff(self,ch):
        self._digOutputs.WriteBit(ch,0)
        

def saveParameters(fileOut,paramDict,dictName=None):
    for key,val in paramDict.items():
        if key[0] != '_':
            if dictName is None:
                paramName = key
            else:
                paramName = dictName+'_'+key
            if isinstance(val,dict):
                saveParameters(fileOut,val,paramName)
            else:
                try:
                    if val is None:
                        val = np.nan
                    fileOut.create_dataset(paramName,data=val)
                except:
                    print 'could not save ' + key
                    

if __name__ == "__main__":
    pass