"""One explicit image/text request per invocation; credentials never in arguments."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screenlingo.baidu_probe import BaiduProbe, ProbeError, TestBudget


def main():
    parser = argparse.ArgumentParser(description="百度小样本测试：单次请求，不自动重试")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image", type=Path)
    group.add_argument("--text-file", type=Path)
    parser.add_argument("--source", choices=["auto", "jp", "en", "kor"], default="auto")
    parser.add_argument("--live", action="store_true", help="实际上传素材并消耗额度")
    args = parser.parse_args()
    if not args.live:
        print("未发送请求。实际测试需添加 --live；图片会上传百度。")
        return 0
    appid = os.environ.get("BAIDU_APP_ID") or input("百度 APPID: ").strip()
    secret = os.environ.get("BAIDU_API_KEY") or getpass.getpass("开发者密钥（不回显）: ")
    budget_path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ScreenLingo" / "baidu-test-budget.sqlite3"
    try:
        client = BaiduProbe(appid, secret, TestBudget(budget_path))
        result = (client.image(args.image, args.source) if args.image else
                  client.text(args.text_file.read_text(encoding="utf-8"), args.source))
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except ProbeError as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
