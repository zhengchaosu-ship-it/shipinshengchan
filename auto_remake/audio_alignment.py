"""有限时间带16k mono声学比对；MFCC+subsequence DTW，无ASR/下载/视频裁切。"""
import math
from pathlib import Path
import time

import av
import numpy as np
from numba import njit

from .transcript_alignment import RULES
from speech_search.common import normalize


def audio_chunks(ref):
    chunks=[];i=0
    while i<len(ref):
        chosen=None
        for count in (1,2,3):
            part=ref[i:i+count]
            if len(part)!=count:break
            duration=part[-1]['reference_end']-part[0]['reference_start']
            if duration>RULES['audio_chunk_max_seconds']:break
            if any(b['reference_start']-a['reference_end']>1.5 for a,b in zip(part,part[1:])):break
            text=' '.join(p['text'] for p in part)
            if duration>=RULES['audio_chunk_min_seconds'] and len(normalize(text))>=RULES['audio_chunk_min_characters']:
                chosen=dict(anchor_id=f'audio_{len(chunks)+1:02d}',reference_start=part[0]['reference_start'],reference_end=part[-1]['reference_end'],
                    reference_midpoint=(part[0]['reference_start']+part[-1]['reference_end'])/2,text=text,ref_segment_ids=[r['ref_segment_id'] for r in part]);break
        if chosen:chunks.append(chosen);i+=count
        else:i+=1
    return chunks


def decode_audio(path,start,end):
    if not 0<=start<end or end-start>RULES['audio_max_band_seconds']:
        raise ValueError('只允许有限局部音频带，不允许全片扫描')
    t=time.perf_counter();rate=RULES['audio_sample_rate'];samples=np.zeros(int(math.ceil((end-start)*rate)),dtype=np.float32)
    present=np.zeros(len(samples),dtype=bool);seen=[]
    with av.open(str(path)) as c:
        stream=c.streams.audio[0];video=c.streams.video[0]
        if video.start_time is None:raise ValueError('无法确认视频时间原点，拒绝猜测')
        origin=float(video.start_time*video.time_base)
        requested=int((origin+max(0,start-.5))*av.time_base)
        c.seek(requested,backward=True,any_frame=False)
        resampler=av.AudioResampler(format='fltp',layout='mono',rate=rate)
        for frame in c.decode(audio=0):
            if frame.pts is None:raise ValueError('音频帧缺少真实PTS')
            timestamp=float(frame.pts*frame.time_base)-origin
            if not seen and timestamp<start-20:raise ValueError('seek未到局部区域，禁止从头扫描')
            seen.append(timestamp)
            if timestamp>end+.25:break
            for output in resampler.resample(frame):
                if output.pts is None:raise ValueError('resample丢失PTS')
                position=round((float(output.pts*output.time_base)-origin-start)*rate)
                values=output.to_ndarray().reshape(-1).astype(np.float32)
                a=max(0,position);b=min(len(samples),position+len(values))
                if b>a:samples[a:b]=values[a-position:b-position];present[a:b]=True
        metadata=dict(path=str(path),requested_start=start,requested_end=end,video_pts_origin=origin,
            sample_rate=rate,samples=len(samples),decoded_frames=len(seen),decoded_first_timestamp=min(seen) if seen else None,
            decoded_last_timestamp=max(seen) if seen else None,decoded_coverage=float(present.mean()),
            time_source='audio frame PTS after16k resample relative to video stream start_time',decode_seconds=time.perf_counter()-t)
    if metadata['decoded_coverage']<.95:raise ValueError(f'局部音频解码覆盖不足: {metadata}')
    return samples,metadata


def features(samples):
    rate=RULES['audio_sample_rate'];win=RULES['audio_window_samples'];hop=RULES['audio_hop_samples'];nfft=RULES['audio_fft']
    if len(samples)<win:raise ValueError('音频太短')
    frames=np.lib.stride_tricks.sliding_window_view(samples,win)[::hop].copy()
    energy=np.sqrt(np.mean(frames**2,axis=1)+1e-12)
    frames*=np.hanning(win).astype(np.float32)
    power=np.abs(np.fft.rfft(frames,n=nfft,axis=1))**2
    mel=lambda f:2595*np.log10(1+f/700)
    hz=lambda m:700*(10**(m/2595)-1)
    knots=hz(np.linspace(mel(RULES['audio_low_hz']),mel(RULES['audio_high_hz']),RULES['audio_mel_bins']+2))
    frequencies=np.arange(nfft//2+1)*rate/nfft
    bank=np.stack([np.maximum(0,np.minimum((frequencies-knots[i])/(knots[i+1]-knots[i]),(knots[i+2]-frequencies)/(knots[i+2]-knots[i+1]))) for i in range(RULES['audio_mel_bins'])])
    logmel=np.log(np.maximum(power@bank.T,1e-10))
    basis=np.cos(np.pi/RULES['audio_mel_bins']*(np.arange(RULES['audio_mel_bins'])+.5)[None,:]*np.arange(1,RULES['audio_mfcc']+1)[:,None])
    cepstra=(logmel@basis.T).astype(np.float32)
    radius=int(RULES['audio_cmn_seconds']*rate/hop/2)
    padded=np.pad(cepstra,((radius,radius),(0,0)),mode='edge')
    sums=np.vstack([np.zeros((1,cepstra.shape[1])),np.cumsum(padded,axis=0,dtype=np.float64)])
    local_mean=(sums[2*radius+1:]-sums[:-2*radius-1])/(2*radius+1)
    cepstra=cepstra-local_mean
    cepstra/=np.maximum(np.std(cepstra,axis=0,keepdims=True),1.)
    delta=np.gradient(cepstra,axis=0)
    vec=np.concatenate([cepstra,RULES['audio_delta_weight']*delta],axis=1)
    vec/=np.maximum(np.linalg.norm(vec,axis=1,keepdims=True),1e-8)
    times=(np.arange(len(frames))*hop+win/2)/rate
    return vec.astype(np.float32),times,energy


@njit(cache=False)
def dtw_kernel(cost,penalty):
    m,n=cost.shape
    d=np.full((m+1,n+1),np.inf,np.float32);d[0,:]=0
    parent=np.zeros((m+1,n+1),np.uint8)
    for i in range(1,m+1):
        for j in range(1,n+1):
            best=d[i-1,j-1];op=1
            if j>=2 and d[i-1,j-2]+penalty<best:best=d[i-1,j-2]+penalty;op=2
            if i>=2 and d[i-2,j-1]+cost[i-2,j-1]+penalty<best:best=d[i-2,j-1]+cost[i-2,j-1]+penalty;op=3
            d[i,j]=best+cost[i-1,j-1];parent[i,j]=op
    return d[-1],parent


def acoustic_peaks(query,source,query_times,source_times,band_start):
    if len(query)<10:return []
    costs=np.clip(1-query@source.T,0,2).astype(np.float32)
    last,parent=dtw_kernel(costs,RULES['audio_warp_step_penalty'])
    peaks=[];duration=query_times[-1]-query_times[0]
    for endpoint in np.argsort(last):
        if endpoint==0 or not np.isfinite(last[endpoint]):continue
        i=len(query);j=int(endpoint);pairs=[]
        while i>0 and j>0:
            pairs.append((i-1,j-1));op=parent[i,j]
            if op==1:i-=1;j-=1
            elif op==2:i-=1;j-=2
            elif op==3:i-=2;j-=1
            else:break
        if i>0:continue
        pairs.reverse();a=source_times[pairs[0][1]];b=source_times[pairs[-1][1]]
        speed=(b-a)/max(.01,duration)
        if not RULES['audio_speed_range'][0]<=speed<=RULES['audio_speed_range'][1]:continue
        mid=band_start+(a+b)/2
        if any(abs(mid-p['source_midpoint'])<max(.5,duration/2) for p in peaks):continue
        score=float(np.clip(1-last[endpoint]/len(query),0,1))
        peaks.append(dict(score=score,source_start=band_start+float(a),source_end=band_start+float(b),source_midpoint=mid,
            speed_ratio=float(speed),alignment_frame_pairs=len(pairs),
            sampled_path=[dict(reference_time=float(query_times[x]),source_time=band_start+float(source_times[y])) for x,y in pairs[::max(1,len(pairs)//8)]]))
        if len(peaks)==3:break
    return peaks


def consistent_audio_chain(anchors):
    nodes=[];scores=[];parents=[]
    for layer,a in enumerate(anchors):
        if not a['individually_supported']:continue
        h=a['peaks'][0];n=dict(h,anchor_id=a['anchor_id'],layer=layer,reference_midpoint=a['reference_midpoint'],
            reference_start=a['reference_start'],reference_end=a['reference_end'])
        value=1+.1*h['score'];parent=None
        for j,old in enumerate(nodes):
            dr=n['reference_midpoint']-old['reference_midpoint'];ds=n['source_midpoint']-old['source_midpoint']
            if ds>=-RULES['audio_sequence_backtrack_tolerance_seconds'] and .5*dr-1<=ds<=2*dr+RULES['audio_sequence_jump_allowance_seconds']:
                candidate=scores[j]+1+.1*h['score']
                if candidate>value:value=candidate;parent=j
        nodes.append(n);scores.append(value);parents.append(parent)
    if not nodes:return []
    j=int(np.argmax(scores));chain=[]
    while j is not None:chain.append(nodes[j]);j=parents[j]
    return list(reversed(chain))


def verify_audio(reference_features,source_audio,band_start,chunks):
    started=time.perf_counter();qvec,qt,qe=reference_features;svec,st,se=features(source_audio);results=[]
    for chunk in chunks:
        mask=(qt>=chunk['reference_start'])&(qt<=chunk['reference_end'])
        peaks=acoustic_peaks(qvec[mask],svec,qt[mask],st,band_start)
        margin=peaks[0]['score']-peaks[1]['score'] if len(peaks)>1 else 0
        active=float((qe[mask]>max(1e-4,np.percentile(qe,75)*.05)).mean()) if mask.any() else 0
        okay=bool(peaks and peaks[0]['score']>=RULES['audio_min_score'] and margin>=RULES['audio_min_peak_margin'] and active>=.5)
        results.append(dict(chunk,reference_midpoint=(chunk['reference_start']+chunk['reference_end'])/2,peaks=peaks,
            peak_margin=margin,active_ratio=active,individually_supported=okay))
    chain=consistent_audio_chain(results)
    return dict(method='16k mono MFCC1–20+delta;5sCMN;rowL2;subsequenceDTW(1,1)/(1,2)/(2,1)',
        anchor_count=len(results),individually_supported=sum(a['individually_supported'] for a in results),
        consistent_anchor_count=len(chain),anchors=results,consistent_chain=chain,
        source_start=chain[0]['source_start'] if chain else None,source_end=chain[-1]['source_end'] if chain else None,
        acoustic_seconds=time.perf_counter()-started,asr_used=False,score_is_probability=False)
