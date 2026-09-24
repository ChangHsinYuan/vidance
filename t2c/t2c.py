import argparse, torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

def main():
    p = argparse.ArgumentParser(description='自然语言 -> Vidance 命令')
    p.add_argument('text', nargs='?', help='中文输入，不给则进入交互模式')
    p.add_argument('--model', default='model', help='模型目录')
    a = p.parse_args()

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    dtype = torch.float16 if device == 'cuda' else torch.float32
    tok = AutoTokenizer.from_pretrained(a.model)
    net = AutoModelForSeq2SeqLM.from_pretrained(a.model, torch_dtype=dtype).to(device).eval()

    def gen(text):
        inputs = tok(text, return_tensors='pt', max_length=256, truncation=True).to(device)
        with torch.no_grad():
            out = net.generate(**inputs, max_new_tokens=128, num_beams=5, early_stopping=True)
        return tok.decode(out[0], skip_special_tokens=True)

    if a.text:
        print(gen(a.text))
    else:
        while True:
            try:
                t = input('> ').strip()
            except (EOFError, KeyboardInterrupt):
                break
            if t.lower() in ('q', 'quit', 'exit'):
                break
            if t:
                print(' ', gen(t))

main()
