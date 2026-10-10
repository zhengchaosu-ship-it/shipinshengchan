from config import PATHS
import cv2
import numpy as np

vp = str(PATHS.sample_video("green"))
cap = cv2.VideoCapture(vp)
fps = cap.get(cv2.CAP_PROP_FPS)
total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
duration = total / fps
print(f"视频时长: {int(duration//60)}分{int(duration%60)}秒")

found = []
sec = 0
step = 2  # 每2秒抽一帧
while sec < duration:
    cap.set(cv2.CAP_PROP_POS_MSEC, sec*1000)
    ret, frame = cap.read()
    if not ret:
        sec += step
        continue
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # 绿色衣服的HSV范围
    lower_g = np.array([35, 50, 50])
    upper_g = np.array([85, 255, 255])
    mask = cv2.inRange(hsv, lower_g, upper_g)
    ratio = np.sum(mask>0) / mask.size
    if ratio > 0.08:  # 绿色像素占比超过8%，认为是绿衣服
        m, s = int(sec//60), int(sec%60)
        found.append((m, s, round(ratio,3)))
    sec += step
cap.release()

print(f"\n找到 {len(found)} 个有绿衣服的时间点:")
for m,s,r in found:
    print(f"{m:02d}:{s:02d}  绿色占比:{r*100:.1f}%")
