"""
generate_ppt.py - 基于模板、关键帧和转录文本生成 PPT

功能：
1. 加载 PPT 模板
2. 每张 slide = 一个关键帧截图 + 对应时间段的文字摘要
3. 添加总结页、Q&A 汇总页

用法：
    python generate_ppt.py --frames-dir frames/ --transcript transcript.json \
        --template template.pptx --output output.pptx
"""

import argparse
import json
import os
import sys
from pathlib import Path
import re
import urllib.parse
import urllib.request

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.enum.shapes import MSO_SHAPE_TYPE
except ImportError:
    print("Error: python-pptx not installed. Run: pip install python-pptx")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("Warning: Pillow not installed. Image sizing may be suboptimal.")
    Image = None


def format_timestamp(seconds):
    """格式化时间戳"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def truncate_text(text, max_chars=300):
    """截断文本"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3] + "..."


def clip_at_boundary(text, max_chars):
    """在词/标点边界处截断，避免在单词中间切断导致半句话"""
    s = (text or "").strip()
    if len(s) <= max_chars:
        return s
    cut = s[:max_chars]
    for sep in ["。", "；", "，", "; ", ", ", " "]:
        idx = cut.rfind(sep)
        if idx >= max_chars * 0.55:
            return cut[:idx].rstrip(" ,，;；、") + "…"
    return cut.rstrip() + "…"


def split_sentences(text):
    """按中英文标点切句"""
    if not text:
        return []
    return [s.strip() for s in re.split(r'(?<=[。！？?.])\s*', text) if s.strip()]


def has_cjk(text):
    """检测是否包含中文字符"""
    return any('\u4e00' <= ch <= '\u9fff' for ch in (text or ""))


def fallback_translate_en_to_zh(text):
    """离线兜底翻译：常见词替换，保证最差情况下也有中英对照结构"""
    if not text:
        return ""
    result = text
    replacements = [
        ("important", "重要"),
        ("key", "关键"),
        ("summary", "总结"),
        ("question", "问题"),
        ("answer", "回答"),
        ("performance", "性能"),
        ("memory", "内存"),
        ("power", "功耗"),
        ("bandwidth", "带宽"),
        ("latency", "时延"),
        ("model", "模型"),
        ("training", "训练"),
        ("system", "系统"),
        ("configuration", "配置"),
        ("result", "结果"),
        ("issue", "问题"),
    ]
    for en, zh in replacements:
        result = re.sub(rf"\\b{re.escape(en)}\\b", zh, result, flags=re.IGNORECASE)
    if result == text:
        return f"(自动翻译不可用) {text}"
    return result


TRANSLATE_STATE = {
    "cache": {},
    "online_enabled": True,
    "failures": 0,
    "opener": None,
    "opener_ready": False,
    "cache_path": None,
    "cache_dirty": False,
}

# MyMemory 匿名配额有限（~1000 词/天）；传 email 后提升至 ~50000 词/天
MYMEMORY_EMAIL = os.environ.get("MYMEMORY_EMAIL", "video.ppt.tool@example.com").strip()


def _mymemory_url(text):
    q = urllib.parse.quote(text[:480])
    url = f"https://api.mymemory.translated.net/get?q={q}&langpair=en|zh-CN"
    if MYMEMORY_EMAIL:
        url += "&de=" + urllib.parse.quote(MYMEMORY_EMAIL)
    return url


def load_translation_cache(path):
    """载入持久化翻译缓存，避免重复消耗 API 配额"""
    TRANSLATE_STATE["cache_path"] = path
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                TRANSLATE_STATE["cache"].update(data)
                print(f"  Translation cache loaded: {len(data)} entries")
        except Exception as e:
            print(f"  Warning: failed to load translation cache: {e}")


def save_translation_cache():
    """保存持久化翻译缓存"""
    path = TRANSLATE_STATE.get("cache_path")
    if not path or not TRANSLATE_STATE.get("cache_dirty"):
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(TRANSLATE_STATE["cache"], f, ensure_ascii=False, indent=0)
        print(f"  Translation cache saved: {len(TRANSLATE_STATE['cache'])} entries")
    except Exception as e:
        print(f"  Warning: failed to save translation cache: {e}")

# 网络通道候选：先直连，再尝试 Intel 代理
PROXY_CANDIDATES = [
    None,
    "http://proxy-dmz.intel.com:911",
    "http://proxy-chain.intel.com:911",
    "http://proxy-us.intel.com:911",
    "http://proxy.intel.com:911",
]


def _build_translate_opener():
    """自动探测可用通道（直连或代理），返回可用 opener"""
    test_url = _mymemory_url("hello world")
    for proxy in PROXY_CANDIDATES:
        try:
            if proxy:
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"http": proxy, "https": proxy})
                )
            else:
                opener = urllib.request.build_opener()
            with opener.open(test_url, timeout=6) as resp:
                if getattr(resp, "status", 200) == 200:
                    print(f"  Translator online via: {proxy or 'direct'}")
                    return opener
        except Exception:
            continue
    return None


def _get_translate_opener():
    if not TRANSLATE_STATE["opener_ready"]:
        TRANSLATE_STATE["opener"] = _build_translate_opener()
        TRANSLATE_STATE["opener_ready"] = True
        if TRANSLATE_STATE["opener"] is None:
            TRANSLATE_STATE["online_enabled"] = False
            print("  Translator offline: 使用本地兜底翻译（质量有限）。")
    return TRANSLATE_STATE["opener"]


def translate_en_to_zh(text):
    """优先在线真翻译（自动走代理），失败后回退离线规则"""
    if not text:
        return ""
    if has_cjk(text):
        return text

    cache = TRANSLATE_STATE["cache"]
    exact = cache.get(text)
    if exact and not _is_bad_zh(exact, text):
        return apply_zh_fixes(exact)

    # 模糊复用：同一句子不同截断长度时，复用已缓存的优质翻译
    fuzzy = _fuzzy_cache_lookup(text)
    if fuzzy:
        return apply_zh_fixes(fuzzy)

    translated = ""
    opener = _get_translate_opener() if TRANSLATE_STATE["online_enabled"] else None
    if opener is not None:
        try:
            url = _mymemory_url(text)
            with opener.open(url, timeout=8) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
            translated = ((payload.get("responseData") or {}).get("translatedText") or "").strip()
            up = translated.upper()
            if translated.lower() == text.lower() or "MYMEMORY WARNING" in up or "INVALID" in up:
                translated = ""
        except Exception:
            TRANSLATE_STATE["failures"] += 1
            if TRANSLATE_STATE["failures"] >= 6:
                TRANSLATE_STATE["online_enabled"] = False

    if not translated:
        translated = fallback_translate_en_to_zh(text)

    if not _is_bad_zh(translated, text):
        cache[text] = translated
        TRANSLATE_STATE["cache_dirty"] = True
    return apply_zh_fixes(translated)


# 翻译后的领域术语修正（MyMemory 对小众一致性术语常误译；按长词优先）
ZH_TERM_FIXES = [
    ("(自动翻译不可用)", "（中文待在线补全）"),
    ("融合相干织物", "融合一致性互连(converged coherent fabric)"),
    ("相干织物", "一致性互连(coherent fabric)"),
    ("铸造兑现代理", "缓存归属代理(caching home agent)"),
    ("有限责任公司", "LLC(末级缓存)"),
    ("活动现金线", "活动缓存行"),
    ("现金线", "缓存行(cache line)"),
    ("现金行", "缓存行(cache line)"),
    ("活动现金", "活动缓存"),
    ("分期线索", "暂存队列(staging queue)"),
    ("分期队列", "暂存队列"),
    ("胜利线", "获胜缓存行(win line)"),
    ("胜利的线", "获胜缓存行(win line)"),
    ("战利品", "有效负载(payload)"),
    ("戒指", "环(ring)"),
    ("相干性", "一致性"),
    ("相干", "一致性"),
    ("织物", "互连结构(fabric)"),
    ("现金", "缓存"),
]


def apply_zh_fixes(text):
    if not text:
        return text
    out = text
    for a, b in ZH_TERM_FIXES:
        out = out.replace(a, b)
    return out


def _is_bad_zh(value, src=""):
    """判断缓存里的中文是否为无效/兜底垃圾"""
    if not value:
        return True
    if value.startswith("(自动翻译"):
        return True
    if not has_cjk(value):
        return True
    if src and value.strip().lower() == src.strip().lower():
        return True
    return False


def _strip_ellipsis(s):
    return (s or "").rstrip("….、,， ").strip()


def _fuzzy_cache_lookup(text):
    """同一句子被截断成不同长度时，复用已缓存的优质翻译（按前缀匹配）"""
    t = _strip_ellipsis(text)
    if len(t) < 18:
        return None
    best = None
    best_len = 0
    for k, v in TRANSLATE_STATE["cache"].items():
        if _is_bad_zh(v, k):
            continue
        kc = _strip_ellipsis(k)
        if len(kc) < 18:
            continue
        if t.startswith(kc) or kc.startswith(t):
            if len(kc) > best_len:
                best_len = len(kc)
                best = v
    return best


FILLER_PATTERNS = [
    r"^thank(s| you)?[.!\s]*$",
    r"^thank you (so |very )?much[.!\s]*$",
    r"^thanks (a lot|everyone|guys|all|again)?[.!\s]*$",
    r"^(bye|bye bye|byebye|goodbye|good bye)[.!\s]*$",
    r"^see you( later| again| next time| around)?[.!\s]*$",
    r"^(ok|okay|alright|all right)[.!\s]*$",
    r"^(yeah|yep|yes|no|uh|um|umm|hmm|hm|huh|oh|hi|hey|hello)[.!\s]*$",
    r"^(you know|i mean|kind of|sort of)[.!\s]*$",
    r"^(let'?s see|let me see)[.!\s]*$",
    r"^(so|well|now|right|cool|great|nice|sure)[.!\s]*$",
    r"^(any questions?|no questions?)[.!\s]*$",
    r"^(谢谢|谢谢大家|谢谢各位|多谢|感谢大家|拜拜|再见|好的|好嘞|嗯|嗯嗯|啊|哦|呃|那个|这个|对对对|是的)[。！\s]*$",
]
FILLER_RE = [re.compile(p, re.IGNORECASE) for p in FILLER_PATTERNS]


def is_filler(sentence):
    """判断是否为无信息量的寒暄/语气填充语（谢谢/再见/嗯等）"""
    s = (sentence or "").strip()
    if not s:
        return True
    plain = re.sub(r"[^\w\u4e00-\u9fff]", "", s)
    if len(plain) <= 2:
        return True
    for rx in FILLER_RE:
        if rx.match(s):
            return True
    lowered = s.lower()
    # Whisper 静音幻觉：同一个词反复出现（you you you / thank you thank you）
    words = re.findall(r"[a-z']+", lowered)
    if words:
        unique = set(words)
        if len(unique) <= 2 and len(words) >= 3:
            return True
        stop = {"you", "the", "a", "an", "i", "uh", "um", "umm", "yeah", "so",
                "and", "to", "it", "is", "of", "ok", "okay", "oh", "hmm", "like"}
        if unique and unique.issubset(stop):
            return True
    filler_words = ["thank you", "thanks", "bye bye", "byebye", "bye", "goodbye",
                    "see you", "谢谢", "再见", "拜拜"]
    stripped = lowered
    for w in filler_words:
        stripped = stripped.replace(w, "")
    stripped = re.sub(r"[^\w\u4e00-\u9fff]", "", stripped)
    if len(stripped) <= 2 and stripped != plain.lower():
        return True
    return False


# ----------------------------------------------------------------------------
# 领域相关性过滤 + 术语规范化（只保留与 CCF/SCF coherent fabric 相关的知识点）
# ----------------------------------------------------------------------------

# 多字符、辨识度高的领域短语（子串匹配即可）
DOMAIN_PHRASES = {
    "coherent fabric", "coherent", "coherency", "converged", "mesh", "caching home agent",
    "home agent", "snoop", "directory", "cache", "memory", "bandwidth", "latency",
    "fabric", "socket", "sub-numa", "numa", "cluster", "clustering", "bridge", "ingress",
    "egress", "credit", "flit", "packet", "throttle", "throttling", "interconnect",
    "topology", "chiplet", "interleave", "interleaving", "hash", "slice", "channel",
    "router", "ring stop", "mesh stop", "node id", "poison", "viral", "parity", "scrub",
    "address decode", "decode", "transaction", "payload", "register", "telemetry",
    "two level memory", "2 level memory", "hemisphere", "quadrant", "sector", "die", "tile",
}

# 短缩写：用单词边界匹配，避免 cha 命中 change / purchase
DOMAIN_ACRONYMS = {
    "ccf", "scf", "cha", "cms", "sbo", "crs", "ufi", "nip", "b2upi", "b2cxl", "b2cmi",
    "b2idi", "b2hot", "b2ubo", "snc", "uma", "2lm", "mktme", "llc", "sf", "mca", "dvfs",
    "pmon", "upi", "cxl", "ddr", "pcie", "imc", "mc", "iio", "ubox", "pkgc",
}

_ACRONYM_RE = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(sorted(map(re.escape, DOMAIN_ACRONYMS), key=len, reverse=True)) + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# ASR 常见误转 / 大小写规范化（标准化为正式术语写法）
TERM_CANONICAL = {
    "ccf": "CCF", "scf": "SCF", "cha": "CHA", "cms": "CMS", "sbo": "SBO", "crs": "CRS",
    "ufi": "UFI", "nip": "NIP", "b2upi": "B2UPI", "b2cxl": "B2CXL", "b2cmi": "B2CMI",
    "b2idi": "B2IDI", "b2hot": "B2HOT", "b2ubo": "B2UBO", "snc": "SNC", "uma": "UMA",
    "2lm": "2LM", "mktme": "MKTME", "llc": "LLC", "mca": "MCA", "dvfs": "DVFS",
    "pmon": "PMON", "upi": "UPI", "cxl": "CXL", "ddr": "DDR", "pcie": "PCIe",
    "imc": "IMC", "iio": "IIO", "ubox": "UBOX", "pkgc": "PkgC",
}

TERM_PHRASE_FIXES = [
    (re.compile(r"\bcaching home agent\b", re.IGNORECASE), "Caching Home Agent (CHA)"),
    (re.compile(r"\bcommon mesh stop\b", re.IGNORECASE), "Common Mesh Stop (CMS)"),
    (re.compile(r"\bsub[\s-]?numa\b", re.IGNORECASE), "Sub-NUMA"),
    (re.compile(r"\b(two|2)\s*level\s*memory\b", re.IGNORECASE), "2LM"),
]


def normalize_terms(text):
    """规范化领域术语：修正缩写大小写、统一专业写法，提升专业度"""
    if not text:
        return text
    out = text
    for rx, repl in TERM_PHRASE_FIXES:
        out = rx.sub(repl, out)

    def _fix(m):
        return TERM_CANONICAL.get(m.group(1).lower(), m.group(1))

    out = _ACRONYM_RE.sub(_fix, out)
    return out


def is_relevant(text):
    """判断文本是否与 CCF/SCF coherent fabric 主题相关（过滤纯寒暄/屏幕共享闲聊）"""
    if not text:
        return False
    low = text.lower()
    if any(p in low for p in DOMAIN_PHRASES):
        return True
    if _ACRONYM_RE.search(text):
        return True
    return False


# ----------------------------------------------------------------------------
# HAS / 参考文档自动跳转链接
# ----------------------------------------------------------------------------
# 每条： keywords=触发关键词, label=显示名, url=可点击跳转地址（无 URL 时只显示标签）
DEFAULT_HAS_REFERENCES = [
    {"keywords": ["scf", "server coherent", "converged"], "label": "SCF Gen3 Overall HAS", "url": None},
    {"keywords": ["ccf", "client coherent"], "label": "CCF HAS", "url": None},
    {"keywords": ["cha", "caching home agent", "snoop", "directory"], "label": "CHA / Coherency HAS", "url": None},
    {"keywords": ["cms", "mesh", "router", "ring stop"], "label": "Mesh / CMS HAS", "url": None},
    {"keywords": ["b2cmi", "imc", "2lm", "memory"], "label": "Memory / B2CMI HAS", "url": None},
    {"keywords": ["upi", "b2upi"], "label": "UPI HAS", "url": None},
    {"keywords": ["cxl", "b2cxl"], "label": "CXL HAS", "url": None},
    {"keywords": ["snc", "uma", "numa", "cluster"], "label": "SNC/UMA Clustering HAS", "url": None},
]

HAS_REFERENCES = list(DEFAULT_HAS_REFERENCES)


def load_has_references(path):
    """从 JSON 载入 HAS 参考链接表，覆盖默认值"""
    global HAS_REFERENCES
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        refs = []
        for item in data:
            kw = item.get("keywords") or []
            if isinstance(kw, str):
                kw = [kw]
            refs.append({
                "keywords": [k.lower() for k in kw],
                "label": item.get("label") or item.get("url") or "HAS",
                "url": item.get("url"),
            })
        if refs:
            HAS_REFERENCES = refs
            print(f"  Loaded {len(refs)} HAS references from {path}")
    except Exception as e:
        print(f"  Warning: failed to load HAS references: {e}")


def matched_has_refs(text, limit=3):
    """返回与文本相关的 HAS 参考（按关键词命中），用于本页自动跳转"""
    if not text:
        return []
    low = text.lower()
    hits = []
    for ref in HAS_REFERENCES:
        if any(k in low for k in ref.get("keywords", [])):
            hits.append(ref)
        if len(hits) >= limit:
            break
    return hits


def add_hyperlink_run(paragraph, text, url=None, size=10, color=(0x0F, 0x5E, 0xC9)):
    """在段落里追加一个（可选超链接的）文字 run"""
    run = paragraph.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor(*color)
    if url:
        try:
            run.hyperlink.address = url
            run.font.underline = True
        except Exception:
            pass
    return run


def summarize_segment(text, max_chars=110):
    """生成本页主旨：挑选信息量最高、且与主题相关的一句，剔除寒暄语"""
    sentences = [s.strip() for s in split_sentences(text) if s.strip()]
    candidates = [s for s in sentences if not is_filler(s) and len(s) > 12]
    relevant = [s for s in candidates if is_relevant(s)]
    if not relevant:
        return ""
    candidates = relevant
    if not candidates:
        return ""
    keywords = ["important", "key", "because", "result", "performance", "memory",
                "bandwidth", "latency", "configure", "configuration", "issue",
                "problem", "should", "need", "improve", "increase", "reduce",
                "support", "enable", "design", "feature", "data", "model"]

    def score(s):
        low = s.lower()
        kw = sum(2 for k in keywords if k in low)
        return kw + min(len(s) / 40.0, 3)

    # 优先选择能完整容纳的句子（不需截断）
    fitting = [c for c in candidates if len(normalize_terms(c)) <= max_chars]
    pool = fitting if fitting else candidates
    best = max(pool, key=score)
    best = normalize_terms(best)
    best = clip_at_boundary(best, max_chars)
    return best


def remove_empty_textboxes(slide):
    """删除没有任何文字内容的空文本框/空占位符（保留背景色块和图片）"""
    removed = 0
    for shape in list(slide.shapes):
        try:
            if not shape.has_text_frame:
                continue
            if (shape.text_frame.text or "").strip():
                continue
            is_textbox = shape.shape_type == MSO_SHAPE_TYPE.TEXT_BOX
            if is_textbox or shape.is_placeholder:
                shape._element.getparent().remove(shape._element)
                removed += 1
        except Exception:
            continue
    return removed


def to_bullets(text, max_items=6, max_chars_per_item=95, relevant_only=True):
    """把长文本变成可读 bullet：剔除寒暄、只保留主题相关句、规范化术语"""
    sentences = split_sentences(text)
    items = []
    for s in sentences:
        clean = s.replace("\n", " ").strip()
        if len(clean) < 6:
            continue
        if is_filler(clean):
            continue
        if relevant_only and not is_relevant(clean):
            continue
        clean = normalize_terms(clean)
        clean = clip_at_boundary(clean, max_chars_per_item)
        items.append(clean)
        if len(items) >= max_items:
            break

    return items


def draw_footer(slide, slide_width, slide_height, footer_text):
    """统一页脚信息，提升展示观感"""
    bar = slide.shapes.add_shape(1, Inches(0.2), slide_height - Inches(0.45), slide_width - Inches(0.4), Inches(0.25))
    bar.fill.solid()
    bar.fill.fore_color.rgb = RGBColor(0xF5, 0xF8, 0xFC)
    bar.line.color.rgb = RGBColor(0xD3, 0xDE, 0xEA)

    tx = slide.shapes.add_textbox(Inches(0.35), slide_height - Inches(0.42), slide_width - Inches(0.7), Inches(0.2))
    tf = tx.text_frame
    p = tf.paragraphs[0]
    p.text = footer_text
    p.font.size = Pt(9)
    p.font.color.rgb = RGBColor(0x4D, 0x5E, 0x73)


def get_slide_layout(prs, layout_index=1):
    """获取 slide layout，优先用 index=1（通常是标题+内容布局）"""
    layouts = prs.slide_layouts
    if layout_index < len(layouts):
        return layouts[layout_index]
    # fallback: 使用空白布局（通常是最后一个）
    return layouts[-1]


def add_content_slide(prs, layout, image_path, title_text, body_text, slide_width, slide_height, bilingual=True, curated=None):
    """添加一张内容 slide：左侧图片 + 右侧文字。
    curated 提供时，使用人工润色的中英文要点（不再机翻、不再截断）。"""
    slide = prs.slides.add_slide(layout)

    # 清除 layout 自带的 placeholder 文本
    for ph in slide.placeholders:
        if ph.has_text_frame:
            ph.text_frame.clear()

    # 图片区域：左侧 60% 宽
    img_left = Inches(0.3)
    img_top = Inches(1.35)
    img_width = slide_width * 0.58
    img_height = slide_height - Inches(1.95)

    # 保持图片比例
    if Image and os.path.exists(image_path):
        with Image.open(image_path) as img:
            orig_w, orig_h = img.size
            aspect = orig_w / orig_h
            target_w = img_width
            target_h = int(target_w / aspect)
            if target_h > img_height:
                target_h = img_height
                target_w = int(target_h * aspect)
            img_width = target_w
            img_height = target_h

    slide.shapes.add_picture(image_path, img_left, img_top, img_width, img_height)

    # 顶部标题条：白底窄条，仅放单行标题，避免文字拥挤重叠
    title_bg = slide.shapes.add_shape(
        1, Inches(0.2), Inches(0.18), slide_width - Inches(0.4), Inches(0.95)
    )
    title_bg.fill.solid()
    title_bg.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    title_bg.fill.transparency = 0.05
    title_bg.line.color.rgb = RGBColor(0xD9, 0xE2, 0xEC)
    title_bg.shadow.inherit = False

    # 标题（单行）
    title_box = slide.shapes.add_textbox(Inches(0.4), Inches(0.28), slide_width - Inches(0.8), Inches(0.75))
    tf = title_box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.text = title_text
    p.font.size = Pt(18)
    p.font.bold = True
    p.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)

    # 文字区域白底卡片：保证对比度和可读性
    text_left = slide_width * 0.60 + Inches(0.2)
    text_top = Inches(1.35)
    text_width = slide_width * 0.37
    text_height = slide_height - Inches(1.95)

    text_bg = slide.shapes.add_shape(1, text_left - Inches(0.08), text_top - Inches(0.05), text_width + Inches(0.16), text_height + Inches(0.1))
    text_bg.fill.solid()
    text_bg.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    text_bg.fill.transparency = 0.08
    text_bg.line.color.rgb = RGBColor(0xCC, 0xD6, 0xE0)
    text_bg.shadow.inherit = False

    text_box = slide.shapes.add_textbox(text_left, text_top + Inches(0.05), text_width, text_height - Inches(0.1))
    tf = text_box.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.margin_left = Inches(0.12)
    tf.margin_right = Inches(0.12)
    tf.margin_top = Inches(0.08)

    if curated:
        gist = curated.get("gist_en", "") or ""
        gist_zh = curated.get("gist_zh", "") or ""
        bullets = list(curated.get("en", []) or [])
        zh_bullets = list(curated.get("zh", []) or [])
    else:
        gist = summarize_segment(body_text, max_chars=78)
        gist_zh = translate_en_to_zh(gist) if gist else ""
        bullets = to_bullets(body_text, max_items=3, max_chars_per_item=86)
        zh_bullets = [translate_en_to_zh(b) for b in bullets]

    first_para = True

    def _add(text, size, bold, color, space_before=0, space_after=3, spacing=1.0):
        nonlocal first_para
        para = tf.paragraphs[0] if first_para else tf.add_paragraph()
        first_para = False
        para.text = text
        para.font.size = Pt(size)
        para.font.bold = bold
        para.font.color.rgb = RGBColor(*color)
        para.space_before = Pt(space_before)
        para.space_after = Pt(space_after)
        try:
            para.line_spacing = spacing
        except Exception:
            pass
        return para

    if gist:
        _add("主旨 · Gist", 10, True, (0x6B, 0x7A, 0x8C), space_after=2)
        _add(gist, 12, True, (0x16, 0x3B, 0x5A), space_after=3, spacing=1.05)
        if bilingual and gist_zh:
            _add(gist_zh, 11, False, (0x2A, 0x55, 0x6E), space_after=6, spacing=1.1)

    if bullets:
        _add("要点 · Key Points", 10, True, (0x6B, 0x7A, 0x8C), space_before=4, space_after=3)
        for idx, b in enumerate(bullets):
            _add(f"• {b}", 11, True, (0x1F, 0x2A, 0x38), space_before=2, space_after=2, spacing=1.05)
            if bilingual:
                zh = zh_bullets[idx] if idx < len(zh_bullets) else translate_en_to_zh(b)
                if zh:
                    _add(f"  {zh}", 10.5, False, (0x44, 0x52, 0x63), space_after=6, spacing=1.1)
    elif not gist:
        _add("本页无与 CCF/SCF 相关的知识点", 12, False, (0x80, 0x80, 0x80), space_after=4)
        if bilingual:
            _add("(No CCF/SCF-related point in this segment)", 10, False, (0x99, 0x99, 0x99))

    # 本页相关 HAS 自动跳转链接
    ref_source = body_text
    if curated:
        ref_source = " ".join([gist] + bullets)
    refs = matched_has_refs(ref_source)
    if refs:
        link_p = tf.add_paragraph()
        link_p.space_before = Pt(8)
        lead = link_p.add_run()
        lead.text = "参考 HAS: "
        lead.font.size = Pt(10)
        lead.font.bold = True
        lead.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
        for i, ref in enumerate(refs):
            if i:
                sep = link_p.add_run()
                sep.text = " | "
                sep.font.size = Pt(10)
                sep.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
            add_hyperlink_run(link_p, ref["label"], ref.get("url"))

    draw_footer(slide, slide_width, slide_height, "Generated by video-to-ppt | Timeline + Summary + Q&A")

    return slide


def add_slide_notes(slide, frame, segment=None, qa_pairs=None):
    """在备注里记录时间点、原文和 Q&A，便于人工复核"""
    notes_slide = slide.notes_slide
    tf = notes_slide.notes_text_frame
    tf.clear()

    ts = frame.get("timestamp_sec", 0)
    lines = [
        f"Frame Timestamp: {format_timestamp(ts)} ({ts:.1f}s)",
        f"Frame File: {frame.get('filename', '')}",
    ]

    if segment:
        start = segment.get("time_start", ts)
        end = segment.get("time_end", ts)
        lines.append(f"Segment Range: {format_timestamp(start)} - {format_timestamp(end)}")
        lines.append("")
        lines.append("Transcript Segments:")

        seg_items = segment.get("segments", [])
        if seg_items:
            for s in seg_items:
                s_start = format_timestamp(s.get("start", start))
                s_end = format_timestamp(s.get("end", end))
                s_text = (s.get("text") or "").replace("\n", " ").strip()
                if s_text:
                    lines.append(f"[{s_start}-{s_end}] {s_text}")
        else:
            full_text = (segment.get("full_text") or "").replace("\n", " ").strip()
            if full_text:
                lines.append(full_text)

    if qa_pairs:
        lines.append("")
        lines.append("Q&A In This Segment:")
        for qa in qa_pairs:
            q_time = qa.get("time_str") or format_timestamp(qa.get("time", ts))
            lines.append(f"Q [{q_time}]: {qa.get('question', '')}")
            ans = qa.get("answer", "").strip()
            if ans:
                lines.append(f"A: {ans}")
            else:
                lines.append("A: (not confidently extracted)")

    tf.text = "\n".join(lines)


def add_summary_slide(prs, layout, key_points, slide_width, slide_height):
    """添加总结页"""
    slide = prs.slides.add_slide(layout)

    for ph in slide.placeholders:
        if ph.has_text_frame:
            ph.text_frame.clear()

    # 标题
    title_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), slide_width - Inches(1), Inches(0.8))
    tf = title_box.text_frame
    p = tf.paragraphs[0]
    p.text = "Summary / 重点总结"
    p.font.size = Pt(24)
    p.font.bold = True
    p.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)

    # 内容
    content_box = slide.shapes.add_textbox(Inches(0.5), Inches(1.3), slide_width - Inches(1), slide_height - Inches(1.8))
    tf = content_box.text_frame
    tf.word_wrap = True

    for kp in key_points:
        time_str = format_timestamp(kp["time_start"])
        for point in kp["points"]:
            if is_filler(point) or not is_relevant(point):
                continue
            point = normalize_terms(point)
            p = tf.add_paragraph()
            p.text = f"• EN [{time_str}] {point}"
            p.font.size = Pt(12)
            p.space_after = Pt(4)

            p2 = tf.add_paragraph()
            p2.text = f"  ZH [{time_str}] {translate_en_to_zh(point)}"
            p2.font.size = Pt(11)
            p2.font.color.rgb = RGBColor(0x33, 0x3F, 0x4F)
            p2.space_after = Pt(6)

    draw_footer(slide, slide_width, slide_height, "Summary with bilingual highlights | 双语重点总结")

    return slide


def add_qa_slides(prs, layout, qa_pairs, slide_width, slide_height, per_slide=6):
    """添加 Q&A 汇总页（分页，保留全部问答记录）"""
    if not qa_pairs:
        return 0

    total_added = 0
    chunks = [qa_pairs[i:i + per_slide] for i in range(0, len(qa_pairs), per_slide)]

    for page_idx, chunk in enumerate(chunks, start=1):
        slide = prs.slides.add_slide(layout)
        total_added += 1

        for ph in slide.placeholders:
            if ph.has_text_frame:
                ph.text_frame.clear()

        title_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), slide_width - Inches(1), Inches(0.8))
        tf = title_box.text_frame
        p = tf.paragraphs[0]
        p.text = f"Q&A 汇总 ({page_idx}/{len(chunks)})"
        p.font.size = Pt(24)
        p.font.bold = True
        p.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)

        content_bg = slide.shapes.add_shape(1, Inches(0.45), Inches(1.2), slide_width - Inches(0.9), slide_height - Inches(1.65))
        content_bg.fill.solid()
        content_bg.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        content_bg.fill.transparency = 0.06
        content_bg.line.color.rgb = RGBColor(0xCC, 0xD6, 0xE0)

        content_box = slide.shapes.add_textbox(Inches(0.55), Inches(1.3), slide_width - Inches(1.1), slide_height - Inches(1.9))
        tf = content_box.text_frame
        tf.word_wrap = True

        for idx, qa in enumerate(chunk):
            time_str = qa.get("time_str") or format_timestamp(qa.get("time", 0))
            q = normalize_terms(qa.get("q") or qa.get("question", ""))
            a = normalize_terms((qa.get("a") or qa.get("answer", "")).strip()) or "(未能可靠提取答案，请回看备注原文)"
            q_zh = qa.get("q_zh") or translate_en_to_zh(q)
            a_zh = qa.get("a_zh") or translate_en_to_zh(a)

            if idx == 0:
                p = tf.paragraphs[0]
            else:
                p = tf.add_paragraph()
            p.text = f"Q [{time_str}]: {truncate_text(q, 160)}"
            p.font.size = Pt(12)
            p.font.bold = True
            p.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
            p.space_before = Pt(7)

            p = tf.add_paragraph()
            p.text = f"A: {truncate_text(a, 220)}"
            p.font.size = Pt(11)
            p.font.color.rgb = RGBColor(0x2F, 0x2F, 0x2F)
            p.space_after = Pt(3)

            p = tf.add_paragraph()
            p.text = f"问 [{time_str}]: {truncate_text(q_zh, 180)}"
            p.font.size = Pt(11)
            p.font.color.rgb = RGBColor(0x2A, 0x3A, 0x4A)

            p = tf.add_paragraph()
            p.text = f"答: {truncate_text(a_zh, 220)}"
            p.font.size = Pt(10)
            p.font.color.rgb = RGBColor(0x3A, 0x4A, 0x5A)
            p.space_after = Pt(5)

        draw_footer(slide, slide_width, slide_height, "Q&A Trace | 问答追踪")

    return total_added


def add_references_slide(prs, layout, slide_width, slide_height):
    """添加 HAS 参考总表页（可点击跳转）"""
    refs = [r for r in HAS_REFERENCES if r.get("label")]
    if not refs:
        return None
    slide = prs.slides.add_slide(layout)
    for ph in slide.placeholders:
        if ph.has_text_frame:
            ph.text_frame.clear()

    title_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), slide_width - Inches(1), Inches(0.8))
    p = title_box.text_frame.paragraphs[0]
    p.text = "参考 HAS 文档 / Reference HAS"
    p.font.size = Pt(24)
    p.font.bold = True
    p.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)

    bg = slide.shapes.add_shape(1, Inches(0.45), Inches(1.2), slide_width - Inches(0.9), slide_height - Inches(1.65))
    bg.fill.solid()
    bg.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    bg.fill.transparency = 0.06
    bg.line.color.rgb = RGBColor(0xCC, 0xD6, 0xE0)

    box = slide.shapes.add_textbox(Inches(0.6), Inches(1.35), slide_width - Inches(1.2), slide_height - Inches(2.0))
    tf = box.text_frame
    tf.word_wrap = True
    has_url = False
    for i, ref in enumerate(refs):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.space_after = Pt(6)
        bullet = para.add_run()
        bullet.text = "• "
        bullet.font.size = Pt(13)
        bullet.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        add_hyperlink_run(para, ref["label"], ref.get("url"), size=13)
        if ref.get("url"):
            has_url = True
        else:
            note = para.add_run()
            note.text = "  (待填入链接)"
            note.font.size = Pt(10)
            note.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

    if not has_url:
        tip = tf.add_paragraph()
        tip.space_before = Pt(10)
        tip.text = "提示：通过 --has-refs 注入真实 HAS URL 后，以上条目即可点击跳转。"
        tip.font.size = Pt(10)
        tip.font.italic = True
        tip.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    draw_footer(slide, slide_width, slide_height, "Reference HAS | 参考文档跳转")
    return slide


def generate_ppt(frames_dir, transcript_path, template_path, output_path, max_slides=30, bilingual=True, curated_path=None):
    """主生成函数"""
    # 加载模板
    if not os.path.exists(template_path):
        print(f"Error: Template not found: {template_path}")
        sys.exit(1)

    # 加载人工润色覆盖层（有则优先于机翻，内容更通顺完整）
    curated = {}
    if curated_path and os.path.exists(curated_path):
        with open(curated_path, "r", encoding="utf-8") as f:
            curated = json.load(f)
        print(f"  Loaded curated overrides: {len(curated.get('slides', {}))} slides, {len(curated.get('qa', []))} Q&A")
    curated_slides = curated.get("slides", {}) if curated else {}
    curated_only = bool(curated_slides)

    prs = Presentation(template_path)
    slide_width = prs.slide_width
    slide_height = prs.slide_height

    # 持久化翻译缓存（与输出同目录），避免重复消耗 API 配额
    if bilingual and not TRANSLATE_STATE.get("cache_path"):
        cache_path = os.path.join(os.path.dirname(os.path.abspath(output_path)) or ".", ".translation_cache.json")
        load_translation_cache(cache_path)
    print(f"Template: {template_path}")
    print(f"  Slide size: {slide_width/914400:.1f}\" x {slide_height/914400:.1f}\"")
    print(f"  Layouts available: {len(prs.slide_layouts)}")

    # 选择布局：使用第二个 layout（通常是 Title + Content）
    # 如果模板只有一个 layout，用那个
    content_layout = get_slide_layout(prs, 1)

    # 加载转录数据
    transcript = {}
    if transcript_path and os.path.exists(transcript_path):
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript = json.load(f)
        print(f"  Loaded transcript: {len(transcript.get('structured_segments', []))} segments")

    # 加载帧元数据
    frames_meta_path = os.path.join(frames_dir, "frames_meta.json")
    if os.path.exists(frames_meta_path):
        with open(frames_meta_path, "r", encoding="utf-8") as f:
            frames_meta = json.load(f)
    else:
        # 按文件名排序
        frame_files = sorted([f for f in os.listdir(frames_dir) if f.endswith(".png")])
        frames_meta = [{"filename": f, "filepath": os.path.join(frames_dir, f),
                       "timestamp_sec": 0, "index": i} for i, f in enumerate(frame_files)]

    print(f"  Found {len(frames_meta)} frames")

    # 获取结构化文本
    structured = transcript.get("structured_segments", [])
    structured_map = {seg.get("slide_index"): seg for seg in structured}

    # 删除模板中的所有现有 slides（保留 layout 定义）
    while len(prs.slides) > 0:
        rId = prs.slides._sldIdLst[0].rId
        prs.part.drop_rel(rId)
        del prs.slides._sldIdLst[0]

    # 添加标题页
    title_layout = get_slide_layout(prs, 0)
    title_slide = prs.slides.add_slide(title_layout)
    for ph in title_slide.placeholders:
        if ph.has_text_frame:
            ph.text_frame.clear()

    # 视频标题
    video_name = transcript.get("video", "Video Presentation")
    video_name = Path(video_name).stem if video_name else "Video Presentation"
    title_box = title_slide.shapes.add_textbox(Inches(0.5), Inches(2), slide_width - Inches(1), Inches(2))
    tf = title_box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = video_name
    p.font.size = Pt(28)
    p.font.bold = True
    p.alignment = PP_ALIGN.CENTER

    duration = transcript.get("duration_sec", 0)
    if duration > 0:
        p = tf.add_paragraph()
        p.text = f"Duration: {format_timestamp(duration)}"
        p.font.size = Pt(14)
        p.alignment = PP_ALIGN.CENTER

    title_notes = title_slide.notes_slide.notes_text_frame
    title_notes.clear()
    title_notes.text = "Auto-generated by video-to-ppt. This deck contains timeline, summary, and Q&A traceability."

    # 添加内容页
    slides_added = 0
    for frame in frames_meta:
        if slides_added >= max_slides:
            break

        img_path = frame.get("filepath") or os.path.join(frames_dir, frame["filename"])
        if not os.path.exists(img_path):
            continue

        timestamp = frame.get("timestamp_sec", 0)
        time_str = format_timestamp(timestamp)

        idx = frame.get("index", -1)
        slide_curated = curated_slides.get(str(idx)) if curated_slides else None
        # 启用润色覆盖层时，仅保留有润色内容的相关页，得到紧凑高质量的讲解 deck
        if curated_only and not slide_curated:
            continue

        # 找对应的文字
        body_text = ""
        if structured:
            for seg in structured:
                if seg["slide_index"] == frame.get("index", -1):
                    body_text = seg["full_text"]
                    break
            # fallback: 按时间匹配
            if not body_text:
                for seg in structured:
                    if seg["time_start"] <= timestamp < seg.get("time_end", float("inf")):
                        body_text = seg["full_text"]
                        break

        title = f"[{time_str}]"
        if slide_curated:
            gist_en = slide_curated.get("gist_en", "")
            short = gist_en.split(".")[0][:42].strip()
            title = f"[{time_str}] {short}" if short else f"[{time_str}]"
        elif body_text:
            # 从相关主旨提取简短标题（跳过闲聊）
            gist = summarize_segment(body_text, max_chars=42)
            if gist:
                short = gist.split("。")[0].split(".")[0][:34].strip()
                title = f"[{time_str}] {short}"
            else:
                title = f"[{time_str}] (本页无相关要点)"

        slide = add_content_slide(prs, content_layout, img_path, title, body_text,
                      slide_width, slide_height, bilingual=bilingual, curated=slide_curated)

        seg = structured_map.get(frame.get("index"))
        frame_qa = [q for q in transcript.get("qa_pairs", []) if q.get("slide_index") == frame.get("index")]
        add_slide_notes(slide, frame, seg, frame_qa)
        slides_added += 1

    # 添加总结页（润色模式下内容页已完整覆盖，跳过机翻总结页避免低质内容）
    key_points = transcript.get("key_points", [])
    if key_points and not curated_only:
        sum_slide = add_summary_slide(prs, content_layout, key_points, slide_width, slide_height)
        sum_notes = sum_slide.notes_slide.notes_text_frame
        sum_notes.clear()
        summary_lines = ["Summary source timeline:"]
        for kp in key_points:
            start = format_timestamp(kp.get("time_start", 0))
            end = format_timestamp(kp.get("time_end", kp.get("time_start", 0)))
            summary_lines.append(f"[{start}-{end}] {len(kp.get('points', []))} key points")
        sum_notes.text = "\n".join(summary_lines)

    # 添加 Q&A 页（优先用人工润色问答；否则过滤无意义寒暄 + 只保留主题相关问答）
    if curated.get("qa"):
        qa_pairs = curated["qa"]
    else:
        qa_pairs = [
            q for q in transcript.get("qa_pairs", [])
            if not is_filler(q.get("question", ""))
            and (is_relevant(q.get("question", "")) or is_relevant(q.get("answer", "")))
        ]
    if qa_pairs:
        qa_slide_count = add_qa_slides(prs, content_layout, qa_pairs, slide_width, slide_height)
    else:
        qa_slide_count = 0

    # 添加 HAS 参考总表页（可点击跳转）
    add_references_slide(prs, content_layout, slide_width, slide_height)

    # 清除所有空白文本框/空占位符
    empty_removed = 0
    for slide in prs.slides:
        empty_removed += remove_empty_textboxes(slide)

    # 保存持久化翻译缓存
    save_translation_cache()

    # 保存
    prs.save(output_path)
    total_slides = len(prs.slides)
    print(f"\nPPT generated: {output_path}")
    print(f"  Total slides: {total_slides} (1 title + {slides_added} content + {qa_slide_count} Q&A + extras)")
    print(f"  Empty text boxes removed: {empty_removed}")


def main():
    parser = argparse.ArgumentParser(description="从帧和转录生成 PPT")
    parser.add_argument("--frames-dir", required=True, help="帧图片目录")
    parser.add_argument("--transcript", default=None, help="转录 JSON 文件")
    parser.add_argument("--template", required=True, help="PPT 模板文件")
    parser.add_argument("--output", default="output.pptx", help="输出 PPT 路径")
    parser.add_argument("--max-slides", type=int, default=30, help="最大内容页数")
    parser.add_argument("--no-bilingual", action="store_true", help="关闭中英文对照")
    parser.add_argument("--has-refs", default=None, help="HAS 参考链接 JSON 文件（keywords/label/url）")
    parser.add_argument("--curated", default=None, help="人工润色覆盖层 JSON（slides + qa，优先于机翻）")
    args = parser.parse_args()

    load_has_references(args.has_refs)
    generate_ppt(args.frames_dir, args.transcript, args.template, args.output,
                max_slides=args.max_slides, bilingual=not args.no_bilingual,
                curated_path=args.curated)


if __name__ == "__main__":
    main()
