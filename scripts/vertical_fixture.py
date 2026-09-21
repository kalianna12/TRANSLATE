"""A synthetic upright vertical Japanese fixture, transcribed from the reported layout."""
from PIL import Image, ImageDraw, ImageFont


COLUMNS = ["思えば高一のとき", "三者面談で", "いきなり東大を", "目指しだして以来"]


def vertical_fixture(size=32):
    image = Image.new("RGB", (size * 7 + 16, size * 10), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/YuGothM.ttc", size)
    for column, text in enumerate(COLUMNS):
        x = image.width - 16 - size - column * int(size * 1.75)
        for row, char in enumerate(text):
            draw.text((x, 5 + row * size), char, font=font, fill="black", anchor="lt")
    return image


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import numpy as np
    from screenlingo.ocr import MultilingualOCR
    image = vertical_fixture()
    image.save("artifacts/vertical-fixture.png")
    engine = MultilingualOCR()
    result = engine(np.array(image)[:, :, ::-1].copy())
    print([(line[0], ascii(line[1]), line[2]) for line in result])
