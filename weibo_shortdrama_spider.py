#!/usr/bin/env python3
"""
轻量级微博爬虫：按关键词抓取短剧付费意愿相关的博文评论，并提取评论者信息/平台/短剧名称/是否大学生的粗略判定。

借鉴 DSBA 范例的注意事项：
- 登录态必须有（Cookie 中包含 SUB 等）；若未提供 Cookie，可开启 --allow-anon 但成功率/数据量会显著降低；
- 控速（内置 sleep，支持 --sleep 参数），避免 418；
- 时间窗口默认近 90 天（--since-days 可改）；
- 通过个人信息关键词粗判“大学生”；
- 请求失败会重试，微博异步/未返回时有限等待。

使用示例（请遵守平台条款）：
python weibo_shortdrama_spider.py --query "短剧 付费" --pages 3 --max-comments 40 --since-days 90 --out outputs/weibo_shortdrama_comments.ndjson --cookie "$WEIBO_COOKIE"
默认查询集：["短剧 付费", "微短剧 付费", "短剧 广告解锁", "短剧 会员"]
"""
import argparse
import html
import json
import os
import pathlib
import re
import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

import requests


# 默认关键词集合（覆盖“短剧/微短剧”及付费/广告/会员/充值等变体，提升召回）
DEFAULT_QUERIES = [
    "短剧",
    "微短剧",
    "短剧 付费",
    "微短剧 付费",
    "短剧 充值",
    "微短剧 充值",
    "短剧 会员",
    "微短剧 会员",
    "短剧 广告",
    "短剧 广告解锁",
    "短剧 看广告",
    "短剧 免广告",
    "短剧 月卡",
    "短剧 点券",
    "短剧 解锁",
    "短剧 vip",
    "短剧 花钱",
    "短剧 推荐",
    "短剧 剧情",
    "短剧 追更",
]

# 粗略匹配平台/短剧名称的关键词与正则
PLATFORM_KEYWORDS: Dict[str, List[str]] = {
    "抖音": ["抖音", "douyin"],
    "快手": ["快手"],
    "番茄短剧": ["番茄短剧", "番茄小说"],
    "微信视频号": ["视频号", "微信短剧"],
    "腾讯短剧": ["腾讯短剧", "tencent短剧"],
    "爱奇艺短剧": ["爱奇艺短剧", "iqiyi短剧"],
    "优酷短剧": ["优酷短剧", "youku短剧"],
    "星芽短剧": ["星芽短剧", "星芽"],
    "河马剧场": ["河马剧场"],
}
DRAMA_BRACKET_RE = re.compile(r"[《「](.{2,30}?)[》」]")
STUDENT_KEYWORDS = [
    "大学", "本科", "大一", "大二", "大三", "大四", "大五", "研一", "研二", "研三",
    "研究生", "博士", "校园", "学院", "在校", "学生"
]
PAY_KEYWORDS = [
    "付费", "充值", "会员", "月卡", "周卡", "季卡", "年卡", "点券", "解锁", "广告解锁",
    "看广告", "免广告", "包月", "包年", "买断", "花钱", "收费", "价格", "太贵", "便宜"
]
MARKETING_KEYWORDS = [
    "博主", "官方", "机器人", "营销", "推广", "自媒体", "娱乐博主", "情感博主"
]


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<.*?>", "", text)
    text = html.unescape(text)
    return text.replace("\u200b", "").strip()


def detect_platforms(text: str) -> List[str]:
    text_lower = text.lower()
    hits = []
    for name, kws in PLATFORM_KEYWORDS.items():
        if any(kw.lower() in text_lower for kw in kws):
            hits.append(name)
    return sorted(set(hits))


def detect_dramas(text: str) -> List[str]:
    if not text:
        return []
    names = []
    for m in DRAMA_BRACKET_RE.findall(text):
        cleaned = m.strip()
        if cleaned and len(cleaned) >= 2 and len(cleaned) <= 30 and cleaned not in ("短剧", "微短剧"):
            names.append(cleaned)
    return sorted(set(names))


def detect_student(user: Dict[str, str]) -> Tuple[bool, Optional[str]]:
    fields = {
        "description": str(user.get("description", "") or ""),
        "screen_name": str(user.get("screen_name", "") or ""),
        "verified_reason": str(user.get("verified_reason", "") or ""),
    }
    blob_lower = " ".join(fields.values()).lower()
    for kw in STUDENT_KEYWORDS:
        if kw.lower() in blob_lower:
            # 需命中的字段非空才判为“学生线索”
            if any(kw.lower() in fields[k].lower() and fields[k].strip() for k in fields):
                return True, kw
    return False, None


def detect_pay_intent(text: str) -> bool:
    t = (text or "").lower()
    return any(kw.lower() in t for kw in PAY_KEYWORDS)


def parse_followers(val) -> float:
    """
    将粉丝数解析为数字，用于过滤大号/营销号。
    """
    if val is None:
        return 0.0
    s = str(val)
    try:
        # 处理 “1.2万” / “9873” 这类格式
        if "万" in s:
            return float(s.replace("万", "")) * 10000
        return float(s.replace(",", ""))
    except Exception:
        return 0.0


def is_marketing_user(user: Dict[str, str], max_followers: int) -> bool:
    if not user:
        return False
    vr = str(user.get("verified_reason", "") or "")
    sn = str(user.get("screen_name", "") or "")
    desc = str(user.get("description", "") or "")
    blob = f"{vr} {sn} {desc}".lower()
    if any(kw.lower() in blob for kw in MARKETING_KEYWORDS):
        return True
    followers = parse_followers(user.get("followers") or user.get("followers_count"))
    if max_followers > 0 and followers >= max_followers:
        return True
    return False


def fetch_full_status_text(sess: requests.Session, status: Dict, cache: Dict[str, str]) -> str:
    """
    若微博为长文或包含“全文”提示，调用 extend 接口获取完整正文；带缓存避免重复请求。
    """
    sid = status.get("id")
    raw = status.get("text", "") or ""
    if not sid:
        return strip_html(raw)
    if sid in cache:
        return cache[sid]
    need_full = bool(status.get("isLongText")) or ("全文" in raw)
    if not need_full:
        cache[sid] = strip_html(raw)
        return cache[sid]
    try:
        resp = safe_get(sess, "https://m.weibo.cn/statuses/extend", params={"id": sid})
        long_text = resp.json().get("data", {}).get("longTextContent") or raw
        cache[sid] = strip_html(long_text)
    except Exception as e:
        print(f"[WARN] fetch long text failed for {sid}: {e}")
        cache[sid] = strip_html(raw)
    return cache[sid]


def init_session(cookie: str = "", allow_anon: bool = False) -> requests.Session:
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
        "Referer": "https://m.weibo.cn",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    })
    if cookie:
        sess.headers["Cookie"] = cookie
    elif not allow_anon:
        raise SystemExit("缺少 Cookie（需 SUB 等）。请设置环境变量 WEIBO_COOKIE 或传 --cookie；如需匿名尝试可加 --allow-anon（成功率低）。")
    else:
        print("[WARN] 以未登录模式尝试，接口可能返回空/被限流；推荐提供有效 Cookie。")
    return sess


def parse_weibo_time(ts: str) -> Optional[datetime]:
    """
    尝试解析微博时间字段。返回 UTC-naive datetime（本地时区按 +0800 处理）。
    """
    if not ts:
        return None
    ts = ts.strip()
    # 形如 "Thu Apr 04 17:48:56 +0800 2024"
    dt = None
    try:
        dt = parsedate_to_datetime(ts)
    except Exception:
        dt = None
    if dt:
        return dt.replace(tzinfo=None)
    # 形如 "2024-04-04 17:48:56"
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt)
        except Exception:
            pass
    # 形如 "04-04"（无年份，补当前年）
    for fmt in ("%m-%d",):
        try:
            d = datetime.strptime(ts, fmt)
            now = datetime.now()
            return d.replace(year=now.year)
        except Exception:
            pass
    # 相对时间（今天/刚刚/xx分钟前）：直接用当前时间近似
    return datetime.now()


def in_time_window(created_at: str, since_days: int) -> bool:
    dt = parse_weibo_time(created_at)
    if not dt:
        return True  # 无法解析时不过滤
    cutoff = datetime.now() - timedelta(days=since_days)
    return dt >= cutoff


def safe_get(sess: requests.Session, url: str, **kwargs) -> requests.Response:
    """
    轻量重试，处理 418/5xx/网络闪断。
    """
    backoff = 1.0
    for attempt in range(4):
        resp = sess.get(url, timeout=15, **kwargs)
        if resp.status_code in (500, 502, 503, 504, 418):
            if resp.status_code == 418:
                print(f"[WARN] 418 {url}, stop.")
                break
            time.sleep(backoff)
            backoff *= 1.6
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()
    return resp


def fetch_statuses(sess: requests.Session, query: str, page: int, sleep_sec: float) -> List[Dict]:
    containerid = f"100103type%3D1%26q%3D{quote(query)}"
    url = "https://m.weibo.cn/api/container/getIndex"
    params = {"containerid": containerid, "page_type": "searchall", "page": page}
    resp = safe_get(sess, url, params=params)
    data = resp.json().get("data", {})
    cards = data.get("cards", []) or []
    results = []
    for card in cards:
        if card.get("card_type") != 9:
            continue
        mblog = card.get("mblog")
        if mblog:
            results.append(mblog)
    time.sleep(sleep_sec)
    return results


def fetch_comments(sess: requests.Session, status_id: str, max_comments: int, sleep_sec: float) -> Iterable[Dict]:
    """
    使用 m.weibo.cn/hotflow 接口抓取评论（支持 max_id 翻页）。
    """
    url = "https://m.weibo.cn/comments/hotflow"
    params = {"id": status_id, "mid": status_id, "max_id_type": 0}
    fetched = 0
    max_id = None
    while fetched < max_comments:
        if max_id:
            params["max_id"] = max_id
        resp = safe_get(sess, url, params=params)
        if resp.status_code == 418:
            print(f"[WARN] 418 for status {status_id}, stop comments.")
            break
        j = resp.json().get("data", {})
        items = j.get("data", []) or []
        for item in items:
            yield item
            fetched += 1
            if fetched >= max_comments:
                break
        max_id = j.get("max_id")
        if not max_id:
            break
        time.sleep(sleep_sec)  # 避免过快


def slim_user(user: Dict) -> Dict:
    if not user:
        return {}
    is_student, hit = detect_student(user)
    return {
        "id": user.get("id"),
        "screen_name": user.get("screen_name"),
        "description": user.get("description"),
        "location": user.get("location"),
        "gender": user.get("gender"),
        "followers": user.get("followers_count"),
        "follows": user.get("follow_count"),
        "verified_type": user.get("verified_type"),
        "verified_reason": user.get("verified_reason"),
        "is_student_hint": is_student,
        "student_hit": hit,
    }


def build_record(query: str, status: Dict, comment: Dict, status_text: Optional[str] = None) -> Dict:
    status_text = status_text if status_text is not None else strip_html(status.get("text", ""))
    comment_text = strip_html(comment.get("text", ""))
    platforms = sorted(set(detect_platforms(status_text) + detect_platforms(comment_text)))
    dramas = sorted(set(detect_dramas(status_text) + detect_dramas(comment_text)))
    return {
        "query": query,
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        # 顶层冗余写一份帖子的 id，方便直接筛选/关联
        "status_id": status.get("id"),
        "status_mid": status.get("mid"),
        "status": {
            "id": status.get("id"),
            "mid": status.get("mid"),
            "created_at": status.get("created_at"),
            "reposts": status.get("reposts_count"),
            "comments": status.get("comments_count"),
            "attitudes": status.get("attitudes_count"),
            "text": status_text,
            "platforms": detect_platforms(status_text),
            "dramas": detect_dramas(status_text),
            "user": slim_user(status.get("user") or {}),
        },
        "comment": {
            "id": comment.get("id"),
            "root_id": comment.get("rootid") or status.get("id"),
            "created_at": comment.get("created_at"),
            "like_count": comment.get("like_counts"),
            "text": comment_text,
            "platforms": detect_platforms(comment_text),
            "dramas": detect_dramas(comment_text),
            "user": slim_user(comment.get("user") or {}),
        },
        "combined_platforms": platforms,
        "combined_dramas": dramas,
    }


def crawl_queries(sess: requests.Session,
                  queries: List[str],
                  pages: int,
                  max_comments_per_status: int,
                  since_days: int,
                  sleep_sec: float,
                  pay_filter: bool,
                  marketing_filter: bool,
                  max_followers: int,
                  students_only: bool) -> Iterable[Dict]:
    longtext_cache: Dict[str, str] = {}
    for q in queries:
        print(f"[INFO] Query '{q}' ...")
        for page in range(1, pages + 1):
            try:
                statuses = fetch_statuses(sess, q, page, sleep_sec)
            except Exception as e:
                print(f"[WARN] fetch_statuses failed q={q} page={page}: {e}")
                continue
            if not statuses:
                break
            for st in statuses:
                status_id = st.get("id")
                if not status_id or not in_time_window(st.get("created_at", ""), since_days):
                    continue
                status_text_full = fetch_full_status_text(sess, st, longtext_cache)
                for cm in fetch_comments(sess, str(status_id), max_comments_per_status, sleep_sec):
                    rec = build_record(q, st, cm, status_text=status_text_full)
                    # 过滤：付费相关关键词
                    if pay_filter:
                        if not (detect_pay_intent(rec["status"]["text"]) or detect_pay_intent(rec["comment"]["text"])):
                            continue
                    # 过滤：营销号/大号
                    if marketing_filter:
                        st_user = rec["status"]["user"]
                        cm_user = rec["comment"]["user"]
                        if is_marketing_user(st_user, max_followers) or is_marketing_user(cm_user, max_followers):
                            continue
                    # 过滤：只要学生线索
                    if students_only:
                        st_student = rec["status"]["user"].get("is_student_hint")
                        cm_student = rec["comment"]["user"].get("is_student_hint")
                        if not (st_student or cm_student):
                            continue
                    yield rec
            time.sleep(sleep_sec)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Weibo crawler for short-drama payment willingness comments.")
    p.add_argument("--query", action="append", dest="queries", help="搜索关键词，可多次传入；为空时用默认集合。")
    p.add_argument("--pages", type=int, default=3, help="每个关键词抓取的页数（搜索结果页）。")
    p.add_argument("--max-comments", type=int, default=50, help="每条博文抓取的评论数量上限。")
    p.add_argument("--since-days", type=int, default=90, help="仅保留最近 N 天的微博（默认 90）。")
    p.add_argument("--sleep", type=float, default=0.6, help="请求间隔秒数，控制频率避免 418。")
    p.add_argument("--out", default="outputs/weibo_shortdrama_comments.ndjson", help="输出 NDJSON 路径。")
    p.add_argument(
        "--cookie",
        default=os.getenv(
            "WEIBO_COOKIE",
            "_T_WM=29671675699; "
            "ALF=1768065337; "
            "BAIDU_SSP_lcr=https://open.weixin.qq.com/; "
            "M_WEIBOCN_PARAMS=oid%3D5242836841663008%26lfid%3D5242836841663008%26luicode%3D20000174; "
            "MLOGIN=1; "
            "SCF=AvhteMreU7JbWvH4R43yUvjbVqOYwKgj7UwvzdiEz0zmMu_ve6e0In1R21HFnpCp9lw6OE6VNuss6t8XFR5fzvY.; "
            "SSOLoginState=1765473337; "
            "SUB=_2A25EPoxpDeRhGeBI6VAU8CzFwj2IHXVnNYGhrDV6PUJbktCOLWajkW1NRo3EbmJ7FCLdvpiCdCGyv3EivWZZ_qy0; "
            "SUBP=0033WrSXqPxfM725Ws9jqgMF55529P9D9WFO9zY-KFIcyRgpD_o1fJ0O5NHD95QcSozESK5E1K.pWs4DqcjMi--NiK.Xi-2Ri--ciKnRi-zNSoqEeo-7eo.4eBtt; "
            "WEIBOCN_FROM=1110006030; "
            "XSRF-TOKEN=246ba9"
        ),
        help="微博 Cookie（含 SUB）。",
    )
    p.add_argument("--allow-anon", action="store_true", help="允许无 Cookie 匿名尝试（成功率低，可能无数据）。")
    p.add_argument("--no-pay-filter", dest="pay_filter", action="store_false", help="关闭付费关键词过滤（默认开启）。")
    p.add_argument("--max-followers", type=int, default=200000, help="营销号过滤的粉丝数阈值（默认 200000，<=0 表示不看粉丝数）。")
    p.add_argument("--no-marketing-filter", dest="marketing_filter", action="store_false", help="关闭营销号过滤（默认开启）。")
    p.add_argument("--students-only", action="store_true", help="仅保留含学生线索的帖子或评论。")
    p.set_defaults(pay_filter=True, marketing_filter=True)
    return p.parse_args()

"""
从网页复制的cookie内容
SUB	_2AkMeZmECf8NxqwFRmv4QzmrlbI90yQDEieKoOpDZJRMxHRl-yT9kqk0gtRB6NeZP7ctkfRRGiEy1Kla4xvI-P4IRvhbU	.weibo.com	/	2026-12-11T16:15:49.583Z	97	✓	✓	None			Medium
SUBP	0033WrSXqPxfM72-Ws9jqgMF55529P9D9WhFRRf6yKTg8qiErMJBRUem	.weibo.com	/	2026-12-11T16:15:49.583Z	60						Medium
WBPSESS	J3XGACCH-8SPj9NpOr7hzUfGfkfrwhdmxQET4wMGUNh3V9F6FMTcpPUImjbvUbexTmxmkY-LU5pVMoerClZE2P-H9KIBi_QCKduMJ2UmYZAjAj0SkgWa6cm0chYPYaXaMewTooaRiqdMPP644zoi2w609hNYlz0NNO1MYlJBJBU=	weibo.com	/	2025-12-12T16:15:49.799Z	179	✓	✓				Medium
XSRF-TOKEN	jG3dKC_dKyVtkHwO7kre6WnA	weibo.com	/	Session	34		✓				Medium
"""
def ensure_parent(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def main():
    args = parse_args()
    queries = args.queries or DEFAULT_QUERIES
    out_path = pathlib.Path(args.out)
    ensure_parent(out_path)
    sess = init_session(args.cookie, allow_anon=args.allow_anon)

    with out_path.open("w", encoding="utf-8") as f:
        for rec in crawl_queries(
            sess,
            queries,
            args.pages,
            args.max_comments,
            args.since_days,
            args.sleep,
            args.pay_filter,
            args.marketing_filter,
            args.max_followers,
            args.students_only,
        ):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[DONE] Saved to {out_path.resolve()}")


if __name__ == "__main__":
    main()

"""
python weibo_shortdrama_spider.py \
  --since-days 365 \
  --pages 1000 \ 
  --max-comments 1000 \
  --sleep 1.0 \
  --out outputs/weibo_shortdrama_comments_180d.ndjson \
  --no-pay-filter \
"""
