"""衣橱系统演示（BigBanana 借鉴 · v17 缺口④）：Base Look 锁脸，N 套服装同角色出图。

用法: python input/rag_test/m6_wardrobe_test.py [--gen]   # --gen 真出图（GPU），缺省只生成 prompt
输出: output/m6/wardrobe/{prompts.json,kf_*.png,contact.jpg}（--gen 时）
"""
import json
import os
import sys

_ROOT = os.path.abspath(__file__)
for _ in range(3):
    _ROOT = os.path.dirname(_ROOT)
sys.path.insert(0, _ROOT)

OUT = os.path.join('output', 'm6', 'wardrobe')
BASE_LOOK = ('孔乙己：站立于咸亨酒店，身材高大，青白脸色，皱纹间常夹伤痕，'
             '花白乱胡子，约五十岁，清瘦，长指甲——脸型/胡须/体型/年龄感为不可变特征')
COSTUMES = [
    {'name': 'chushi', 'desc': '出场：穿一件又脏又破的长衫，似乎十多年没有补也没有洗，'
                               '袖口磨破起毛，站在短衣帮酒客中间'},
    {'name': 'luopo', 'desc': '落魄：黑瘦，穿一件破夹袄，盘着两腿，下面垫一个蒲包，'
                              '用草绳挂在肩上，脸上一层灰'},
    {'name': 'duantui', 'desc': '断腿后：用手走来，穿一件破夹袄，满手是泥，'
                              '膝盖磨损严重，草绳松垮挂肩'},
]
os.makedirs(OUT, exist_ok=True)
PROMPTS_JSON = os.path.join(OUT, 'prompts.json')


def main():
    gen = '--gen' in sys.argv
    if os.path.isfile(PROMPTS_JSON) and not gen:
        outfits = json.load(open(PROMPTS_JSON))
        print(f'[衣橱] 缓存 {PROMPTS_JSON}（{len(outfits)} 套）')
    else:
        from agents.common.tools.llm import LLMClient
        lc = LLMClient()
        print('[衣橱] LLM 生成 %d 套服装 prompt（Base Look 锁脸）…' % len(COSTUMES))
        for attempt in range(3):
            try:
                outfits = lc.optimize_costume_prompts(BASE_LOOK, COSTUMES)
                break
            except Exception as e:
                print(f'  第 {attempt + 1} 次失败: {e}')
                if attempt == 2:
                    raise
        json.dump(outfits, open(PROMPTS_JSON, 'w'), ensure_ascii=False, indent=1)
        print(f'[衣橱] ✓ {PROMPTS_JSON}')
    for o in outfits:
        print(f"  - {o['name']}: {o['prompt'][:90]}…")
    if not gen:
        print('\n（--gen 真出图）')
        return

    from agents.generator.tools.comfy_api import ComfyClient
    flux = ComfyClient(instance='flux')
    STYLE = ('1910s rural Zhejiang China, vintage black and white documentary photo, '
             'grainy film texture, photorealistic, early republican era Chinese tavern')
    pngs = []
    for o in outfits:
        p = os.path.join(OUT, f'kf_{o["name"]}.png')
        pngs.append(p)
        if os.path.isfile(p):
            print(f'[出图] {o["name"]} 已存在，跳过')
            continue
        prompt = f"{o['prompt']}, {STYLE}"
        flux.generate_flux_t2i(prompt, width=832, height=1216, steps=20,
                               guidance=3.5, output_path=p)
        print(f'[出图] ✓ {p}')
    from PIL import Image, ImageDraw
    tw, th = 416, 608
    sheet = Image.new('RGB', (tw * len(pngs), th), 'black')
    dr = ImageDraw.Draw(sheet)
    for i, (p, o) in enumerate(zip(pngs, outfits)):
        sheet.paste(Image.open(p).resize((tw, th)), (i * tw, 0))
        dr.rectangle([i * tw + 8, 8, i * tw + 160, 44], fill='black')
        dr.text((i * tw + 16, 14), o['name'], fill='white')
    contact = os.path.join(OUT, 'contact.jpg')
    sheet.save(contact, quality=88)
    print(f'[拼贴] ✓ {contact}')


if __name__ == '__main__':
    main()
