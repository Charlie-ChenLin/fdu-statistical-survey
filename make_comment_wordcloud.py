#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import jieba
from wordcloud import WordCloud, STOPWORDS


DEFAULT_INPUT = Path("outputs/weibo_shortdrama_comments_180d.ndjson")
DEFAULT_OUTPUT = Path("weibo_shortdrama_wordcloud.png")
DEFAULT_FONT = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")


CN_STOPWORDS = {
    "的","了","是","在","我","也","就","都","很","啊","吧","吗","呢","呀",
    "你","他","她","它","我们","你们","他们","她们","它们","这","那","一个",
    "这个","那个","怎么","什么","为什么","因为","所以","如果","但是","而且",
    "然后","不是","没有","还有","感觉","觉得","可以","可能","不过","这样",
    "真的","已经","还是","就是","不是","只是","一次","现在","还是","一下",
    "以及","一下","一些","非常","很多","比较","一起","一直","一下子",
}

SHORTDRAMA_KEYWORDS = ["短剧", "微短剧"]
PAY_KEYWORDS = [
    "付费", "充值", "会员", "月卡", "周卡", "季卡", "年卡", "点券", "解锁", "广告解锁",
    "看广告", "免广告", "包月", "包年", "买断", "花钱", "收费", "价格", "太贵", "便宜",
]


def _clean_text(text: str) -> str:
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"@\S+", " ", text)
    text = re.sub(r"#.+?#", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _contains_any(text: str, keywords: list[str]) -> bool:
    blob = (text or "").lower()
    return any(kw.lower() in blob for kw in keywords)


def _is_target_comment(text: str) -> bool:
    return _contains_any(text, SHORTDRAMA_KEYWORDS) and _contains_any(text, PAY_KEYWORDS)


def load_comment_texts(path: Path) -> list[str]:
    texts: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            comment = (obj.get("comment") or {})
            text = (comment.get("text") or "").strip()
            if not text:
                continue
            if not _is_target_comment(text):
                continue
            texts.append(_clean_text(text))
    return texts


def tokenize(texts: list[str]) -> Counter:
    stopwords = set(STOPWORDS) | CN_STOPWORDS
    counter: Counter = Counter()
    for text in texts:
        for token in jieba.lcut(text, cut_all=False):
            token = token.strip()
            if not token or token in stopwords:
                continue
            if len(token) < 2:
                continue
            counter[token] += 1
    return counter


def build_wordcloud(freqs: Counter, font_path: Path) -> WordCloud:
    return WordCloud(
        font_path=str(font_path),
        width=900,
        height=600,
        background_color="white",
        max_words=200,
        colormap="viridis",
        random_state=42,
        collocations=False,
        prefer_horizontal=0.9,
    ).generate_from_frequencies(freqs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate wordcloud from comment texts.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT)
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input not found: {args.input}")
    if not args.font.exists():
        raise SystemExit(f"Font not found: {args.font}")

    texts = load_comment_texts(args.input)
    freqs = tokenize(texts)
    wc = build_wordcloud(freqs, args.font)
    wc.to_file(str(args.output))
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
