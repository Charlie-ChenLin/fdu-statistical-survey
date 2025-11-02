# -*- coding: utf-8 -*-
import os, json, random, requests,csv
from dataclasses import dataclass
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import csv
import time
import re
from typing import Dict, List, Tuple, Any
import pandas as pd



# ===================== 你给的 chat_agent（略做小改：支持传模型名） =====================
class chat_agent(object):
    def __init__(self, api_key:str, user_name:str, base_url:str='https://ds-api.yovole.com/v1/', model_id:str='gpt-oss-120b'):
        self.api_key = api_key
        self.base_url = base_url
        self.model_id = model_id
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        self.conversation_history = []
        self.user = user_name

    def chat(self, message):
        url = self.base_url + 'chat/completions'

        # 构造历史：user, assistant, user, ...
        messages = []
        for hist in self.conversation_history:
            messages.append({"role": "user", "content": hist['query']})
            messages.append({"role": "assistant", "content": hist['answer']})
        messages.append({"role": "user", "content": message})

        data = {
            "model": self.model_id,
            "messages": messages,
            "top_p": 0.8,
            "temperature": 1.2,
            "n": 1,
            "max_tokens": 5000,
            "stream": False,
            "frequency_penalty": 1,
            "stop": []
        }

        try:
            for attempt in range(3):
                resp = requests.post(url, headers=self.headers, data=json.dumps(data), timeout=60)

                # 429/5xx → 指数退避后重试
                if resp.status_code in (429, 500, 502, 503, 504):
                    if attempt < 2:
                        time.sleep(1.5 * (2 ** attempt))
                        continue

                # 其它非 200：认为失败
                if resp.status_code != 200:
                    print(f"[API] 状态码: {resp.status_code}\n{resp.text[:500]}",flush=True)
                    return None

                jd = resp.json()
                choices = jd.get("choices", [])
                if not choices:
                    # 没choices当失败
                    return None

                answer_raw = choices[0]["message"]["content"]
                answer_clean = (answer_raw or "").strip()

                # 只有非空回答才写进历史
                if answer_clean:
                    self.conversation_history.append({
                        'query': message,
                        'answer': answer_clean
                    })

                return answer_clean  # 可能是 ""，也可能是 "4" 这类简短答案

            # 三次循环都没成功
            return None

        except Exception as e:
            print(f"[API] 异常: {e}",flush=True)
            return None



    def history(self, number:int = 50):
        return self.conversation_history[-number:]

# ===================== 简单画像采样（极简随机即可跑通） =====================
# ------------ 固定 13 类专业标签（强校验） ------------
MAJOR_KEYS = ["工学","哲学","经济学","法学","教育学","文学","历史学","理学","管理学","农学","医学","军事学","艺术学"]

def _normalize_major(d: Dict[str, float]) -> Dict[str, float]:
    # 将缺失的专业补 0，并归一化；剔除不在 13 类的键（如“公安/行政专门”等）
    v = {k: float(d.get(k, 0.0)) for k in MAJOR_KEYS}
    s = sum(v.values())
    if s <= 0:
        # 极端兜底：若全 0，则给均匀分布
        v = {k: 1.0/len(MAJOR_KEYS) for k in MAJOR_KEYS}
    else:
        v = {k: x/s for k, x in v.items()}
    return v

# ------------ 40 校名单与类型映射（与上一版一致；略） ------------
SCHOOLS = [
    "复旦大学","同济大学","上海交通大学","华东理工大学","上海理工大学","上海海事大学","东华大学","上海电力大学","上海应用技术大学","上海健康医学院",
    "上海海洋大学","上海中医药大学","华东师范大学","上海师范大学","上海外国语大学","上海财经大学","上海对外经贸大学","上海海关学院","华东政法大学","上海体育大学",
    "上海音乐学院","上海戏剧学院","上海大学","上海公安学院","上海工程技术大学","上海立信会计金融学院","上海电机学院","上海政法学院","上海第二工业大学","上海商学院",
    "上海科技大学","上海杉达学院","上海立达学院","上海建桥学院","上海兴伟学院","上海中侨职业技术大学","上海视觉艺术学院","上海外国语大学贤达经济人文学院","上海师范大学天华学院","上海纽约大学"
]

SCHOOL_TO_CATEGORY: Dict[str, str] = {
    "复旦大学": "comprehensive",
    "同济大学": "engineering_heavy",
    "上海交通大学": "engineering_heavy",
    "华东理工大学": "engineering_mixed",
    "上海理工大学": "engineering_mixed",
    "上海海事大学": "maritime",
    "东华大学": "textile_fashion_engineering",
    "上海电力大学": "power_energy",
    "上海应用技术大学": "applied_tech",
    "上海健康医学院": "medical_health",
    "上海海洋大学": "marine_fisheries",
    "上海中医药大学": "tcm_med",
    "华东师范大学": "teacher_comprehensive",
    "上海师范大学": "teacher_comprehensive",
    "上海外国语大学": "foreign_languages",
    "上海财经大学": "finance_econ",
    "上海对外经贸大学": "finance_econ",
    "上海海关学院": "law_admin_special",
    "华东政法大学": "law_politics",
    "上海体育大学": "sports",
    "上海音乐学院": "music",
    "上海戏剧学院": "theatre_film",
    "上海大学": "comprehensive_engineering",
    "上海公安学院": "police_security",
    "上海工程技术大学": "engineering_applied",
    "上海立信会计金融学院": "accounting_finance",
    "上海电机学院": "engineering_applied",
    "上海政法学院": "law_politics",
    "上海第二工业大学": "engineering_applied",
    "上海商学院": "business_management",
    "上海科技大学": "science_tech",
    "上海杉达学院": "private_general",
    "上海立达学院": "private_general",
    "上海建桥学院": "private_general",
    "上海兴伟学院": "private_general_small",
    "上海中侨职业技术大学": "private_vocational",
    "上海视觉艺术学院": "visual_arts",
    "上海外国语大学贤达经济人文学院": "private_affiliated_lang_biz",
    "上海师范大学天华学院": "private_affiliated_teacher",
    "上海纽约大学": "intl_coop_liberal"
}

# ------------ 学校规模 → 学校总体抽样权重（与上一版一致，可保留） ------------
SCHOOL_SIZE_CLASS: Dict[str, str] = {
    "复旦大学": "mega",
    "同济大学": "large",
    "上海交通大学": "mega",
    "华东理工大学": "large",
    "上海理工大学": "medium",
    "上海海事大学": "medium",
    "东华大学": "medium",
    "上海电力大学": "medium",
    "上海应用技术大学": "medium",
    "上海健康医学院": "small",
    "上海海洋大学": "small",
    "上海中医药大学": "small",
    "华东师范大学": "large",
    "上海师范大学": "large",
    "上海外国语大学": "small",
    "上海财经大学": "medium",
    "上海对外经贸大学": "small",
    "上海海关学院": "specialized",
    "华东政法大学": "small",
    "上海体育大学": "specialized",
    "上海音乐学院": "specialized",
    "上海戏剧学院": "specialized",
    "上海大学": "large",
    "上海公安学院": "specialized",
    "上海工程技术大学": "medium",
    "上海立信会计金融学院": "small",
    "上海电机学院": "small",
    "上海政法学院": "small",
    "上海第二工业大学": "small",
    "上海商学院": "small",
    "上海科技大学": "small",
    "上海杉达学院": "small",
    "上海立达学院": "small",
    "上海建桥学院": "small",
    "上海兴伟学院": "specialized",
    "上海中侨职业技术大学": "specialized",
    "上海视觉艺术学院": "specialized",
    "上海外国语大学贤达经济人文学院": "small",
    "上海师范大学天华学院": "small",
    "上海纽约大学": "specialized"
}

SIZE_CLASS_BASE_WEIGHTS = {"mega": 6.0, "large": 4.0, "medium": 2.5, "small": 1.5, "specialized": 0.9}

def get_school_sampling_weights() -> Dict[str, float]:
    raw = {s: SIZE_CLASS_BASE_WEIGHTS[SCHOOL_SIZE_CLASS[s]] for s in SCHOOLS}
    tot = sum(raw.values())
    return {s: round(w/tot, 6) for s, w in raw.items()}

# ------------ 类型先验（修正：专业键只用 13 类；GRADE 改为层次+年级两级后合成 joint） ------------
def _grade_joint(level_share: Dict[str, float],
                 ug_year: Dict[str, float],
                 ms_year: Dict[str, float],
                 phd_year: Dict[str, float]) -> Dict[str, float]:
    """把层次占比 × 各层次数内年级分布 → 合成联合分布（总和=1）"""
    # 归一层次
    ls = {k: max(0.0, float(v)) for k, v in level_share.items()}
    s = sum(ls.values()) or 1.0
    ls = {k: v/s for k, v in ls.items()}
    # 归一年级
    def nz_norm(d):
        t = sum(max(0.0, float(x)) for x in d.values()) or 1.0
        return {k: max(0.0, float(v))/t for k, v in d.items()}
    ug = nz_norm(ug_year); ms = nz_norm(ms_year); phd = nz_norm(phd_year)
    out = {}
    for k, p in ug.items():
        out[f"本科/{k}"] = ls.get("本科",0)*p
    for k, p in ms.items():
        out[f"硕士/{k}"] = ls.get("硕士",0)*p
    for k, p in phd.items():
        out[f"博士/{k}"] = ls.get("博士",0)*p
    # 归一最终 joint
    tot = sum(out.values()) or 1.0
    return {k: v/tot for k, v in out.items()}

CATEGORY_PRIORS: Dict[str, Dict[str, Any]] = {
    "comprehensive": {
        "GENDER": {"男": 0.50, "女": 0.50},
        "LEVEL_SHARE": {"本科": 0.45, "硕士": 0.40, "博士": 0.15},
        "UG_YEAR": {"大一": 0.26, "大二": 0.24, "大三": 0.23, "大四（含大五）": 0.27},
        "MS_YEAR": {"研一": 0.50, "研二": 0.35, "研三": 0.15},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.07, "20–22岁": 0.52, "23–25岁": 0.26, "25岁以上": 0.15},
        "MAJOR": _normalize_major({
            "工学":0.20,"理学":0.17,"医学":0.12,"经济学":0.08,"管理学":0.07,"法学":0.07,
            "文学":0.12,"历史学":0.04,"哲学":0.03,"教育学":0.03,"农学":0.02,"军事学":0.00,"艺术学":0.05
        })
    },
    "engineering_heavy": {
        "GENDER": {"男": 0.64, "女": 0.36},
        "LEVEL_SHARE": {"本科": 0.45, "硕士": 0.38, "博士": 0.17},
        "UG_YEAR": {"大一": 0.26, "大二": 0.24, "大三": 0.23, "大四（含大五）": 0.27},
        "MS_YEAR": {"研一": 0.50, "研二": 0.35, "研三": 0.15},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.06, "20–22岁": 0.48, "23–25岁": 0.30, "25岁以上": 0.16},
        "MAJOR": _normalize_major({
            "工学":0.58,"理学":0.14,"医学":0.05,"经济学":0.05,"管理学":0.07,"法学":0.02,
            "文学":0.03,"艺术学":0.02,"教育学":0.01,"历史学":0.01,"哲学":0.01,"农学":0.01,"军事学":0.00
        })
    },
    "engineering_mixed": {
        "GENDER": {"男": 0.60, "女": 0.40},
        "LEVEL_SHARE": {"本科": 0.52, "硕士": 0.36, "博士": 0.12},
        "UG_YEAR": {"大一": 0.25, "大二": 0.25, "大三": 0.25, "大四（含大五）": 0.25},
        "MS_YEAR": {"研一": 0.50, "研二": 0.35, "研三": 0.15},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.07, "20–22岁": 0.50, "23–25岁": 0.30, "25岁以上": 0.13},
        "MAJOR": _normalize_major({
            "工学":0.50,"理学":0.15,"管理学":0.10,"经济学":0.05,"文学":0.04,"艺术学":0.03,
            "法学":0.03,"教育学":0.02,"历史学":0.01,"哲学":0.01,"医学":0.04,"农学":0.02,"军事学":0.00
        })
    },
    "engineering_applied": {
        "GENDER": {"男": 0.62, "女": 0.38},
        "LEVEL_SHARE": {"本科": 0.60, "硕士": 0.34, "博士": 0.06},
        "UG_YEAR": {"大一": 0.27, "大二": 0.25, "大三": 0.24, "大四（含大五）": 0.24},
        "MS_YEAR": {"研一": 0.52, "研二": 0.33, "研三": 0.15},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.10, "20–22岁": 0.55, "23–25岁": 0.27, "25岁以上": 0.08},
        "MAJOR": _normalize_major({
            "工学":0.62,"理学":0.12,"管理学":0.10,"经济学":0.05,"文学":0.03,"法学":0.03,
            "艺术学":0.02,"教育学":0.01,"历史学":0.00,"哲学":0.00,"医学":0.01,"农学":0.01,"军事学":0.00
        })
    },
    "comprehensive_engineering": {
        "GENDER": {"男": 0.58, "女": 0.42},
        "LEVEL_SHARE": {"本科": 0.50, "硕士": 0.38, "博士": 0.12},
        "UG_YEAR": {"大一": 0.26, "大二": 0.24, "大三": 0.24, "大四（含大五）": 0.26},
        "MS_YEAR": {"研一": 0.50, "研二": 0.35, "研三": 0.15},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.08, "20–22岁": 0.50, "23–25岁": 0.28, "25岁以上": 0.14},
        "MAJOR": _normalize_major({
            "工学":0.45,"理学":0.18,"管理学":0.08,"经济学":0.06,"文学":0.08,"法学":0.05,
            "教育学":0.03,"艺术学":0.04,"历史学":0.01,"哲学":0.01,"医学":0.01,"农学":0.00,"军事学":0.00
        })
    },
    "maritime": {
        "GENDER": {"男": 0.70, "女": 0.30},
        "LEVEL_SHARE": {"本科": 0.62, "硕士": 0.33, "博士": 0.05},
        "UG_YEAR": {"大一": 0.27, "大二": 0.25, "大三": 0.24, "大四（含大五）": 0.24},
        "MS_YEAR": {"研一": 0.50, "研二": 0.35, "研三": 0.15},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.09, "20–22岁": 0.54, "23–25岁": 0.28, "25岁以上": 0.09},
        "MAJOR": _normalize_major({
            "工学":0.65,"管理学":0.10,"经济学":0.05,"理学":0.10,"法学":0.03,"文学":0.02,
            "教育学":0.01,"艺术学":0.01,"历史学":0.00,"哲学":0.00,"医学":0.02,"农学":0.01,"军事学":0.00
        })
    },
    "marine_fisheries": {
        "GENDER": {"男": 0.56, "女": 0.44},
        "LEVEL_SHARE": {"本科": 0.60, "硕士": 0.34, "博士": 0.06},
        "UG_YEAR": {"大一": 0.26, "大二": 0.24, "大三": 0.24, "大四（含大五）": 0.26},
        "MS_YEAR": {"研一": 0.52, "研二": 0.33, "研三": 0.15},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.09, "20–22岁": 0.55, "23–25岁": 0.27, "25岁以上": 0.09},
        "MAJOR": _normalize_major({
            "农学":0.25,"工学":0.25,"理学":0.20,"管理学":0.08,"经济学":0.05,"法学":0.05,
            "文学":0.04,"教育学":0.03,"艺术学":0.02,"历史学":0.01,"哲学":0.01,"医学":0.01,"军事学":0.00
        })
    },
    "textile_fashion_engineering": {
        "GENDER": {"男": 0.52, "女": 0.48},
        "LEVEL_SHARE": {"本科": 0.56, "硕士": 0.38, "博士": 0.06},
        "UG_YEAR": {"大一": 0.26, "大二": 0.24, "大三": 0.24, "大四（含大五）": 0.26},
        "MS_YEAR": {"研一": 0.52, "研二": 0.33, "研三": 0.15},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.09, "20–22岁": 0.55, "23–25岁": 0.27, "25岁以上": 0.09},
        "MAJOR": _normalize_major({
            "工学":0.55,"理学":0.15,"艺术学":0.08,"管理学":0.08,"经济学":0.05,
            "文学":0.04,"法学":0.02,"教育学":0.01,"历史学":0.00,"哲学":0.00,"医学":0.01,"农学":0.01,"军事学":0.00
        })
    },
    "power_energy": {
        "GENDER": {"男": 0.66, "女": 0.34},
        "LEVEL_SHARE": {"本科": 0.60, "硕士": 0.34, "博士": 0.06},
        "UG_YEAR": {"大一": 0.27, "大二": 0.25, "大三": 0.24, "大四（含大五）": 0.24},
        "MS_YEAR": {"研一": 0.52, "研二": 0.33, "研三": 0.15},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.10, "20–22岁": 0.53, "23–25岁": 0.28, "25岁以上": 0.09},
        "MAJOR": _normalize_major({
            "工学":0.68,"理学":0.14,"管理学":0.07,"经济学":0.04,"法学":0.02,"文学":0.02,
            "教育学":0.01,"艺术学":0.01,"历史学":0.00,"哲学":0.00,"医学":0.00,"农学":0.01,"军事学":0.00
        })
    },
    "applied_tech": {
        "GENDER": {"男": 0.58, "女": 0.42},
        "LEVEL_SHARE": {"本科": 0.70, "硕士": 0.27, "博士": 0.03},
        "UG_YEAR": {"大一": 0.28, "大二": 0.25, "大三": 0.24, "大四（含大五）": 0.23},
        "MS_YEAR": {"研一": 0.55, "研二": 0.30, "研三": 0.15},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.12, "20–22岁": 0.58, "23–25岁": 0.24, "25岁以上": 0.06},
        "MAJOR": _normalize_major({
            "工学":0.50,"理学":0.15,"管理学":0.12,"经济学":0.06,"文学":0.05,"法学":0.03,
            "艺术学":0.05,"教育学":0.02,"历史学":0.00,"哲学":0.00,"医学":0.01,"农学":0.01,"军事学":0.00
        })
    },
    "medical_health": {
        "GENDER": {"男": 0.40, "女": 0.60},
        "LEVEL_SHARE": {"本科": 0.55, "硕士": 0.35, "博士": 0.10},
        "UG_YEAR": {"大一": 0.22, "大二": 0.24, "大三": 0.24, "大四（含大五）": 0.30},
        "MS_YEAR": {"研一": 0.45, "研二": 0.35, "研三": 0.20},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.06, "20–22岁": 0.46, "23–25岁": 0.33, "25岁以上": 0.15},
        "MAJOR": _normalize_major({
            "医学":0.70,"理学":0.08,"管理学":0.07,"经济学":0.04,"法学":0.03,"文学":0.03,
            "教育学":0.02,"艺术学":0.01,"历史学":0.00,"哲学":0.00,"工学":0.01,"农学":0.01,"军事学":0.00
        })
    },
    "tcm_med": {
        "GENDER": {"男": 0.42, "女": 0.58},
        "LEVEL_SHARE": {"本科": 0.56, "硕士": 0.34, "博士": 0.10},
        "UG_YEAR": {"大一": 0.23, "大二": 0.24, "大三": 0.24, "大四（含大五）": 0.29},
        "MS_YEAR": {"研一": 0.46, "研二": 0.36, "研三": 0.18},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.07, "20–22岁": 0.48, "23–25岁": 0.34, "25岁以上": 0.11},
        "MAJOR": _normalize_major({
            "医学":0.62,"理学":0.10,"管理学":0.08,"经济学":0.04,"法学":0.03,"文学":0.06,
            "教育学":0.03,"艺术学":0.02,"历史学":0.01,"哲学":0.01,"工学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "teacher_comprehensive": {
        "GENDER": {"男": 0.38, "女": 0.62},
        "LEVEL_SHARE": {"本科": 0.52, "硕士": 0.40, "博士": 0.08},
        "UG_YEAR": {"大一": 0.25, "大二": 0.25, "大三": 0.25, "大四（含大五）": 0.25},
        "MS_YEAR": {"研一": 0.50, "研二": 0.35, "研三": 0.15},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.08, "20–22岁": 0.55, "23–25岁": 0.26, "25岁以上": 0.11},
        "MAJOR": _normalize_major({
            "教育学":0.22,"文学":0.20,"理学":0.20,"管理学":0.08,"法学":0.06,"经济学":0.06,
            "历史学":0.06,"哲学":0.04,"工学":0.04,"艺术学":0.04,"医学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "foreign_languages": {
        "GENDER": {"男": 0.25, "女": 0.75},
        "LEVEL_SHARE": {"本科": 0.55, "硕士": 0.38, "博士": 0.07},
        "UG_YEAR": {"大一": 0.25, "大二": 0.25, "大三": 0.25, "大四（含大五）": 0.25},
        "MS_YEAR": {"研一": 0.52, "研二": 0.35, "研三": 0.13},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.09, "20–22岁": 0.58, "23–25岁": 0.25, "25岁以上": 0.08},
        "MAJOR": _normalize_major({
            "文学":0.70,"管理学":0.08,"经济学":0.07,"法学":0.05,"教育学":0.03,"艺术学":0.03,
            "理学":0.02,"历史学":0.01,"哲学":0.01,"工学":0.00,"医学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "finance_econ": {
        "GENDER": {"男": 0.45, "女": 0.55},
        "LEVEL_SHARE": {"本科": 0.52, "硕士": 0.42, "博士": 0.06},
        "UG_YEAR": {"大一": 0.25, "大二": 0.25, "大三": 0.25, "大四（含大五）": 0.25},
        "MS_YEAR": {"研一": 0.52, "研二": 0.35, "研三": 0.13},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.08, "20–22岁": 0.56, "23–25岁": 0.27, "25岁以上": 0.09},
        "MAJOR": _normalize_major({
            "经济学":0.45,"管理学":0.35,"法学":0.08,"理学":0.04,"文学":0.03,"艺术学":0.02,
            "教育学":0.01,"工学":0.01,"历史学":0.00,"哲学":0.00,"医学":0.00,"农学":0.01,"军事学":0.00
        })
    },
    "law_politics": {
        "GENDER": {"男": 0.46, "女": 0.54},
        "LEVEL_SHARE": {"本科": 0.52, "硕士": 0.42, "博士": 0.06},
        "UG_YEAR": {"大一": 0.25, "大二": 0.25, "大三": 0.25, "大四（含大五）": 0.25},
        "MS_YEAR": {"研一": 0.52, "研二": 0.35, "研三": 0.13},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.08, "20–22岁": 0.54, "23–25岁": 0.28, "25岁以上": 0.10},
        "MAJOR": _normalize_major({
            "法学":0.60,"管理学":0.12,"经济学":0.10,"文学":0.08,"教育学":0.03,"历史学":0.03,
            "哲学":0.02,"艺术学":0.01,"理学":0.01,"工学":0.00,"医学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "sports": {
        "GENDER": {"男": 0.55, "女": 0.45},
        "LEVEL_SHARE": {"本科": 0.65, "硕士": 0.30, "博士": 0.05},
        "UG_YEAR": {"大一": 0.26, "大二": 0.25, "大三": 0.25, "大四（含大五）": 0.24},
        "MS_YEAR": {"研一": 0.55, "研二": 0.30, "研三": 0.15},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.10, "20–22岁": 0.58, "23–25岁": 0.24, "25岁以上": 0.08},
        "MAJOR": _normalize_major({
            "教育学":0.10,"管理学":0.10,"文学":0.05,"艺术学":0.10,"法学":0.05,"理学":0.05,
            "工学":0.05,"经济学":0.05,"医学":0.40,"历史学":0.03,"哲学":0.02,"农学":0.00,"军事学":0.00
        })
    },
    "music": {
        "GENDER": {"男": 0.45, "女": 0.55},
        "LEVEL_SHARE": {"本科": 0.70, "硕士": 0.28, "博士": 0.02},
        "UG_YEAR": {"大一": 0.26, "大二": 0.25, "大三": 0.25, "大四（含大五）": 0.24},
        "MS_YEAR": {"研一": 0.52, "研二": 0.35, "研三": 0.13},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.10, "20–22岁": 0.60, "23–25岁": 0.24, "25岁以上": 0.06},
        "MAJOR": _normalize_major({
            "艺术学":0.80,"文学":0.06,"管理学":0.05,"教育学":0.05,"法学":0.02,"经济学":0.01,
            "理学":0.01,"工学":0.00,"医学":0.00,"历史学":0.00,"哲学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "theatre_film": {
        "GENDER": {"男": 0.45, "女": 0.55},
        "LEVEL_SHARE": {"本科": 0.70, "硕士": 0.28, "博士": 0.02},
        "UG_YEAR": {"大一": 0.26, "大二": 0.25, "大三": 0.25, "大四（含大五）": 0.24},
        "MS_YEAR": {"研一": 0.52, "研二": 0.35, "研三": 0.13},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.10, "20–22岁": 0.58, "23–25岁": 0.26, "25岁以上": 0.06},
        "MAJOR": _normalize_major({
            "艺术学":0.75,"文学":0.08,"管理学":0.06,"教育学":0.04,"法学":0.03,"经济学":0.02,
            "理学":0.01,"工学":0.01,"医学":0.00,"历史学":0.00,"哲学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "police_security": {
        "GENDER": {"男": 0.70, "女": 0.30},
        "LEVEL_SHARE": {"本科": 0.80, "硕士": 0.18, "博士": 0.02},
        "UG_YEAR": {"大一": 0.27, "大二": 0.25, "大三": 0.24, "大四（含大五）": 0.24},
        "MS_YEAR": {"研一": 0.50, "研二": 0.35, "研三": 0.15},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.12, "20–22岁": 0.60, "23–25岁": 0.22, "25岁以上": 0.06},
        # 关键修正：不再使用“公安/行政专门”自定义标签，折算回 13 类
        "MAJOR": _normalize_major({
            "法学":0.45,"管理学":0.15,"文学":0.08,"教育学":0.05,"经济学":0.05,"理学":0.08,
            "工学":0.10,"艺术学":0.02,"历史学":0.01,"哲学":0.01,"医学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "accounting_finance": {
        "GENDER": {"男": 0.45, "女": 0.55},
        "LEVEL_SHARE": {"本科": 0.62, "硕士": 0.35, "博士": 0.03},
        "UG_YEAR": {"大一": 0.26, "大二": 0.25, "大三": 0.25, "大四（含大五）": 0.24},
        "MS_YEAR": {"研一": 0.52, "研二": 0.35, "研三": 0.13},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.10, "20–22岁": 0.58, "23–25岁": 0.25, "25岁以上": 0.07},
        "MAJOR": _normalize_major({
            "管理学":0.46,"经济学":0.40,"法学":0.06,"文学":0.03,"教育学":0.01,"艺术学":0.01,
            "理学":0.02,"工学":0.01,"历史学":0.00,"哲学":0.00,"医学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "business_management": {
        "GENDER": {"男": 0.48, "女": 0.52},
        "LEVEL_SHARE": {"本科": 0.65, "硕士": 0.32, "博士": 0.03},
        "UG_YEAR": {"大一": 0.27, "大二": 0.25, "大三": 0.24, "大四（含大五）": 0.24},
        "MS_YEAR": {"研一": 0.52, "研二": 0.33, "研三": 0.15},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.11, "20–22岁": 0.58, "23–25岁": 0.25, "25岁以上": 0.06},
        "MAJOR": _normalize_major({
            "管理学":0.55,"经济学":0.30,"法学":0.05,"文学":0.04,"教育学":0.01,"艺术学":0.02,
            "理学":0.02,"工学":0.01,"历史学":0.00,"哲学":0.00,"医学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "law_admin_special": {
        "GENDER": {"男": 0.55, "女": 0.45},
        "LEVEL_SHARE": {"本科": 0.70, "硕士": 0.28, "博士": 0.02},
        "UG_YEAR": {"大一": 0.27, "大二": 0.25, "大三": 0.24, "大四（含大五）": 0.24},
        "MS_YEAR": {"研一": 0.50, "研二": 0.35, "研三": 0.15},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.11, "20–22岁": 0.57, "23–25岁": 0.25, "25岁以上": 0.07},
        "MAJOR": _normalize_major({
            "法学":0.45,"管理学":0.20,"经济学":0.20,"文学":0.05,"教育学":0.03,"理学":0.03,
            "工学":0.02,"艺术学":0.01,"历史学":0.00,"哲学":0.01,"医学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "science_tech": {
        "GENDER": {"男": 0.60, "女": 0.40},
        "LEVEL_SHARE": {"本科": 0.40, "硕士": 0.45, "博士": 0.15},
        "UG_YEAR": {"大一": 0.26, "大二": 0.24, "大三": 0.24, "大四（含大五）": 0.26},
        "MS_YEAR": {"研一": 0.50, "研二": 0.35, "研三": 0.15},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.08, "20–22岁": 0.50, "23–25岁": 0.30, "25岁以上": 0.12},
        "MAJOR": _normalize_major({
            "理学":0.40,"工学":0.40,"管理学":0.06,"经济学":0.04,"文学":0.03,"法学":0.03,
            "教育学":0.02,"艺术学":0.01,"历史学":0.00,"哲学":0.01,"医学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "private_general": {
        "GENDER": {"男": 0.52, "女": 0.48},
        "LEVEL_SHARE": {"本科": 0.85, "硕士": 0.14, "博士": 0.01},
        "UG_YEAR": {"大一": 0.29, "大二": 0.26, "大三": 0.24, "大四（含大五）": 0.21},
        "MS_YEAR": {"研一": 0.60, "研二": 0.28, "研三": 0.12},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.14, "20–22岁": 0.62, "23–25岁": 0.20, "25岁以上": 0.04},
        "MAJOR": _normalize_major({
            "管理学":0.28,"经济学":0.22,"工学":0.22,"文学":0.12,"法学":0.06,"艺术学":0.06,
            "教育学":0.02,"理学":0.02,"历史学":0.00,"哲学":0.00,"医学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "private_general_small": {
        "GENDER": {"男": 0.52, "女": 0.48},
        "LEVEL_SHARE": {"本科": 0.90, "硕士": 0.09, "博士": 0.01},
        "UG_YEAR": {"大一": 0.30, "大二": 0.26, "大三": 0.24, "大四（含大五）": 0.20},
        "MS_YEAR": {"研一": 0.62, "研二": 0.26, "研三": 0.12},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.16, "20–22岁": 0.62, "23–25岁": 0.18, "25岁以上": 0.04},
        "MAJOR": _normalize_major({
            "管理学":0.30,"经济学":0.25,"工学":0.18,"文学":0.12,"法学":0.06,"艺术学":0.06,
            "教育学":0.02,"理学":0.01,"历史学":0.00,"哲学":0.00,"医学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "private_vocational": {
        "GENDER": {"男": 0.55, "女": 0.45},
        "LEVEL_SHARE": {"本科": 0.95, "硕士": 0.04, "博士": 0.01},
        "UG_YEAR": {"大一": 0.32, "大二": 0.28, "大三": 0.24, "大四（含大五）": 0.16},
        "MS_YEAR": {"研一": 0.65, "研二": 0.23, "研三": 0.12},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.20, "20–22岁": 0.60, "23–25岁": 0.17, "25岁以上": 0.03},
        "MAJOR": _normalize_major({
            "管理学":0.30,"经济学":0.20,"工学":0.30,"文学":0.08,"法学":0.05,"艺术学":0.05,
            "教育学":0.01,"理学":0.01,"历史学":0.00,"哲学":0.00,"医学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "private_affiliated_lang_biz": {
        "GENDER": {"男": 0.40, "女": 0.60},
        "LEVEL_SHARE": {"本科": 0.88, "硕士": 0.11, "博士": 0.01},
        "UG_YEAR": {"大一": 0.28, "大二": 0.26, "大三": 0.24, "大四（含大五）": 0.22},
        "MS_YEAR": {"研一": 0.58, "研二": 0.30, "研三": 0.12},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.14, "20–22岁": 0.62, "23–25岁": 0.20, "25岁以上": 0.04},
        "MAJOR": _normalize_major({
            "文学":0.40,"管理学":0.22,"经济学":0.20,"法学":0.07,"艺术学":0.05,"教育学":0.03,
            "理学":0.02,"工学":0.01,"历史学":0.00,"哲学":0.00,"医学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "private_affiliated_teacher": {
        "GENDER": {"男": 0.38, "女": 0.62},
        "LEVEL_SHARE": {"本科": 0.88, "硕士": 0.11, "博士": 0.01},
        "UG_YEAR": {"大一": 0.28, "大二": 0.26, "大三": 0.24, "大四（含大五）": 0.22},
        "MS_YEAR": {"研一": 0.58, "研二": 0.30, "研三": 0.12},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.14, "20–22岁": 0.62, "23–25岁": 0.20, "25岁以上": 0.04},
        "MAJOR": _normalize_major({
            "教育学":0.30,"文学":0.26,"管理学":0.12,"经济学":0.10,"艺术学":0.08,"法学":0.06,
            "理学":0.05,"工学":0.02,"历史学":0.01,"哲学":0.00,"医学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "visual_arts": {
        "GENDER": {"男": 0.46, "女": 0.54},
        "LEVEL_SHARE": {"本科": 0.78, "硕士": 0.20, "博士": 0.02},
        "UG_YEAR": {"大一": 0.27, "大二": 0.25, "大三": 0.25, "大四（含大五）": 0.23},
        "MS_YEAR": {"研一": 0.55, "研二": 0.32, "研三": 0.13},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.12, "20–22岁": 0.58, "23–25岁": 0.24, "25岁以上": 0.06},
        "MAJOR": _normalize_major({
            "艺术学":0.78,"文学":0.06,"管理学":0.06,"教育学":0.04,"法学":0.02,"经济学":0.02,
            "理学":0.01,"工学":0.01,"历史学":0.00,"哲学":0.00,"医学":0.00,"农学":0.00,"军事学":0.00
        })
    },
    "intl_coop_liberal": {
        "GENDER": {"男": 0.48, "女": 0.52},
        "LEVEL_SHARE": {"本科": 0.52, "硕士": 0.42, "博士": 0.06},
        "UG_YEAR": {"大一": 0.25, "大二": 0.25, "大三": 0.25, "大四（含大五）": 0.25},
        "MS_YEAR": {"研一": 0.52, "研二": 0.35, "研三": 0.13},
        "PHD_YEAR": {"博士": 1.00},
        "AGE": {"20岁以下": 0.10, "20–22岁": 0.55, "23–25岁": 0.27, "25岁以上": 0.08},
        "MAJOR": _normalize_major({
            "文学":0.28,"理学":0.20,"工学":0.12,"管理学":0.14,"经济学":0.12,"法学":0.06,
            "教育学":0.03,"艺术学":0.04,"历史学":0.00,"哲学":0.01,"医学":0.00,"农学":0.00,"军事学":0.00
        })
    }
}

def _build_grade_joint_for_category(cat: str) -> Dict[str, float]:
    c = CATEGORY_PRIORS[cat]
    return _grade_joint(c["LEVEL_SHARE"], c["UG_YEAR"], c["MS_YEAR"], c["PHD_YEAR"])

def get_school_profile_weights(school: str) -> Dict[str, Any]:
    """返回指定学校的画像抽样权重：
       - GENDER: {"男":p, "女":p}
       - AGE: {"20岁以下":p, "20–22岁":p, "23–25岁":p, "25岁以上":p}
       - MAJOR: 13 类（已经规范化）
       - GRADE_JOINT: {"本科/大一":p, ..., "硕士/研一":p, ..., "博士/博士":p}
    """
    cat = SCHOOL_TO_CATEGORY[school]
    pri = CATEGORY_PRIORS[cat]
    return {
        "GENDER": pri["GENDER"],
        "AGE": pri["AGE"],
        "MAJOR": pri["MAJOR"],  # 已经标准化为 13 类
        "GRADE_JOINT": _build_grade_joint_for_category(cat)
    }
# ============== 工具函数：按权重采样 ==============
def choice_from_weights(d: Dict[str, float]) -> str:
    keys = list(d.keys())
    weights = list(d.values())
    return random.choices(keys, weights=weights, k=1)[0]

def map_grade_joint_to_label(grade_joint_key: str) -> str:
    if "/" in grade_joint_key:
        _, year = grade_joint_key.split("/", 1)
        return year
    return grade_joint_key

# ============== 画像采样（按学校→类型先验） ==============
def sample_profile() -> Dict[str, str]:
    """
    随机生成画像（性别、年级、年龄、专业、学校）：
    - 学校按 get_school_sampling_weights() 权重抽；
    - 其它四项来自该校的类型先验（含“学历×年级联合分布”）。
    """
    # 1) 学校（总体抽样权重）
    school_weights = get_school_sampling_weights()
    school_list = list(school_weights.keys())
    school_prob = list(school_weights.values())
    school = random.choices(school_list, weights=school_prob, k=1)[0]

    # 2) 四类分布：GENDER / AGE / MAJOR / GRADE_JOINT
    prof_w = get_school_profile_weights(school)
    gender = choice_from_weights(prof_w["GENDER"])
    age    = choice_from_weights(prof_w["AGE"])

    majors = prof_w["MAJOR"]
    assert set(majors.keys()) == set(MAJOR_KEYS), "专业分布必须严格为 13 类"
    major  = choice_from_weights(majors)

    grade_joint_key = choice_from_weights(prof_w["GRADE_JOINT"])
    grade = map_grade_joint_to_label(grade_joint_key)

    return {
        "gender": gender,
        "grade":  grade,
        "age":    age,
        "major":  major,
        "school": school,
    }

def persona_intro(profile: dict) -> str:
    return f"""你将被要求预测人们对不同信息的反应。社会科学家经常通过在线问卷来进行此类研究。你是一个性别为{profile['gender']}、就读年级为{profile['grade']}、年龄为{profile['age']}岁、专业为{profile['major']}、学校为{profile['school']}的大学生受访者。请回答这份《上海市大学生微短剧观看与付费行为调查》问卷，且全程只用中文、每题仅按要求输出答案。
【作答总规则】
1) 选择题只输出选项字母（如 A 或 A,C），不附加文本。
2) 量表题只输出 1~5 中的一个数字。
3) 开放题用 1-2 句简短中文作答，不加编号。
接下来，请严格按照作答总规则与每题的作答格式要求，逐题完整回答问卷内容。"""

# ===================== 问卷（用列表构造，代码更短） =====================
@dataclass
class QItem:
    qid: str
    text: str
    qtype: str  # 'single' | 'multi' | 'likert5' | 'school' | 'open_short' | 'open_long'

def hint(qtype:str) -> str:
    return {
        "single": "【作答格式】该题目为单选题，只回答一个大写字母（如 A）。",
        "multi": "【作答格式】该题目为多选题，可以回答若干个大写字母，用英文逗号分隔（如 A,C,F）。",
        "likert5": "【作答格式】该题目为量表，请回答一个1-5之间的数字（1=非常不符合，2=不太符合，3=一般，4=比较符合，5=非常符合）。",
        "school": "【作答格式】只输出你的院校全称，必须与画像完全一致。",
        "open_short": "【作答格式】1 句中文（≤30 字）。",
        "open_long": "【作答格式】1–2 句中文（≤60 字）。",
    }[qtype]

PART2_ITEMS = [
 "微短剧平台推送的内容很符合我的兴趣",
 "微短剧平台操作方便、播放流畅",
 "微短剧平台的弹幕、评论等互动功能很活跃",
 "微短剧剧情反转多、“爽点”密集",
 "微短剧的演员表现、画面质量等制作水平高",
 "微短剧的题材新颖、符合我的喜好",
 "微短剧单部更新快、上新数量多",
 "微短剧广告解锁的时长在我可接受范围内",
 "微短剧单集价格或者周月卡价格在我可接受范围内",
 "相比直接付费，我更愿意通过看广告解锁微短剧内容",
 "微短剧平台的促销活动很有吸引力",
 "我常在社交媒体上看到微短剧相关的热门内容",
 "同学、朋友经常推荐我观看微短剧",
 "我所在的社交平台群里常讨论微短剧",
]

PART3_ITEMS = [
 "观看微短剧能满足我的休闲娱乐需求",
 "微短剧平台的操作对我来说很容易",
 "当朋友、同学、网红等都在看微短剧，我也愿意去看",
 "观看微短剧需要的设备、时间、网络我都能满足",
 "观看微短剧能让我感到愉悦、有“爽”感",
 "当我需要娱乐时，我习惯性地自动打开微短剧观看",
 "微短剧带来的体验值得我观看广告进行剧集解锁",
 "微短剧带来的体验值得我付费进行解锁",
]

QUESTIONS: list[QItem] = [
    QItem("1.1","您的性别（单选）：A 男  B 女","single"),
    QItem("1.2","您的年级（单选）：A 大一  B 大二  C 大三  D 大四（含五年制大五）  E 研一  F 研二  G 研三  H 博士","single"),
    QItem("1.3","您的年龄（单选）：A 20岁以下  B 20–22岁  C 23–25岁  D 25岁以上","single"),
    QItem("1.4","您的专业（单选）：A 工学  B 哲学  C 经济学  D 法学  E 教育学  F 文学  G 历史学  H 理学  I 管理学  J 农学  K 医学  L 军事学  M 艺术学","single"),
    QItem("1.5","您所在的院校：请输出你的学校全称","school"),
    QItem("1.6","您是否观看过微短剧？A 是  B 否","single"),
]
# 2.x / 3.x（likert）
for i, s in enumerate(PART2_ITEMS, start=1):
    QUESTIONS.append(QItem(f"2.{i}", s, "likert5"))
for i, s in enumerate(PART3_ITEMS, start=1):
    QUESTIONS.append(QItem(f"3.{i}", s, "likert5"))
# 4.x（行为题）
QUESTIONS.extend([
    QItem("4.1","未来继续观看意愿：A 非常不愿意  B 不太愿意  C 一般  D 比较愿意  E 非常愿意","single"),
    QItem("4.2","平均每周时长：A 1小时以内  B 1–3小时  C 3–5小时  D 5–8小时  E 8小时以上","single"),
    QItem("4.3","观看频率：A 几乎每天  B 每周3–5次  C 每周1–2次  D 每月1–2次  E 偶尔","single"),
    QItem("4.4","主要观看平台（多选）：A 抖音  B 快手  C 番茄短剧  D 微信视频号  E 哔哩哔哩  F 腾讯短剧  G 爱奇艺短剧  H 优酷短剧  I 星芽短剧  J 河马剧场  K 其他","multi"),
    QItem("4.5","偏好题材（多选）：A 甜宠恋爱  B 复仇逆袭  C 校园生活  D 悬疑推理  E 家庭伦理  F 其他","multi"),
    QItem("4.6","发现途径（多选）：A 平台算法推荐  B 朋友/同学推荐  C 社交平台种草  D 广告推广  E 其他","multi"),
    QItem("4.7","未来愿意广告解锁：A 非常不可能  B 不太可能  C 一般  D 比较可能  E 非常可能","single"),
    QItem("4.8","每周广告解锁次数：A 0次  B 1–3次  C 4–6次  D 7–10次  E 10次以上","single"),
    QItem("4.9","选广告解锁主因（多选）：A 节省开支  B 广告时长可接受  C 仅偶尔观看  D 不反感广告内容  E 其他","multi"),
    QItem("4.10","未来愿意付费：A 非常不可能  B 不太可能  C 一般  D 比较可能  E 非常可能","single"),
    QItem("4.11","过去一月付费总额：A 0元  B 1–10元  C 11–25元  D 26–50元  E 50元以上","single"),
    QItem("4.12","选择付费主因：A 不想看广告  B 想快速解锁  C 内容质量高  D 会员权益丰富  E 其他","single"),
    QItem("4.13","广告解锁 vs 直接付费：A 优先广告解锁  B 优先直接付费  C 看情况  D 放弃观看","single"),
])
# 5.x（开放题）
QUESTIONS.extend([
    QItem("5.1","你对校园题材微短剧有哪些期待？","open_short"),
    QItem("5.2","你认为微短剧平台需要哪些改进，才能更吸引大学生？","open_long"),
])

def mk_user_prompt(q: QItem) -> str:
    return (
        f"[题目] {q.qid} {q.text}\n"
        f"{hint(q.qtype)}\n"
        "请只输出最终答案本身，不要解释，不要复述题干，不要说其他任何话。"
    )


def watched_from(ans: str) -> bool:
    s = (ans or '').strip().upper()
    if s in {"A","是","Y","YES"}: return True
    if s in {"B","否","N","NO"}:  return False
    # 容错：包含“是”或首字母 A 视为 True
    if "是" in s or (s and s[0]=="A"): return True
    if "否" in s or (s and s[0]=="B"): return False
    return True

def ask_with_retry(client: chat_agent, prompt: str, max_attempts: int = 3) -> str:
    """
    向同一个 client 连续尝试问同一题，最多 max_attempts 次。
    只要拿到非空答案就返回；否则最后返回空字符串 ""。
    非空答案会在 chat_agent.chat 内部被写入 conversation_history；
    空答案不会污染 conversation_history。
    """
    for _ in range(max_attempts):
        ans = client.chat(prompt)
        if ans is not None:
            cleaned = ans.strip()
            if cleaned != "":
                return cleaned
    # 全部尝试后还是没拿到，就给空串
    return ""

# ===================== 运行一次完整“受访者访谈” =====================
def run_one_interview(api_key: str, model_id: str = "gpt-oss-120b", seed: int = None):
    profile = sample_profile()
    print(profile,flush=True)
    client  = chat_agent(api_key=api_key, user_name="survey-bot", model_id=model_id)

    # 回合 0：画像与规则提示（建立对话记忆）
    hello = client.chat(persona_intro(profile))
    # 逐题
    qa, transcript_lines, seen_watch = [], [], None
    for q in QUESTIONS:
        # 分支：未看过则跳过 2.x / 3.x / 4.x
        if seen_watch is False and (q.qid.startswith("2.") or q.qid.startswith("3.") or q.qid.startswith("4.")):
            continue

        prompt = mk_user_prompt(q)
        ans = ask_with_retry(client, prompt, max_attempts=3)

        qa.append({
            "qid": q.qid,
            "type": q.qtype,
            "question": q.text,
            "answer": ans
        })

        transcript_lines.append(f"Question: {q.qid} {q.text}")
        transcript_lines.append(f"Answer: {ans}")

        if q.qid == "1.6":
            seen_watch = watched_from(ans)


    transcript = "\n".join(transcript_lines)

    # 打印结果
    print(f"\n===== 访谈完成 | {profile['school']} | {profile['grade']} | {profile['gender']} =====",flush=True)
    print(transcript,flush=True)
    print("===== END =====\n",flush=True)

    # 返回结构，便于你保存
    return {
        "profile": profile,
        "qa": qa,
        "transcript": transcript,
        "model": model_id,
    }
def run_batch(
    n: int,
    api_key: str,
    model_id: str = "gpt-oss-120b",
    start_seed: int | None = None,
    out_dir: str = "outputs",
    save_each_txt: bool = True,
):
    os.makedirs(out_dir, exist_ok=True)
    records = []
    base_seed = start_seed if start_seed is not None else random.randint(1, 10**9)

    for i in range(n):
        rec = run_one_interview(api_key, model_id=model_id, seed=base_seed + i)
        rec["created"] = datetime.now().isoformat(timespec="seconds")
        records.append(rec)

        # 每个受访者各自保存一个 transcript（便于快速查看）
        if save_each_txt:
            with open(os.path.join(out_dir, f"interview_{i+1:04d}.txt"), "w", encoding="utf-8") as f:
                f.write(rec["transcript"])

    # 汇总保存：NDJSON（每行一个完整对象，最通用）
    ndjson_path = os.path.join(out_dir, "interviews.ndjson")
    with open(ndjson_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 简单 CSV（画像 + transcript 摘要；后续要更细粒度可以再扩展）
    csv_path = os.path.join(out_dir, "interviews.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["created","model","gender","grade","age","major","school","transcript"])
        for r in records:
            p = r["profile"]
            w.writerow([
                r.get("created"), r.get("model"),
                p["gender"], p["grade"], p["age"], p["major"], p["school"],
                r["transcript"].replace("\n", " / ")
            ])

    print(f"[DONE] Collected {len(records)} interviews",flush=True)
    print(f"NDJSON: {ndjson_path}",flush=True)
    print(f"CSV:    {csv_path}",flush=True)
    return records
def run_batch_parallel(
    n: int,
    api_key: str,
    model_id: str = "gpt-oss-120b",
    concurrency: int = 8,
    start_seed: int | None = None,
    out_dir: str = "outputs",
    save_each_txt: bool = True,
):
    os.makedirs(out_dir, exist_ok=True)
    base_seed = start_seed if start_seed is not None else random.randint(1, 10**9)

    def _worker(i: int):
        # 每个受访者一个独立会话与随机种子
        return i, run_one_interview(api_key, model_id=model_id, seed=base_seed + i)

    records = [None] * n
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(_worker, i) for i in range(n)]
        for fut in as_completed(futures):
            idx, rec = fut.result()
            # 可选：边跑边落地方便观察
            if save_each_txt:
                with open(os.path.join(out_dir, f"interview_{idx+1:04d}.txt"), "w", encoding="utf-8") as f:
                    f.write(rec["transcript"])
            rec["created"] = datetime.now().isoformat(timespec="seconds")
            records[idx] = rec

    # —— 统一落盘（主线程串行写文件，避免竞争）——
    ndjson_path = os.path.join(out_dir, "interviews.ndjson")
    with open(ndjson_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    csv_path = os.path.join(out_dir, "interviews.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["created","model","gender","grade","age","major","school","transcript"])
        for r in records:
            p = r["profile"]
            w.writerow([
                r["created"], r["model"],
                p["gender"], p["grade"], p["age"], p["major"], p["school"],
                r["transcript"].replace("\n", " / ")
            ])

    print(f"[DONE] Collected {len(records)} interviews in parallel",flush=True)
    print(f"NDJSON: {ndjson_path}",flush=True)
    print(f"CSV:    {csv_path}",flush=True)
    return records

def load_interviews(ndjson_path: str):
    respondents = []  # list of dicts, one per respondent
    qa_pairs=[]

    with open(ndjson_path, "r", encoding="utf-8") as f:
        id=0
        for line in f:
            id+=1
            line = line.strip()
            if not line:
                continue  # 跳过空行
            record = json.loads(line)  # 这一行 -> dict
            

            profile = record.get("profile", {})
            qa_list = record.get("qa", [])
            model_id = record.get("model", None)
            created  = record.get("created", None)
            transcript_str = record.get("transcript", "")
            print(id,profile)
            if "sorry" in transcript_str.lower():
                print('skip',profile)
                continue  # 跳过包含“sorry”的记录（可能未完成）
            # 把 qa_list 转成 {qid: answer}
            answers_by_qid = { item["qid"]: item.get("answer","") for item in qa_list }
            answers_by_qid['id']=id

            respondents.append(record)
            qa_pairs.append(answers_by_qid)
            # break

    return respondents,qa_pairs


if __name__ == "__main__":
    API_KEY = os.getenv("YOVOLE_API_KEY", "sk-qGPvtEBthIIULdhf61A9D2AfC09244B0809e2a2547A69dE1")  # 建议用环境变量
    MODEL_ID = os.getenv("YOVOLE_MODEL_ID", "gpt-oss-120b")
    N = int(os.getenv("N_RESPONDENTS", "1000"))
    CC = int(os.getenv("CONCURRENCY",  "10"))        # 并行度
    # run_one_interview(API_KEY, model_id=os.getenv("YOVOLE_MODEL_ID","gpt-oss-120b"), seed=20251102)

    # run_batch(
    #     n=N,
    #     api_key=API_KEY,
    #     model_id=MODEL_ID,
    #     start_seed=20251102,      # 固定基准种子，结果可复现；去掉则随机
    #     out_dir="outputs",
    #     save_each_txt=True,
    # )
    
    run_batch_parallel(
        n=N,
        api_key=API_KEY,
        model_id=MODEL_ID,
        concurrency=CC,
        start_seed=20251102,       # 固定基准种子以便复现；去掉则随机
        out_dir="outputs",
        save_each_txt=True,
    )
    resp,qa_pairs = load_interviews("outputs/interviews.ndjson")
    df=pd.DataFrame(qa_pairs)
    # 假设 df 已经存在，并且 df['id'] 已经有内容
    
    cols = df.columns.tolist()      # 当前所有列名按顺序拿出来
    if 'id' in cols:
        cols.remove('id')           # 先把 'id' 从原来的位置拿掉
        new_cols = ['id'] + cols    # 把它放到列表最前面
        df = df[new_cols]           # 重新按这个顺序重排列
    
    # 现在 df 里第一列就是 'id'，而且内容都是原来那列的内容
    
    df.to_csv("interviews_qa.csv",index=False,encoding="utf-8")
    with open("resp.json", "w", encoding="utf-8") as f:
      json.dump(resp, f, ensure_ascii=False, indent=2)
