# -*- coding: utf-8 -*-
"""
Created on Mon Feb  8 11:44:29 2021

@author: svc_ccg
"""

import time
import h5py
import numpy as np
import scipy.signal
from numba import njit
import fileIO


def loadDatData(filePath):
    totalChannels = 136
    probeChannels = 128      
    rawData = np.memmap(filePath,dtype='int16',mode='r')    
    rawData = np.reshape(rawData,(int(rawData.size/totalChannels),-1)).T
    analogInData = {name: rawData[ch+probeChannels] for ch,name in enumerate(('vsync',
                                                                              'photodiode',
                                                                              'rotaryEncoder',
                                                                              'cam1Exposure',
                                                                              'cam2Exposure',
                                                                              'led1',
                                                                              'led2'))}
    return rawData,analogInData


@njit
def findSignalEdges(signal,edgeType,thresh,refractory):
    """
    signal: typically a large memmap array (loop through values rather than load all into memory)
    edgeType: 'rising' or 'falling'
    thresh: difference between current and previous value
    refractory: samples after detected edge to ignore
    """
    edges = []
    lastVal = signal[0]
    lastEdge = -refractory
    for i in range(1,signal.size):
        val = signal[i]
        if i-lastEdge>refractory and ((edgeType=='rising' and val-lastVal>thresh) or (edgeType=='falling' and val-lastVal<thresh)):
            edges.append(i)
            lastEdge = i
        lastVal = val
    return edges


@njit
def findSpikes(data,negThresh,posThresh):
    spikes = []    
    searchStart = 0
    while searchStart < data.size:
        spikeBegin,spikeEnd = findNextSpike(data[searchStart:],negThresh,posThresh)
        if spikeBegin is None:
            break
        else:
            spikes.append(searchStart+spikeBegin)
            searchStart += spikeEnd
    return spikes

@njit
def findNextSpike(data,negThresh,posThresh):
    for i,v in enumerate(data.flat):
        if v < negThresh:
            for j,vi in enumerate(data[i:].flat):
                if vi > posThresh:
                    return i,i+j
    return None,None


datPath = fileIO.getFile('Select probe dat file',fileType='*.dat')
datData,analogInData = loadDatData(datPath)
sampleRate = 30000
channelMap = np.array([16,112,111,14,110,15,109,12,108,13,107,10,106,11,105,8,104,9,103,6,102,7,101,4,100,5,99,2,98,3,97,96,1,95,62,94,63,93,60,92,61,91,58,90,59,89,56,88,57,87,55,86,54,85,53,84,52,83,51,82,50,81,49,80,48,47,78,46,79,45,76,44,77,43,75,42,74,41,73,40,72,39,71,38,70,37,69,36,68,35,67,34,66,33,65,32,64,31,127,30,126,29,125,28,124,27,123,26,122,25,121,24,120,23,119,22,118,21,117,20,116,19,115,18,114,17,113])-1
frameSamples = np.array(findSignalEdges(analogInData['vsync'],edgeType='falling',thresh=-5000,refractory=2))


pklPath = fileIO.getFile('Select rf mapping pkl file',fileType='*.hdf5')
pklData = h5py.File(pklPath,'r')
frameIntervals = pklData['frameIntervals'][:]
if 'stimStartFrame' in pklData:
    stimStart = pklData['stimStartFrame'][:]
else:
    trialStartFrame = np.concatenate(([0],np.cumsum(pklData['preFrames'] + pklData['trialStimFrames'][:-1] + pklData['postFrames'])))
    stimStart = trialStartFrame + pklData['preFrames']
stimStart += frameSamples.size-(frameIntervals.size+1)
stimPos = pklData['trialGratingCenter'][:]


print(str(frameIntervals.size+1)+' frames')
print(str(frameSamples.size)+' frame samples')    


channelRange = [9,10]
negThresh = -500
posThresh = 100
chunkSamples = int(15*sampleRate)

Wn = 300/(sampleRate/2)
b,a = scipy.signal.butter(2,Wn,btype='highpass')

t = time.perf_counter()

spikes = []
for ch in range(channelRange[0],channelRange[1]):
    offset = 0
    while offset < datData.shape[1]:
        if offset > 0 and len(spikes) < 1:
            break
        d = scipy.signal.filtfilt(b,a,datData[ch,offset:offset+chunkSamples])
        s = np.array(findSpikes(d,negThresh,posThresh)) + offset
        spikes.extend(s)
        offset += chunkSamples

print(time.perf_counter()-t)      

                        
    



































