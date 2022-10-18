# -*- coding: utf-8 -*-
"""
Created on Wed Feb  3 16:32:27 2021

@author: svc_ccg
"""

import copy
import pickle
import random
import numpy as np
import scipy.optimize
import scipy.signal
import scipy.stats
import matplotlib
matplotlib.rcParams['pdf.fonttype']=42
import matplotlib.pyplot as plt
from numba import njit
import fileIO



def fitModel(fitParamRanges,fixedParams,finish=False):
    fit = scipy.optimize.brute(calcModelError,fitParamRanges,args=fixedParams,full_output=False,finish=None,workers=1)
    if finish:
        finishRanges = []
        for rng,val in zip(fitParamRanges,fit):
            if val in (rng.start,rng.stop):
                finishRanges.append(slice(val,val+1,1))
            else:
                oldStep = rng.step
                newStep = oldStep/4
                finishRanges.append(slice(val-oldStep+newStep,val+oldStep,newStep))
        fit = scipy.optimize.brute(calcModelError,finishRanges,args=fixedParams,full_output=False,finish=None,workers=1)
    return fit


def calcModelError(paramsToFit,*fixedParams):
    tauI,alpha,eta,sigma,tauA,decay,inhib,threshold,trialEnd,postDecision = paramsToFit
    signals,targetSide,maskOnset,optoOnset,optoSide,trialsPerCondition,responseRate,fractionCorrect,reactionTime = fixedParams
    sessionData = runSession(signals,targetSide,maskOnset,optoOnset,optoSide,tauI,alpha,eta,sigma,tauA,decay,inhib,threshold,trialEnd,postDecision,trialsPerCondition)
    if sessionData is None:
        return 1e6
    else:
        trialTargetSide,trialMaskOnset,trialOptoOnset,trialOptoSide,response,responseTime,Lrecord,Rrecord = sessionData
        result = analyzeSession(targetSide,maskOnset,optoOnset,optoSide,trialTargetSide,trialMaskOnset,trialOptoOnset,trialOptoSide,response,responseTime)
        respRateError = np.nansum(((responseRate-result['responseRate'])/np.nanstd(responseRate))**2)
        fracCorrError = np.nansum(((fractionCorrect-result['fractionCorrect'])/np.nanstd(fractionCorrect))**2)
        if postDecision > 0:
            respTimeError = np.nansum(((reactionTime-(result['responseTimeMedian']+postDecision))/np.nanstd(reactionTime))**2)
        else:
            respTimeError = 0
        return respRateError + fracCorrError + respTimeError


def analyzeSession(targetSide,maskOnset,optoOnset,optoSide,trialTargetSide,trialMaskOnset,trialOptoOnset,trialOptoSide,response,responseTime,Lrecord=None,Rrecord=None):
    result = {}
    responseRate = []
    fractionCorrect = []
    responseTimeMedian = []
    if Lrecord is not None:
        evidenceLeft,evidenceRight = [np.array([ev[rt] for ev,rt in zip(rec,responseTime)]) for rec in (Lrecord,Rrecord)]
    for side in targetSide:
        result[side] = {}
        sideTrials = trialTargetSide==side
        mo = [np.nan] if side==0 else maskOnset
        for maskOn in mo:
            result[side][maskOn] = {}
            maskTrials = np.isnan(trialMaskOnset) if np.isnan(maskOn) else trialMaskOnset==maskOn
            for optoOn in optoOnset:
                result[side][maskOn][optoOn] = {}
                for opSide in optoSide:
                    optoTrials = np.isnan(trialOptoOnset) if np.isnan(optoOn) else (trialOptoOnset==optoOn) & (trialOptoSide==opSide)
                    trials = sideTrials & maskTrials & optoTrials
                    responded = response[trials]!=0
                    responseRate.append(np.sum(responded)/np.sum(trials))
                    responseTimeMedian.append(np.median(responseTime[trials][responded]))
                    result[side][maskOn][optoOn][opSide] = {}
                    result[side][maskOn][optoOn][opSide]['responseRate'] = responseRate[-1]
                    result[side][maskOn][optoOn][opSide]['responseTime'] = responseTime[trials][responded]
                    if Lrecord is not None:
                        result[side][maskOn][optoOn][opSide]['evidenceLeft'] = evidenceLeft[trials][responded]
                        result[side][maskOn][optoOn][opSide]['evidenceLeft'] = evidenceRight[trials][responded]
                    if side!=0 and maskOn!=0:
                        correct = response[trials]==side
                        fractionCorrect.append(np.sum(correct[responded])/np.sum(responded))
                        result[side][maskOn][optoOn][opSide]['fractionCorrect'] = fractionCorrect[-1]
                        result[side][maskOn][optoOn][opSide]['responseTimeCorrect'] = responseTime[trials][responded & correct]
                        result[side][maskOn][optoOn][opSide]['responseTimeIncorrect'] = responseTime[trials][responded & (~correct)]
                        if Lrecord is not None:
                            result[side][maskOn][optoOn][opSide]['evidenceLeftCorrect'] = evidenceLeft[trials][responded & correct]
                            result[side][maskOn][optoOn][opSide]['evidenceRightCorrect'] = evidenceRight[trials][responded & correct]
                            result[side][maskOn][optoOn][opSide]['evidenceLeftIncorrect'] = evidenceLeft[trials][responded & ~correct]
                            result[side][maskOn][optoOn][opSide]['evidenceRightIncorrect'] = evidenceRight[trials][responded & ~correct]
                    else:
                        fractionCorrect.append(np.nan)
    result['responseRate'] = np.array(responseRate)
    result['fractionCorrect'] = np.array(fractionCorrect)
    result['responseTimeMedian'] = np.array(responseTimeMedian)
    return result


def runSession(signals,targetSide,maskOnset,optoOnset,optoSide,tauI,alpha,eta,sigma,tauA,decay,inhib,threshold,trialEnd,postDecision,trialsPerCondition,optoLatency=0,record=False):
    trialTargetSide = []
    trialMaskOnset = []
    trialOptoOnset = []
    trialOptoSide = []
    response = []
    responseTime = []
    if record:
        Lrecord = []
        Rrecord = []
    else:
        Lrecord = Rrecord = None
    for side in targetSide:
        mo = [np.nan] if side==0 else maskOnset
        for maskOn in mo:
            if np.isnan(maskOn):
                sig = 'targetOnly'
                maskOn = np.nan
            elif maskOn==0:
                sig = 'maskOnly'
            else:
                sig = 'mask'
            for optoOn in optoOnset:
                for opSide in optoSide:
                    if side==0:
                        Lsignal = np.zeros(signals[sig]['ipsi'][maskOn].size)
                        Rsignal = Lsignal.copy()
                    elif side<0:
                        Lsignal = signals[sig]['contra'][maskOn].copy()
                        Rsignal = signals[sig]['ipsi'][maskOn].copy()
                    else:
                        Lsignal = signals[sig]['ipsi'][maskOn].copy()
                        Rsignal = signals[sig]['contra'][maskOn].copy()
                    if not np.isnan(optoOn):
                        i = int(optoOn+optoLatency)
                        if opSide <= 0:
                            Lsignal[i:] = 0
                        if opSide >= 0:
                            Rsignal[i:] = 0
                    if tauI==0 and alpha > 0:
                        for s in (Lsignal,Rsignal):
                            i = s > 0
                            s[i] = s[i]**eta / (alpha**eta + s[i]**eta)
                            s *= alpha**eta + 1
                    for n in range(trialsPerCondition):
                        trialTargetSide.append(side)
                        trialMaskOnset.append(maskOn)
                        trialOptoOnset.append(optoOn)
                        trialOptoSide.append(opSide)
                        result = runTrial(tauI,alpha,eta,sigma,tauA,decay,inhib,threshold,trialEnd,postDecision,Lsignal,Rsignal,record)
                        response.append(result[0])
                        responseTime.append(result[1])
                        if record:
                            Lrecord.append(result[2])
                            Rrecord.append(result[3])
                        if n > 0.1 * trialsPerCondition and not any(response):
                            return
    return np.array(trialTargetSide),np.array(trialMaskOnset),np.array(trialOptoOnset),np.array(trialOptoSide),np.array(response),np.array(responseTime),Lrecord,Rrecord


@njit
def runTrial(tauI,alpha,eta,sigma,tauA,decay,inhib,threshold,trialEnd,postDecision,Lsignal,Rsignal,record=False):
    if record:
        Lrecord = np.full(int(trialEnd),np.nan)
        Rrecord = Lrecord.copy()
    else:
        Lrecord = Rrecord = None
    L = R = 0
    iL = iR = 0
    t = 0
    response = 0
    while t < trialEnd - postDecision and response == 0:
        if record:
            Lrecord[t] = L
            Rrecord[t] = R
        if L > threshold and R > threshold:
            response = -1 if L > R else 1
        elif L > threshold:
            response = -1
        elif R > threshold:
            response = 1
        if t >= Lsignal.size:
            Lsig = Rsig = 0
        elif alpha > 0:
            Lsig = (Lsignal[t]**eta) / (alpha**eta + iL**eta) if Lsignal[t]>0 and iL>=0 else Lsignal[t]
            Rsig = (Rsignal[t]**eta) / (alpha**eta + iR**eta) if Rsignal[t]>0 and iR>=0 else Rsignal[t]
        else:
            Lsig = Lsignal[t]
            Rsig = Rsignal[t]
        Lnow = L
        L += (random.gauss(0,sigma) + Lsig - decay*L - inhib*R) / tauA
        R += (random.gauss(0,sigma) + Rsig - decay*R - inhib*Lnow) / tauA
        if tauI > 0:
            if t >= Lsignal.size:
                iL -= iL / tauI
                iR -= iR / tauI
            else:
                iL += (Lsignal[t] - iL) / tauI
                iR += (Rsignal[t] - iR) / tauI
        t += 1
    responseTime = t-1
    return response,responseTime,Lrecord,Rrecord



# create model input signals using population ephys responses
psthFilePath = fileIO.getFile('Load popPsth',fileType='*.pkl')
popPsth = pickle.load(open(psthFilePath,'rb'))

signalNames = ('targetOnly','maskOnly','mask')
dt = 1/120*1000
trialEndTimeMax = 2500
trialEndMax = int(round(trialEndTimeMax/dt))
t = np.arange(0,trialEndMax*dt+dt,dt)

popPsthIntp = {}
for sig in signalNames:
    popPsthIntp[sig] = {}
    for hemi in ('ipsi','contra'):
        popPsthIntp[sig][hemi] = {}
        for mo in popPsth[sig][hemi]:
            p = popPsth[sig][hemi][mo].copy()
            p -= p[:,popPsth['t']<0].mean(axis=1)[:,None]
            p = np.nanmean(p,axis=0)
            p = np.interp(t,popPsth['t']*1000,p)
            p -= p[t<30].mean()
            p[0] = 0
            maskOn = np.nan if sig=='targetOnly' else mo
            popPsthIntp[sig][hemi][maskOn] = p
                                   
signals = copy.deepcopy(popPsthIntp)

smax = max([signals[sig][hemi][mo].max() for sig in signals.keys() for hemi in ('ipsi','contra') for mo in signals[sig][hemi]])
for sig in signals.keys():
    for hemi in ('ipsi','contra'):
        for mo in signals[sig][hemi]:
            s = signals[sig][hemi][mo]
            s /= smax

# or create synthetic signals
signalNames = ('targetOnly','maskOnly','mask')
dt = 1/120*1000
trialEndTimeMax = 2500
trialEndMax = int(round(trialEndTimeMax/dt))
t = np.arange(0,trialEndMax*dt+dt,dt)

latency = 4
targetDur = 6
maskDur = 6

signals = {}
maskOnset = [0,2,4,6,8,10,12,np.nan]
for sig in signalNames:
    signals[sig] = {}
    for hemi in ('ipsi','contra'):
        signals[sig][hemi] = {}
        for mo in maskOnset:
            if (sig=='targetOnly' and not np.isnan(mo)) or (sig=='maskOnly' and mo!=0) or (sig=='mask' and not mo>0):
                continue
            s = np.zeros(t.size)
            if sig in ('targetOnly','mask') and hemi=='contra':
                s[latency:latency+targetDur] = 1
            if 'mask' in sig:
                s[latency+mo:latency+mo+maskDur] = 1
            signals[sig][hemi][mo] = s

# display signals
fig = plt.figure(figsize=(4,9))
n = 2+len(signals['mask']['contra'].keys())
axs = []
ymin = 0
ymax = 0
i = 0
for sig in signals:
    for mo in signals[sig]['contra']:
        ax = fig.add_subplot(n,1,i+1)
        for hemi,clr in zip(('ipsi','contra'),'br'):
            p = signals[sig][hemi][mo]
            lbl = hemi if i==0 else None
            ax.plot(t,p,clr,alpha=0.5,label=lbl)
            ymin = min(ymin,p.min())
            ymax = max(ymax,p.max())
        if i==n-1:
            ax.set_xlabel('Time (ms)')
        else:
            ax.set_xticklabels([])
        ax.set_ylabel('Spikes/s')
        title = sig
        if sig=='mask':
            title += ', SOA '+str(round(mo/120*1000,1))+' ms'
        ax.set_title(title)
        if i==0:
            ax.legend()
        axs.append(ax)
        i += 1
for ax in axs:
    for side in ('right','top'):
        ax.spines[side].set_visible(False)
    ax.tick_params(direction='out',top=False,right=False)
    ax.set_xlim([0,2500])
    ax.set_ylim([1.05*ymin,1.05*ymax])
plt.tight_layout()


## fit model parameters
respRateFilePath = fileIO.getFile('Load respRate',fileType='*.npz')
respRateData = np.load(respRateFilePath)
respRateMean = respRateData['mean']
respRateSem = respRateData['sem']

fracCorrFilePath = fileIO.getFile('Load fracCorr',fileType='*.npz')
fracCorrData = np.load(fracCorrFilePath)
fracCorrMean = fracCorrData['mean']
fracCorrSem = fracCorrData['sem']

reacTimeFilePath = fileIO.getFile('Load reacTime',fileType='*.npz')
reacTimeData = np.load(reacTimeFilePath)
reacTimeMean = reacTimeData['mean'] / dt
reacTimeSem = reacTimeData['sem'] / dt

trialsPerCondition = 500
targetSide = (1,) # (1,0) (-1,1,0)
optoOnset = [np.nan]
optoSide = [0]

# mice
maskOnset = [0,2,3,4,6,np.nan]
respRateMean = respRateMean[:-1]
respRateSem = respRateSem[:-1]
fracCorrMean = fracCorrMean[:-1]
fracCorrSem = fracCorrSem[:-1]
reacTimeMean = reacTimeMean[:-1]
reacTimeSem = reacTimeSem[:-1]

# humans
maskOnset = [0,2,4,6,8,10,12,np.nan]
# respRateMean = np.delete(respRateMean,[5,6])
# respRateSem = np.delete(respRateSem,[5,6])
# fracCorrMean = np.delete(fracCorrMean,[5,6])
# fracCorrSem = np.delete(fracCorrSem,[5,6])
# reacTimeMedian = np.delete(reacTimeMedian,[5,6])

# simple model (no normalization)
tauIRange = slice(0,1,1)
alphaRange = slice(0,1,1)
etaRange = slice(0,1,1)
sigmaRange = slice(0.2,1.1,0.1)
tauARange = slice(0.5,5,0.5)
inhibRange = slice(0.5,1.05,0.05)
thresholdRange = slice(0.1,1.5,0.1)
trialEndRange = slice(trialEndMax,trialEndMax+1,1)

# [0, 0 ,0 , 0.4, 2.5, 1, 0.7, 24]

# with dynamic divisive normalization
tauIRange = slice(0.3,1.2,0.1)
alphaRange = slice(0.05,0.25,0.05)
etaRange = slice(1,2,1)
sigmaRange = slice(0.4,1.3,0.1)
tauARange = slice(2,9,0.5)
inhibRange = slice(0.6,1.05,0.05)
thresholdRange = slice(0.5,1.6,0.1)
trialEndRange = slice(trialEndMax,trialEndMax+1,1)

# [0.5, 0.05, 1, 1, 4.5, 0.8,  1, 24]

# fit with reaction times
tauIRange = slice(0.3,1.2,0.2)
alphaRange = slice(0.05,0.2,0.05)
etaRange = slice(1,2,1)
sigmaRange = slice(0.2,1.2,0.1)
tauARange = slice(1,10,1)
decayRange = slice(0,1.1,0.2)
inhibRange = slice(0,1,0.1)
thresholdRange = slice(0.6,2,0.1)
trialEndRange = slice(78,79,1)
postDecisionRange = slice(6,30,6)

# [0.0, 0.0, 0.0, 0.4, 1.0, 0.8, 0.0, 1.4, 214.0, 0.0] old no reac time fit
# [0.0, 0.0, 0.0, 0.5, 6.0, 0.2, 0.3, 1.8, 300.0, 18.0] old reac time fit

# [1.1, 0.15, 1.0, 0.4, 1.0, 0.6, 0.4, 1.9, 78.0, 18.0] # mice


# fit
fitParamRanges = (tauIRange,alphaRange,etaRange,sigmaRange,tauARange,decayRange,inhibRange,thresholdRange,trialEndRange,postDecisionRange)
fixedParams = (signals,targetSide,maskOnset,optoOnset,optoSide,trialsPerCondition,respRateMean,fracCorrMean,reacTimeMean)

fit = fitModel(fitParamRanges,fixedParams,finish=False)


# run model using best fit params
tauI,alpha,eta,sigma,tauA,decay,inhib,threshold,trialEnd,postDecision = fit

trialTargetSide,trialMaskOnset,trialOptoOnset,trialOptoSide,response,responseTime,Lrecord,Rrecord = runSession(signals,targetSide,maskOnset,optoOnset,optoSide,tauI,alpha,eta,sigma,tauA,decay,inhib,threshold,trialEnd,postDecision,trialsPerCondition=100000,record=True)

result = analyzeSession(targetSide,maskOnset,optoOnset,optoSide,trialTargetSide,trialMaskOnset,trialOptoOnset,trialOptoSide,response,responseTime,Lrecord,Rrecord)
responseRate = result['responseRate']
fractionCorrect = result['fractionCorrect']
responseTimeMedian= result['responseTimeMedian'] + postDecision


# compare fit to data
xticks = [mo/120*1000 for mo in maskOnset[:-1]+[maskOnset[-2]+2,maskOnset[-2]+4]]
xticklabels = ['mask\nonly']+[str(int(round(x))) for x in xticks[1:-2]]+['target\nonly','no\nstimulus']

xticks = [mo/120*1000 for mo in maskOnset[:-1]+[maskOnset[-2]+2]]
xticklabels = ['mask\nonly']+[str(int(round(x))) for x in xticks[1:-1]]+['target\nonly']

xlim = [-8,xticks[-1]+8]

for mean,sem,model,ylim,ylabel in  zip((respRateMean,fracCorrMean,reacTimeMean*dt),(respRateSem,fracCorrSem,reacTimeSem*dt),(responseRate,fractionCorrect,responseTimeMedian*dt),((0,1.02),(0.4,1),None),('Response Rate','Fraction Correct','Reaction Time (ms)')):
    fig = plt.figure()
    ax = fig.add_subplot(1,1,1)
    ax.plot(xticks,mean,'o',mec='k',mfc='none',ms=12,mew=2,label='mice')
    for x,m,s in zip(xticks,mean,sem):
        ax.plot([x,x],[m-s,m+s],'k')
    ax.plot(xticks,model,'o',mec='r',mfc='none',ms=12,mew=2,label='model')
    for side in ('right','top'):
        ax.spines[side].set_visible(False)
    ax.tick_params(direction='out',right=False,labelsize=14)
    if ylabel=='Fraction Correct':
        ax.set_xticks(xticks[1:-1])
        ax.set_xticklabels(xticklabels[1:-1])
    else:
        ax.set_xticks(xticks)
        ax.set_xticklabels(xticklabels)
        ax.legend(fontsize=12)
    ax.set_xlim(xlim)
    if ylim is not None:
        ax.set_ylim(ylim)
    ax.set_xlabel('Mask Onset Relative to Target Onset (ms)',fontsize=16)
    ax.set_ylabel(ylabel,fontsize=16)
    plt.tight_layout()
    

# leave one out fits
leaveOneOutFits = []
nconditions = len(respRateMean)
for i in range(nconditions):
    print('fitting leave out condition '+str(i+1)+' of '+str(nconditions))
    if i==nconditions-1:
        ts = [s for s in targetSide if s!=0]
        mo = maskOnset
        rr = respRateMean[:-1]
        fc = fracCorrMean[:-1]
    else:
        ts = targetSide
        mo = [m for j,m in enumerate(maskOnset) if j!=i]
        rr,fc = [np.array([d for j,d in enumerate(data) if j!=i]) for data in (respRateMean,fracCorrMean)]
    fixedParams=(signals,ts,mo,optoOnset,optoSide,trialsPerCondition,rr,fc)
    leaveOneOutFits.append(fitModel(fitParamRanges,fixedParams,finish=False))
    
#[array([ 0.5,  0.1,  1. ,  0.9,  4.5,  0.8,  0.9, 24. ]),
# array([ 0.6 ,  0.1 ,  1.  ,  1.  ,  4.  ,  0.75,  1.  , 24.  ]),
# array([ 0.6 ,  0.05,  1.  ,  1.1 ,  6.  ,  0.9 ,  0.9 , 24.  ]),
# array([ 0.6 ,  0.05,  1.  ,  1.1 ,  6.  ,  0.9 ,  0.9 , 24.  ]),
# array([ 0.6 ,  0.05,  1.  ,  1.1 ,  5.  ,  0.9 ,  1.  , 24.  ]),
# array([ 0.6,  0.1,  1. ,  1. ,  7.5,  0.9,  0.7, 24. ]),
# array([ 0.6 ,  0.05,  1.  ,  1.2 ,  5.  ,  1.  ,  1.1 , 24.  ])]

outOfSampleRespRate = []
outOfSampleFracCorr = []    
for i in range(nconditions):
    tauI,alpha,eta,sigma,tauA,inhib,threshold,trialEnd = leaveOneOutFits[i]
    trialTargetSide,trialMaskOnset,trialOptoOnset,trialOptoSide,response,responseTime,Lrecord,Rrecord = runSession(signals,targetSide,maskOnset,optoOnset,optoSide,tauI,alpha,eta,sigma,tauA,inhib,threshold,trialEnd,trialsPerCondition=100000,record=True)
    result = analyzeSession(targetSide,maskOnset,optoOnset,optoSide,trialTargetSide,trialMaskOnset,trialOptoOnset,trialOptoSide,response,responseTime)
    outOfSampleRespRate.append(result['responseRate'][i])
    outOfSampleFracCorr.append(result['fractionCorrect'][i])
    
for mean,sem,model,ylim,ylabel in  zip((respRateMean,fracCorrMean),(respRateSem,fracCorrSem),(outOfSampleRespRate,outOfSampleFracCorr),((0,1.02),(0.4,1)),('Response Rate','Fraction Correct')):
    fig = plt.figure()
    ax = fig.add_subplot(1,1,1)
    ax.plot(xticks,mean,'o',mec='k',mfc='none',ms=12,mew=2,label='mice')
    for x,m,s in zip(xticks,mean,sem):
        ax.plot([x,x],[m-s,m+s],'k')
    ax.plot(xticks,model,'o',mec='r',mfc='none',ms=12,mew=2,label='model (leave-one-out fits)')
    for side in ('right','top'):
        ax.spines[side].set_visible(False)
    ax.tick_params(direction='out',right=False,labelsize=14)
    if ylabel=='Fraction Correct':
        ax.set_xticks(xticks[1:-1])
        ax.set_xticklabels(xticklabels[1:-1])
    else:
        ax.set_xticks(xticks)
        ax.set_xticklabels(xticklabels)
        ax.legend(fontsize=12)
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.set_xlabel('Mask Onset Relative to Target Onset (ms)',fontsize=16)
    ax.set_ylabel(ylabel,fontsize=16)
    plt.tight_layout()

for diff,ylim,ylabel in  zip((outOfSampleRespRate-responseRate,outOfSampleFracCorr-fractionCorrect),([-0.2,0.2],[-0.2,0.2]),('$\Delta$ Response Rate','$\Delta$ Fraction Correct')):    
    fig = plt.figure()
    ax = fig.add_subplot(1,1,1)
    ax.plot([0,110],[0,0],'k--')
    ax.plot(xticks,diff,'ko',ms=8)
    for side in ('right','top'):
        ax.spines[side].set_visible(False)
    ax.tick_params(direction='out',right=False)
    ax.set_xticks(xticks)
    ax.set_xticklabels(xticklabels)
    ax.set_xlim(xlim)
    if ylim is not None:
        ax.set_ylim(ylim)
    ax.set_xlabel('Mask onset relative to target onset (ms)')
    ax.set_ylabel(ylabel)
    plt.tight_layout()


# example model traces
for side,lbl in zip((1,),('target right',)):#((1,0),('target right','no stim')):
    sideTrials = trialTargetSide==side
    maskOn = [np.nan] if side==0 else maskOnset
    for mo in [np.nan]:#maskOn:
        maskTrials = np.isnan(trialMaskOnset) if np.isnan(mo) else trialMaskOnset==mo
        trials = np.where(sideTrials & maskTrials)[0]
        for trial in trials[5:7]:
            fig = plt.figure()
            ax = fig.add_subplot(1,1,1)
            ax.plot([0,trialEndTimeMax],[threshold,threshold],'k--')
            ax.plot(t,Lrecord[trial],'b',lw=2,label='Ipsilateral')
            ax.plot(t,Rrecord[trial],'r',lw=2,label='Contralateral')
            for axside in ('right','top','left'):
                ax.spines[axside].set_visible(False)
            ax.tick_params(direction='out',right=False,top=False,left=False,labelsize=16)
            ax.set_xticks([0,50,100,150,200])
            ax.set_yticks([0,threshold])
            ax.set_yticklabels([0,'threshold'])
            ax.set_xlim([0,trialEndTimeMax])
            ax.set_ylim([-1.05*threshold,1.05*threshold])
            ax.set_xlabel('Time (ms)',fontsize=18)
            ax.set_ylabel('Decision Variable',fontsize=18)
            title = lbl
            if not np.isnan(mo):
                title += ' + mask (' + str(int(round(mo*dt))) + ' ms)'
            title += ', decision = '
            if response[trial]==-1:
                title += 'left'
            elif response[trial]==1:
                title += 'right'
            else:
                title += 'none'
#            ax.set_title(title)
            ax.legend(loc='lower right',fontsize=16)
            plt.tight_layout()


# masking decision time
fig = plt.figure()
ax = fig.add_subplot(1,1,1)
rt = []
for side in targetSide:
    maskOn = [np.nan] if side==0 else maskOnset
    for mo in maskOn:
        rt.append(np.median(result[side][mo][optoOnset[0]][optoSide[0]]['responseTime']))
ax.plot(xticks,dt*(np.array(rt)+postDecision),'ko')
for side in ('right','top'):
    ax.spines[side].set_visible(False)
ax.tick_params(direction='out',right=False)
ax.set_xticks(xticks)
ax.set_xticklabels(xticklabels)
ax.set_xlim(xlim)
ax.set_xlabel('Mask onset relative to target onset (ms)')
ax.set_ylabel('Median decision time (ms)')
plt.tight_layout()

fig = plt.figure()
ax = fig.add_subplot(1,1,1)
for respTime,mec,mfc,lbl in zip(('responseTimeCorrect','responseTimeIncorrect','responseTime',),('k','0.5','k'),('k','0.5','none'),('correct','incorrect','other')):
    rt = []
    for side in targetSide:
        maskOn = [np.nan] if side==0 else maskOnset
        for mo in maskOn:
            if side==0 or mo==0:
                if respTime=='responseTime':
                    rt.append(np.median(result[side][mo][optoOnset[0]][optoSide[0]][respTime]))
                else:
                    rt.append(np.nan)
            else:
                if respTime=='responseTime':
                    rt.append(np.nan)
                else:
                    rt.append(np.median(result[side][mo][optoOnset[0]][optoSide[0]][respTime]))
    ax.plot(xticks,dt*(np.array(rt)+postDecision),'o',mec=mec,mfc=mfc,ms=12,label=lbl)
for side in ('right','top'):
    ax.spines[side].set_visible(False)
ax.tick_params(direction='out',right=False,labelsize=14)
ax.set_xticks(xticks)
ax.set_xticklabels(xticklabels)
ax.set_xlim(xlim)
ax.set_xlabel('Mask Onset Relative to Target Onset (ms)',fontsize=16)
ax.set_ylabel('Median Reaction Time (ms)',fontsize=16)
ax.legend()
plt.tight_layout()


fig = plt.figure()
ax = fig.add_subplot(1,1,1)
ax.plot([0,trialEnd*dt],[0.5,0.5],'k--')
clrs = np.zeros((len(maskOnset)-1,3))
clrs[:-1] = plt.cm.plasma(np.linspace(0,0.85,len(maskOnset)-2))[::-1,:3]
lbls = [lbl+' ms' for lbl in xticklabels[1:-2]]+['target only']
ntrials = []
rt = []
rtCorrect = []
rtIncorrect = []
for maskOn,clr in zip(maskOnset[1:],clrs):
    trials = np.isnan(trialMaskOnset) if np.isnan(maskOn) else trialMaskOnset==maskOn
    trials = trials & (trialTargetSide>0)
    ntrials.append(trials.sum())
    respTrials = trials & (response!=0)
    c = (trialTargetSide==response)[respTrials]
    rt.append(dt*(responseTime[respTrials].astype(float)+postDecision))
    rtCorrect.append(dt*(responseTime[respTrials][c].astype(float)+postDecision))
    rtIncorrect.append(dt*(responseTime[respTrials][~c].astype(float)*dt+postDecision))
    fc = []
    for i in t[t>45]:
        j = (rt[-1]>=i) & (rt[-1]<i+dt)
        fc.append(np.sum(c[j])/np.sum(j))
    ax.plot(t[t>45]+dt/2,fc,'-',color=clr,lw=2)
for side in ('right','top'):
    ax.spines[side].set_visible(False)
ax.tick_params(direction='out',right=False,labelsize=14)
# ax.set_xticks([0,50,100,150,200])
# ax.set_xlim([50,200])
ax.set_ylim([0.2,1])
ax.set_xlabel('Reaction Time (ms)',fontsize=16)
ax.set_ylabel('Fraction Correct',fontsize=16)
plt.tight_layout()

fig = plt.figure()
ax = fig.add_subplot(1,1,1)
for r,n,clr,lbl in zip(rt,ntrials,clrs,lbls):
    s = np.sort(r)
    c = [np.sum(r<=i)/n for i in s]
    ax.plot(s,c,'-',color=clr,label=lbl)
for side in ('right','top'):
    ax.spines[side].set_visible(False)
ax.tick_params(direction='out',right=False,labelsize=14)
ax.set_xticks([0,50,100,150,200])
ax.set_xlim([0,200])
ax.set_ylim([0,1.02])
ax.set_xlabel('Decision Time (ms)',fontsize=16)
ax.set_ylabel('Cumulative Probability',fontsize=16)
ax.legend(title='mask onset',fontsize=11,loc='upper left')
plt.tight_layout()

fig = plt.figure()
ax = fig.add_subplot(1,1,1)
for lbl,clr in zip(('no stim','mask only'),('0.5','g')):
    trials = trialTargetSide==0 if lbl=='no stim' else trialMaskOnset==0
    respTrials = trials & (response!=0)
    r = responseTime[respTrials].astype(float)*dt
    s = np.sort(r)
    c = [np.sum(r<=i)/len(s) for i in s]
    ax.plot(s,c,color=clr,label=lbl)
for rc,ri,clr,lbl in zip(rtCorrect,rtIncorrect,clrs,lbls):
    for r,ls in zip((rc,ri),('-','--')):
        s = np.sort(r)
        c = [np.sum(r<=i)/len(s) for i in s]
        l = lbl+', correct' if ls=='-' else lbl+', incorrect'
        ax.plot(s,c,ls,color=clr,label=l)
#ax.plot(-1,-1,'-',color='0.5',label='correct')
#ax.plot(-1,-1,'--',color='0.5',label='incorrect')
for side in ('right','top'):
    ax.spines[side].set_visible(False)
ax.tick_params(direction='out',right=False,labelsize=14)
ax.set_xticks([0,50,100,150,200])
ax.set_xlim([0,200])
ax.set_ylim([0,1.02])
ax.set_xlabel('Model Decision Time (ms)',fontsize=16)
ax.set_ylabel('Cumulative Probability',fontsize=16)
#ax.legend(loc='lower right',fontsize=11)
plt.tight_layout()


# balance of evidence
fig = plt.figure()
ax = fig.add_subplot(1,1,1)
evidenceCorr = []
evidenceIncorr = []
for side in targetSide:
    maskOn = [np.nan] if side==0 else maskOnset
    for mo in maskOn:
        if not (side==0 or mo==0):
            evidence = []
            for evLbl in ('evidenceLeftCorrect','evidenceRightCorrect','evidenceLeftIncorrect','evidenceRightIncorrect'):
                ev = result[side][mo][optoOnset[0]][optoSide[0]][evLbl] / threshold
                ev[ev>1] = 1
                ev[ev<0] = 0
                evidence.append(ev)
            evLcorr,evRcorr,evLincorr,evRincorr = evidence
            evidenceCorr.append(np.mean(evRcorr - evLcorr))
            evidenceIncorr.append(np.mean(evLincorr - evRincorr))
ax.plot(xticks[1:-1],evidenceCorr,'go')
ax.plot(xticks[1:-1],evidenceIncorr,'mo')
for side in ('right','top'):
    ax.spines[side].set_visible(False)
ax.tick_params(direction='out',right=False)
ax.set_xticks(xticks)
ax.set_xticklabels(xticklabels)
ax.set_xlim(xlim)
ax.set_xlabel('Mask onset relative to target onset (ms)')
ax.set_ylabel('Balance of evidence')
plt.tight_layout()


# opto masking
maskOnset = [0,2,np.nan]
optoOnset = list(range(2,11))+[np.nan]
optoSide = [0]
optoLatency = 1

trialTargetSide,trialMaskOnset,trialOptoOnset,trialOptoSide,response,responseTime,Lrecord,Rrecord = runSession(signals,targetSide,maskOnset,optoOnset,optoSide,tauI,alpha,eta,sigma,tauA,inhib,threshold,trialEnd,trialsPerCondition=100000,optoLatency=optoLatency)

result = analyzeSession(targetSide,maskOnset,optoOnset,optoSide,trialTargetSide,trialMaskOnset,trialOptoOnset,trialOptoSide,response,responseTime)

xticks = [x*dt for x in optoOnset[::2]]+[100]
xticklabels = [int(round(x)) for x in xticks[:-1]]+['no\nopto']
x = np.array(optoOnset)*dt
x[-1] = 100
for measure,ylim,ylabel in  zip(('responseRate','fractionCorrect','responseTime'),((0,1),(0.4,1),None),('Response Rate','Fraction Correct','Mean decision time (ms)')):
    fig = plt.figure()
    ax = fig.add_subplot(1,1,1)
    if measure=='fractionCorrect':
        j = 2
        ax.plot([0,xticks[-1]+dt],[0.5,0.5],'k--')
    else:
        j = 0
    for lbl,side,mo,clr in zip(('target only','target + mask','mask only','no stim'),(1,1,1,0),(np.nan,2,0,np.nan),'kbgm'):
        if measure!='fractionCorrect' or 'target' in lbl:
            d = []
            for optoOn in optoOnset:
                if measure=='responseTime':
                    d.append(dt*np.mean(result[side][mo][optoOn][optoSide[0]][measure]))
                else:
                    d.append(result[side][mo][optoOn][optoSide[0]][measure])
            ax.plot(x[:-1],d[:-1],color=clr,label=lbl)
            ax.plot(xticks[j:],np.array(d)[np.in1d(x,xticks)][j:],'o',color=clr,ms=12)
    for side in ('right','top'):
        ax.spines[side].set_visible(False)
    ax.tick_params(direction='out',right=False,labelsize=14)
    ax.set_xticks(xticks)
    ax.set_xticklabels(xticklabels)
    ax.set_xlim([8,108])
    if ylim is not None:
        ax.set_ylim(ylim)
    ax.set_xlabel('Simulated Inhibition Relative to Target Onset (ms)',fontsize=16)
    ax.set_ylabel(ylabel,fontsize=16)
#    if measure=='responseRate':
#        ax.legend(loc='upper left',fontsize=12)
    plt.tight_layout()
    
# combine with masking data
fig = plt.figure()
ax = fig.add_subplot(1,1,1)
ax.plot(xticks[2:],responseRate[[1,3,4,5]],'o',mec='r',mfc='none',mew=2,ms=12,label='masking') 
d = np.array([result[1][np.nan][optoOn][optoSide[0]]['responseRate'] for optoOn in optoOnset]) 
ax.plot(xticks,d[[0,2,4,6,8,9]],'o',mec='b',mfc='none',mew=2,ms=12,label='inhibition')
for side in ('right','top'):
    ax.spines[side].set_visible(False)
ax.tick_params(direction='out',top=False,right=False,labelsize=14)
ax.set_xticks(xticks)
ax.set_xticklabels(['-17','0','17','33','50','no mask or\ninhibition'])
ax.set_xlim([8,108])
ax.set_ylim([0,1])
ax.set_xlabel('Mask or Inhibition Onset (ms)',fontsize=16)
ax.set_ylabel('Response Rate',fontsize=16)
ax.legend(fontsize=14)
plt.tight_layout()

fig = plt.figure()
ax = fig.add_subplot(1,1,1)
ax.plot([8,108],[0.5,0.5],'k--')
ax.plot(xticks[2:],fractionCorrect[[1,3,4,5]],'o',mec='r',mfc='none',mew=2,ms=12,label='masking')
d = np.array([result[1][np.nan][optoOn][optoSide[0]]['fractionCorrect'] for optoOn in optoOnset])
ax.plot(xticks,d[[0,2,4,6,8,9]],'o',mec='b',mfc='none',mew=2,ms=12,label='inhibition')
for side in ('right','top'):
    ax.spines[side].set_visible(False)
ax.tick_params(direction='out',top=False,right=False,labelsize=14)
ax.set_xticks(xticks)
ax.set_xticklabels(['-17','0','17','33','50','no mask or\ninhibition'])
ax.set_xlim([8,108])
ax.set_ylim([0.4,1])
ax.set_xlabel('Mask or Inhibition Onset (ms)',fontsize=16)
ax.set_ylabel('Fraction Correct',fontsize=16)
#ax.legend(fontsize=14)
plt.tight_layout()


# unilateral opto
maskOnset = [np.nan]
optoOnset = [0]
optoSide = [-1,0,1]

trialTargetSide,trialMaskOnset,trialOptoOnset,trialOptoSide,response,responseTime,Lrecord,Rrecord = runSession(signals,targetSide,maskOnset,optoOnset,optoSide,tauI,alpha,eta,sigma,tauA,inhib,threshold,trialEnd,trialsPerCondition=100000)

result = analyzeSession(targetSide,maskOnset,optoOnset,optoSide,trialTargetSide,trialMaskOnset,trialOptoOnset,trialOptoSide,response,responseTime)


# behav
signalsCorr = createInputSignals(fileIO.getFile('Load popPsth correct',fileType='*.pkl'))[0]
signalsIncorr = createInputSignals(fileIO.getFile('Load popPsth incorrect',fileType='*.pkl'))[0]

maskOnset = [2,np.nan]
optoOnset = [np.nan]
optoSide = [0]

respRate = []
fracCorr = []
rtAll = []
rtCorr = []
rtIncorr = []
for sig in (signals,signalsCorr,signalsIncorr):
    trialTargetSide,trialMaskOnset,trialOptoOnset,trialOptoSide,response,responseTime,Lrecord,Rrecord = runSession(sig,targetSide,maskOnset,optoOnset,optoSide,tauI,alpha,eta,sigma,tauA,inhib,threshold,trialEnd,trialsPerCondition=100000)
    result = analyzeSession(targetSide,maskOnset,optoOnset,optoSide,trialTargetSide,trialMaskOnset,trialOptoOnset,trialOptoSide,response,responseTime)
    respRate.append(result['responseRate'])
    fracCorr.append(result['fractionCorrect'])
    for i,(rt,respTime) in enumerate(zip((rtAll,rtCorr,rtIncorr),('responseTime','responseTimeCorrect','responseTimeIncorrect'))):
        rt.append([])
        for side in targetSide:
            maskOn = [np.nan] if side==0 else maskOnset
            for mo in maskOn:
                if side==0 or mo==0:
                    if respTime=='responseTime':
                        rt[-1].append(dt*np.median(result[side][mo][optoOnset[0]][optoSide[0]][respTime]))
                    else:
                        rt[-1].append(np.nan)
                else:
                    rt[-1].append(dt*np.median(result[side][mo][optoOnset[0]][optoSide[0]][respTime]))


for data,ylim,ylabel in  zip((respRate,fracCorr),((0,1.02),(0.4,1)),('Response Rate','Fraction Correct')):
    fig = plt.figure()
    ax = fig.add_subplot(1,1,1)
    if data is fracCorr:
        ax.plot([-1,2],[0.5,0.5],'k--')
    for d,clr,lbl in zip(data,'kgm',('all','correct','incorrect')):
        ax.plot([0,1],d[:2],'o',mec=clr,mfc='none',ms=12,mew=2,label=lbl)
    for side in ('right','top'):
        ax.spines[side].set_visible(False)
    ax.tick_params(direction='out',right=False,labelsize=14)
    ax.set_xticks([0,1])
    ax.set_xticklabels(['mask onset\n17 ms','target only'])
    ax.set_xlim([-0.3,1.3])
    ax.set_ylim(ylim)
    ax.set_ylabel('Model '+ylabel,fontsize=16)
    leg = ax.legend(title='mouse trials',fontsize=12)
    plt.setp(leg.get_title(),fontsize=12)
    plt.tight_layout()




