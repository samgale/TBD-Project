# -*- coding: utf-8 -*-
"""
Created on Fri Mar 20 12:45:29 2020

@author: chelsea.strawder

I'm still working on this plotting 
Creates plots of trial length by SOA (or specified parameter)

can easily call using plot_by_param(create_df(import_data()))
"""


import numpy as np
import matplotlib
import seaborn as sns
import matplotlib.pyplot as plt

def plot_by_param(df, selection='all', param1='soa', param2='trialLength', 
                  stat='Median', ylim='auto', errorBars=False):    
    ''' 
        selection = 'all', 'hits', or 'misses'
        param1 = 'soa', 'targetContrast', or 'targetDuration'
        param2 = 'trialLength', 'initiationTime', 'outcomeTime'
        stat = 'Median' or 'Mean'
        ylim needs to be list of [min, max]
    '''

    matplotlib.rcParams['pdf.fonttype'] = 42
    sns.set_style('white')
    

    nonzeroRxns = df[(df['trialLength']!=df['trialLength'].max()) & 
                     (df['ignoreTrial']!=True) & (df['resp']!=0)]
    # ^ this excludes noResp trials and correct NoGos; soa=-1 are nogo trials 
    
    corrNonzero = nonzeroRxns[(nonzeroRxns['resp']==1) & (nonzeroRxns['nogo']==False)]
    missNonzero = nonzeroRxns[(nonzeroRxns['resp']==-1) & (nonzeroRxns['nogo']==False)]
    
    if len(corrNonzero)>0:
        v = corrNonzero.groupby(['rewDir', param1])[param2].describe()
        print('correct response times\n', v, '\n\n')
    if len(missNonzero)>0:
        y = missNonzero.groupby(['rewDir', param1])[param2].describe()
        print('incorrect response times\n', y)

 ### how to make this less bulky/redundant??     
    param_list = [x for x in np.unique(nonzeroRxns[param1]) if x >=0]   
 
    hits = [[],[]]  #R, L
    misses = [[],[]]   #R, L by rewDir
    maskOnly = []
  # change maskOnly filter to show turning direction
    
    for val in param_list:
        hitVal = [[],[]]
        missVal = [[],[]]
        for j, (time, p, resp, direc, mask) in enumerate(zip(
                nonzeroRxns[param2], nonzeroRxns[param1], nonzeroRxns['resp'], 
                nonzeroRxns['rewDir'], nonzeroRxns['maskContrast'])):
            if p==val:  
                if direc==1:       
                    if resp==1:
                        hitVal[0].append(time)  
                    else:
                        missVal[0].append(time)  
                elif direc==-1:   
                    if resp==1:
                        hitVal[1].append(time)  
                    else:
                        missVal[1].append(time)
                elif direc==0 and mask>0:
                    maskOnly.append(time)
           
        for i in (0,1):         
            hits[i].append(hitVal[i])
            misses[i].append(missVal[i])
            
    if stat=='Median':
        func=np.median
        hitErr = [[np.std(val)/(len(val)**0.5) for val in lst] for lst in hits]
        missErr = [[np.std(val)/(len(val)**0.5) for val in lst] for lst in misses]
    else:
        func=np.mean
        hitErr = [[np.std(val) for val in lst] for lst in hits]
        missErr = [[np.std(val) for val in lst] for lst in misses]
    
    #* func is median or mean as above
    avgHits = [[func(x) for x in side] for side in hits]   # 0=R, 1=L
    avgMisses = [[func(x) for x in side] for side in misses]
    

    #* consider using median absolute deviation or confidence interval when using median
    #* ci = np.percentile([func(np.random.choice(data,len(data),replace=True)) for _ in range(1000)],(2.5,97.5))
    
    #* need shape=(2,len(param_list)) for plt.errorbar()  ** ask sam about this
            

    
### plotting 
    
    ## this will be useful for plotting multiple params at once - trialLength and Time to Initiate
    ## need to write that code though


    fig, ax = plt.subplots()
    
    if selection.lower() in ('all','hits'):
        ax.plot(param_list, avgHits[0], 'ro-', label='Correct R turn',  alpha=.6, lw=3)
        ax.plot(param_list, avgHits[1], 'bo-', label='Correct L turn', alpha=.6, lw=3)
    if selection.lower() in ('all','misses'):  
        ax.plot(param_list, avgMisses[0], 'bo-', mfc='none', label='Incorrect L turn', ls='--', alpha=.3, lw=2)
        ax.plot(param_list, avgMisses[1], 'ro-', mfc='none', label='Incorrect R turn', ls='--', alpha=.3, lw=2)
        #used to plot incorrect based on RewDir, changed to actual direction turned 
   
    if errorBars: #* don't need ==True
        if selection.lower() in ('all','hits'):
            plt.errorbar(param_list, avgHits[0], yerr=hitErr[0], c='r', alpha=.6)
            plt.errorbar(param_list, avgHits[1], yerr=hitErr[1], c='b', alpha=.6)
        if selection.lower() in ('all','misses'):
            plt.errorbar(param_list, avgMisses[0], yerr=missErr[0], c='b', alpha=.3)
            plt.errorbar(param_list, avgMisses[1], yerr=missErr[1], c='r', alpha=.3)

     
    if param1=='soa':
        m = func(maskOnly)    
        ax.plot(8, m, marker='o', c='k')
        param_list[0] = 8
        if errorBars:
            s = np.std(maskOnly)/(len(maskOnly)**0.5)
            ax.plot([8,8],[m-s,m+s],'k')
        
    plt.suptitle((str(df.mouse) + '   ' + str(df.date)))  # need ot figure out loss of df metadata
    
    ax.set_xticks(param_list)   
    a = ax.get_xticks().tolist()
    if param1=='soa':
        a = [int(i) for i in a if i>=0]
        a[0] = 'Mask\nOnly'
        a[-1] = 'Target\nOnly'
    ax.set_xticklabels(a)
    matplotlib.rcParams["legend.loc"] = 'best'
    ax.legend()
    
    for side in ('right','top'):
        ax.spines[side].set_visible(False)
    ax.tick_params(direction='out',top=False,right=False)
    
    
    if param1=='soa':
        xlbl = 'SOA (ms)'
    elif param1=='targetContrast':
        xlbl = 'Target Contrast'
    elif param1=='targetDuration':
        xlbl = 'Target Duration (ms)'
        
    ax.set_xlabel(xlbl)
    ax.set_ylabel('Time from Target Onset (ms)')
    
    if param1!='soa':
        ax.set_xlim([0,1.02*param_list[-1]])
    
    #* maybe make an optional input ylim='auto' which is useful if you want to 
    # make multiple plots with the same ylim
    if ylim != 'auto': 
        ax.set_ylim(ylim)
    else:
        ax.set_ylim([200,700])
    
    #* prevents text from getting cut off at figure edges
    plt.tight_layout()

 