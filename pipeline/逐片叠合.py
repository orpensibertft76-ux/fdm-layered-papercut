from PIL import Image, ImageDraw, ImageFont
import cv2
import numpy as np

from build_dragon import WORK, CHECK, PALETTE, N, RIM, JOB

names = JOB["layers"]
size = 430
sheet = Image.new("RGB", (1870, 1020), "#f8f3e9")
draw = ImageDraw.Draw(sheet)
font_path = "C:/Windows/Fonts/msyh.ttc"
title = ImageFont.truetype(font_path, 32)
label = ImageFont.truetype(font_path, 21)
draw.text((24,16), f"{JOB['name']}  ·  实际切片逐片叠合", font=title, fill="#211a16")

# The path previews are generated from each plate's top-layer G-code.
# Exact gray is their empty canvas. Match the slicer verifier's resampling.
levels = np.zeros((N,N),np.uint8)
for i,name in enumerate(names):
    with Image.open(CHECK/f"切片顶层_{i+1:02d}.png") as im:
        occupied = np.all(np.asarray(im.convert("RGB")) == PALETTE[i], axis=2)
    route = cv2.resize(occupied.astype(np.uint8)*255,(N,N),interpolation=cv2.INTER_AREA)>95
    levels[route] = i
    row,col = divmod(i,3)
    x,y = 24+col*462,66+row*472
    prefix = "铺" if i == 0 else "加"
    draw.text((x,y),f"{i+1:02d}  {prefix}{name}",font=label,fill="#211a16")
    card = Image.fromarray(PALETTE[levels[RIM:-RIM,RIM:-RIM]])
    sheet.paste(card.resize((size,size),Image.Resampling.LANCZOS),(x,y+30))

with Image.open(CHECK/"实际路径叠合.png") as im:
    assert np.array_equal(np.asarray(im),np.asarray(card))
with Image.open(WORK/"reference.png") as im:
    original = im.convert("RGB").crop(JOB["reference_crop"])
draw.text((1410,538),"001 原设计图 · 同画口",font=label,fill="#211a16")
sheet.paste(original.resize((size,size),Image.Resampling.LANCZOS),(1410,568))
draw.text((1410,210),"从背板堆到前片",font=title,fill="#211a16")
draw.text((1410,263),"每格保留前面已经叠上的色片。",font=label,fill="#51463b")
draw.text((1410,302),"右下原稿用于对照最终叠合。",font=label,fill="#51463b")
sheet.save(CHECK/"逐片切片叠合与原设计.png")
