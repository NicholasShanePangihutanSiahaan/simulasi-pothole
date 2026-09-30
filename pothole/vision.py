"""Explainable OpenCV baseline on rendered camera pixels, not ground truth.

Replace Detector.detect with the trained FOMO model once its weights and exact
preprocessing / output contract are available. No FOMO accuracy is claimed here.
"""
import math
import cv2
import numpy as np


class Detector:
    name = 'OpenCV · baseline simulasi'

    def __init__(self, cfg):
        self.cfg = cfg

    def detect(self, rgb):
        h,w = rgb.shape[:2]
        gray = cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
        focal = w/(2*math.tan(self.cfg['hfov']/2))
        # Rays intersecting a flat road between 0.7 and 3m; camera pitch is downward.
        mask = cv2.inRange(gray,0,self.cfg['dark_threshold'])
        mask[:int(h*.50),:] = 0
        mask[:,:int(w*.10)] = 0
        mask[:,int(w*.90):] = 0
        mask = cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
        contours,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        detections=[]
        for contour in contours:
            area=cv2.contourArea(contour)
            x,y,bw,bh=cv2.boundingRect(contour)
            if area<self.cfg['min_area'] or area>w*h*.20 or bw<7 or bh<3 or bw/bh<.7 or bw/bh>10:
                continue
            u,v=x+bw/2,y+bh/2
            alpha = self.cfg['camera_pitch']+math.atan((v-h/2)/focal)
            if alpha<=.05:
                continue
            distance = self.cfg['camera_height']/math.tan(alpha)
            lateral = (u-w/2)/focal*math.sqrt(distance*distance+self.cfg['camera_height']**2)
            if not (.6<distance<=self.cfg['max_distance']) or abs(lateral)>1.5:
                continue
            # Reject elongated borders and low fill-factor cracks/shadows.
            fill=area/max(1,bw*bh)
            if fill<.32:
                continue
            detections.append({'box':[x,y,bw,bh], 'distance':round(distance,2),
                               'area':int(area), 'score':round(min(.99,.50+fill*.4),2)})
        return sorted(detections,key=lambda d:d['distance'])

    def annotate(self, rgb, detections, enabled=True):
        bgr = cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)
        for d in detections:
            x,y,w,h=d['box']
            cv2.rectangle(bgr,(x,y),(x+w,y+h),(67,216,245),2)
            cv2.putText(bgr,f"DUGAAN LUBANG | {d['distance']:.1f}m",(x,max(20,y-8)),
                        cv2.FONT_HERSHEY_SIMPLEX,.45,(67,216,245),1,cv2.LINE_AA)
        cv2.putText(bgr,'OPENCV BASELINE' if enabled else 'VISION NONAKTIF',(14,25),
                    cv2.FONT_HERSHEY_SIMPLEX,.5,(220,238,232),1,cv2.LINE_AA)
        return bgr
