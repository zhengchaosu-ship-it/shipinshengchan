from pathlib import Path
import sys, json
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'benchmark/experiments/dino_july_web'))
import search
from PIL import Image,ImageDraw
import numpy as np
from transformers import AutoImageProcessor
p=AutoImageProcessor.from_pretrained(search.SHARED/'weights/dinov2',local_files_only=True,use_fast=False)
cases=json.loads((OUT/'results.json').read_text(encoding='utf-8'))['cases']
board=Image.new('RGB',(5*224,2*249),'white'); d=ImageDraw.Draw(board)
stats=[]
for i,c in enumerate(cases):
    im=Image.open(c['query']).convert('RGB')
    v=p(images=[im],return_tensors='np')['pixel_values'][0]
    rgb=np.clip((v.transpose(1,2,0)*np.array(p.image_std)+np.array(p.image_mean))*255,0,255).round().astype('uint8')
    view=Image.fromarray(rgb);view.save(OUT/f'case_{c["case_id"]}_model_input.png')
    x=i%5*224;y=i//5*249;board.paste(view,(x,y+25));d.text((x+5,y+5),f'Case {c["case_id"]}',fill='black')
    w,h=im.size;scale=256/min(w,h);rw=int(w*scale);rh=int(h*scale)
    stats.append(dict(case_id=c['case_id'],query_size=[w,h],resized_size=[rw,rh],approx_original_crop_box=[(rw-224)/2/scale,(rh-224)/2/scale,(rw+224)/2/scale,(rh+224)/2/scale]))
board.save(OUT/'actual_model_inputs.jpg')
(OUT/'preprocessing.json').write_text(json.dumps({'processor':p.to_dict(),'cases':stats},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(stats))
