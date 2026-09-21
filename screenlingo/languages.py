def script_of(text):
    if any("\uac00" <= c <= "\ud7af" or "\u1100" <= c <= "\u11ff" for c in text):
        return "ko"
    if any("\u3040" <= c <= "\u30ff" for c in text):
        return "ja"
    if any("\u4e00" <= c <= "\u9fff" for c in text):
        return "CJK"
    return "en"


LANGUAGE_NAMES = {"en": "英语", "ja": "日语", "ko": "韩语", "CJK": "中/日汉字"}
