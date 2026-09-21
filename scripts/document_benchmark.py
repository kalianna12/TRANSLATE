"""Declared text/layout fixtures inspired by user attachments, not original-image tests."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from benchmark import normalized, edit_distance
from screenlingo.ocr import MultilingualOCR
from screenlingo.core import Translator

SAMPLES = {
    "ja": [
        "「ただの友達同士なんだから、エドガーと二人きりで街に出掛けても良いわよね？」",
        "そう言い放つ騎士科の令嬢ミーシャ・ホワイトに気弱なクラリスはいつも口籠ってしまう。",
        "常日頃からクラリスの婚約者と「男友達みたいなものだから」と言って仲睦まじくするミーシャにいつも",
        "気が引けていたのだ。",
        "「私もクラリスみたいに繊細で可愛い女の子だったら良かったんだけどなあ」",
        "「そういうところが男の子達に面白がられちゃうんだけど、それはそれで失礼よね？」",
        "「あーあ、私もクラリスみたいな性格だったら女の子達とうまくやっていけたんだけどなあ」",
        "しかしそんな折に気弱な令嬢クラリスは前世の記憶を思い出し、ミーシャの行動にふ…",
    ],
    "en": [
        "The lids of the girl's eyes lifted slowly, and she stared at the panel of light in the wall.",
        "Just at the outset, the act of seeing made not the least impression on her numbed brain.",
        "For a long time she continued to regard the dim illumination in the wall with the same passive fixity of gaze.",
        "Apathy still lay upon her crushed spirit. In a vague way, she realized her own inertness, and rested in it",
        "gratefully, subtly fearful lest she again arouse to the full horror of her plight.",
        "In a curious subconscious fashion, she was striving to hold on to this deadness of sensation,",
        "thus to win a little respite from the torture that had exhausted her soul.",
        "Of a sudden, her eyes noted the black lines that lay across the panel of light.",
        "And, in that instant, her spirit was quickened once again. The clouds lifted from her brain.",
        "Vision was clear now. Understanding seized the full import of this hideous thing on which she looked.",
        "For the panel of light was a window, set high within a wall of stone.",
        "The rigid lines of black that crossed it were bars--prison bars. It was still true, then:",
        "She was in a cell of the Tombs.",
        "The girl, crouching miserably on the narrow bed, maintained fixed watching of the window.",
        "That window was a symbol of her utter despair. Again, agony wrenched within her.",
        "She did not weep: long ago she had exhausted the relief of tears.",
    ],
    "ko": [
        "그래. 이거면 됐어.",
        "체자레는 걸터앉아 있던 아버지의 옥좌에서 뛰어 내려와 아리아드네의 손을 맞잡았다.",
        "전달되어 오는 체온에 아리아드네는 그의 기쁨과 애정이 전염되는 것 같아 몸을 부르르 떨었다.",
        "잘했어. 그놈의 목숨만 취하고 나면 나는 당신을 왕국에서 가장 고귀한 여자로 만들 거야.",
        "아버지는 오늘내일하셔. 언제 돌아가셔도 이상하지 않아.",
        "늙은 왕이 병석에 누운 지금, 알폰소 왕자마저 실각하고 나니 체자레 데 코모를 막을 수 있는 사람은 이제 아무도 없었다.",
        "이로써 우리의 시대가 오는 거야.",
        "그녀는 새 시대에 관심이 없었다. 그저 그가 기뻐한다면, 그런 그의 옆에 있을 수 있으면 그것으로 충분했다.",
        "체자레 데 코모, 에트루스칸 왕국의 변경백이자 알폰소 왕자의 사촌인 그는 국왕 레오 3세가 병석에 눕자",
        "곧바로 국경의 군사를 일으켜 왕성을 점령했다. 명분은 알폰소 왕자가 레오 3세를 독살하려고 했다는 것이었다.",
        "아무도 그 말을 믿지 않았지만 왕성을 가득 채운 체자레의 사병 앞에서 불만을 토로하는 자는 없었다.",
        "보라! 알폰소 왕자는 적국과 내통하여 국왕 폐하를 독살하려 한 왕위에 오르려던 간악한 반역자다!",
    ],
}


def fixture(language):
    sizes = {"ja": 26, "en": 27, "ko": 20}
    fonts = {"ja": "YuGothL.ttc", "en": "arial.ttf", "ko": "malgun.ttf"}
    size = sizes[language]
    font = ImageFont.truetype("C:/Windows/Fonts/" + fonts[language], size)
    texts = SAMPLES[language]
    width = max(1340, int(max(font.getlength(t) for t in texts)) + 90)
    gap = {"ja": 66, "en": 63, "ko": 53}[language]
    image = Image.new("RGB", (width, gap * len(texts) + 40), "#eff7ff" if language == "en" else "white")
    draw = ImageDraw.Draw(image)
    for i, text in enumerate(texts):
        draw.text((30, 20 + i * gap), text, font=font, fill="#111111")
    return image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--output", default="artifacts/document-benchmark.json")
    parser.add_argument("--progressive", action="store_true")
    args = parser.parse_args()
    output = Path("artifacts/documents")
    output.mkdir(exist_ok=True, parents=True)
    engine = MultilingualOCR()
    rows = []
    for lang in SAMPLES:
        image = fixture(lang)
        image.save(output / (lang + ".png"))
        bgr = np.array(image)[:, :, ::-1].copy()
        reference = normalized("".join(SAMPLES[lang]))
        for fast in (False, True):
            engine.document_fast_path = fast
            samples = []
            first_chunks = []
            for _ in range(3):
                engine.cache.clear()
                started = time.perf_counter()
                chunks = []
                callback = lambda lines: chunks.append((time.perf_counter() - started) * 1000)
                result = engine(bgr, source=lang, on_chunk=callback if args.progressive else None)
                samples.append((time.perf_counter() - started) * 1000)
                first_chunks.append(chunks[0] if chunks else samples[-1])
            texts = [line[1] for line in result]
            actual = normalized("".join(texts))
            row = {"language": lang, "fast_enabled": fast, "dimensions": image.size,
                   "progressive": args.progressive,
                   "first_chunk_median_ms": statistics.median(first_chunks),
                   "ocr_median_ms": statistics.median(samples), "ocr_runs_ms": samples,
                   "metrics": engine.last_metrics.copy(), "recognized": texts,
                   "char_errors": edit_distance(reference, actual), "char_count": len(reference),
                   "line_count": len(texts), "reference_line_count": len(SAMPLES[lang])}
            if args.network:
                translator = Translator(source=lang)
                try:
                    translator.warm_connection()
                    started = time.perf_counter()
                    translations = translator.translate(texts)
                    row.update(translate_ms=(time.perf_counter() - started) * 1000,
                               translations=translations, network_calls=translator.network_calls)
                finally:
                    translator.close()
            rows.append(row)
            print(lang, fast, round(row["ocr_median_ms"], 1), row["metrics"]["detector"],
                  "errors", row["char_errors"], "translation", round(row.get("translate_ms", 0)),
                  "requests", row.get("network_calls"), flush=True)
    Path(args.output).write_text(json.dumps({"scope": "Transcribed synthetic page layouts; not original user images. No portraits, annotations or manga artwork reproduced.",
                                            "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
