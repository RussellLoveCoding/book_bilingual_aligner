# -*- coding: utf-8 -*-
"""生成正文行内标记图标（AI 补译 / 内容审查修复），输出 base64。

产物直接粘贴进 bil/build.py 的 _ICON_AI_B64 / _ICON_CENSOR_B64。
图标要求：无文字的 <img>（alt=""），微信读书听书 TTS 不读图片，
原来的文本标记「AI译」「【内容审查修复提示】」会被读出来（用户反馈）。

用法（Pillow 装在 managed venv 里）：
  C:/Users/abc/.workbuddy/binaries/python/envs/default/Scripts/python.exe tools/gen_icons.py
"""
import base64
import io

from PIL import Image, ImageDraw, ImageFont


def make(text: str, fill, path_font: str, size_px: int = 28,
         font_px: int = 15) -> str:
    img = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size_px - 1, size_px - 1], radius=7, fill=fill)
    font = ImageFont.truetype(path_font, font_px)
    l, t, r, b = d.textbbox((0, 0), text, font=font)
    d.text(((size_px - (r - l)) / 2 - l, (size_px - (b - t)) / 2 - t),
           text, font=font, fill="white")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


if __name__ == "__main__":
    print("AI_B64 =", repr(make("AI", (122, 90, 245, 255),
                                r"C:\Windows\Fonts\arialbd.ttf")))
    print()
    print("CENSOR_B64 =", repr(make("审", (224, 130, 30, 255),
                                    r"C:\Windows\Fonts\msyhbd.ttc")))
