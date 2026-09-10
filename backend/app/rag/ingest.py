"""知识库构建：多格式解析 → 章节感知分块 → 落盘。

分块策略说明（为什么不是简单按字数滑窗）：

本知识库的对象是**技术/学术文档**，语义单元天然就是「章节」。
按字数硬切（如固定 500 字滑窗）会把一个完整的算法推导切成两半，
检索时命中后半段的概率远高于命中定义段，导致 LLM 拿到残缺上下文反而答错。

因此这里用的是：
1. **按标题层级切成原子节**（Markdown `#`~`####` / PPT 单页 / PDF 页段落合并）
2. **过长再递归细分**：超过 max_chars 的节，按段落边界二次切分并保留重叠
3. **每块携带标题路径**：如「3.2 坡度提取 > 算法步骤」，让检索结果自带出处

这是 RAG 里收益最高、成本最低的一步 —— 比换更大的 embedding 模型有效得多。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
LITERATURE_DIR = REPO_ROOT / "literature"
DEFAULT_INDEX_DIR = REPO_ROOT / "backend" / ".data" / "rag"

MAX_CHARS = 520          # 单块目标字数上限
OVERLAP_CHARS = 80       # 二次切分时的重叠量
MIN_CHARS = 60           # 低于此长度视为噪声块，丢弃

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_MATH_NOISE = re.compile(r"^[\s\uff08\(\)\[\],.\u3001\uff1b;:\-+*/=0-9a-zA-Z]+$")


@dataclass
class Chunk:
    """检索的最小单元。"""

    id: str                      # 稳定 hash，重复 ingest 不会漂移
    text: str
    source: str                  # 相对仓库路径
    source_type: str             # md / pdf / pptx
    title_path: List[str] = field(default_factory=list)
    page: Optional[int] = None   # PDF/PPT 页码
    order: int = 0               # 块在文档中的顺序，用于相邻块拼接

    @property
    def heading(self) -> str:
        return " > ".join(self.title_path) if self.title_path else ""


# ---------------------------------------------------------------- 格式适配

def parse_markdown(path: Path) -> List[tuple[List[str], str]]:
    """返回 [(标题路径, 正文)]。代码块整体保留，不参与切分判断。"""
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    sections: List[tuple[List[str], str]] = []
    stack: List[str] = []
    buf: List[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            sections.append((list(stack), body))
        buf.clear()

    in_code = False
    for line in raw.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
            buf.append(line)
            continue
        if in_code:
            buf.append(line)
            continue
        m = _HEADING_RE.match(line)
        if m:
            flush()
            level = len(m.group(1))
            title = m.group(2).strip() or "（无标题）"
            stack = stack[: level - 1]
            stack.append(title)
        else:
            buf.append(line)
    flush()

    # 无标题文档：整篇作为一节
    if not sections and raw.strip():
        sections.append(([path.stem], raw.strip()))
    return sections


def parse_pdf(path: Path) -> List[tuple[List[str], str, int]]:
    """按页解析，返回 [(标题路径, 正文, 页码)]。"""
    try:
        from pypdf import PdfReader
    except ImportError:
        return []

    try:
        reader = PdfReader(str(path))
    except Exception:
        return []

    out: List[tuple[List[str], str, int]] = []
    for i, page in enumerate(reader.pages, 1):
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        txt = _clean_extracted(txt)
        if len(txt) >= MIN_CHARS:
            out.append(([path.stem, f"第 {i} 页"], txt, i))
    return out


def parse_pptx(path: Path) -> List[tuple[List[str], str, int]]:
    """按幻灯片解析，合并文本框，返回 [(标题路径, 正文, 页码)]。"""
    try:
        from pptx import Presentation
    except ImportError:
        return []

    try:
        prs = Presentation(str(path))
    except Exception:
        return []

    out: List[tuple[List[str], str, int]] = []
    for i, slide in enumerate(prs.slides, 1):
        parts: List[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                t = shape.text_frame.text.strip()
                if t:
                    parts.append(t)
            elif shape.has_table:
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    if any(cells):
                        parts.append(" | ".join(cells))
        body = _clean_extracted("\n".join(parts))
        if len(body) >= 30:  # PPT 一页信息量小，门槛放低
            out.append(([path.stem, f"第 {i} 页"], body, i))
    return out


def _clean_extracted(txt: str) -> str:
    """清理 PDF/PPT 抽取噪声。

    三件事：
    1. 丢弃孤立页码 —— PDF 每页页眉页脚会混入。
    2. 丢弃无中文的纯符号行 —— OCR 残留的乱码公式行。
    3. **消除中文字符之间的空格** —— PDF 排版换行时会在词中插入换行/空格，
       如「可能陷入局部 最优解」。不处理的话 BM25 的 bigram 会被拦腰截断
       （"局部最优" 建不出索引项），关键词检索也会静默失效。
    """
    lines = []
    for ln in txt.splitlines():
        s = ln.strip()
        if not s:
            continue
        # 孤立页码
        if re.fullmatch(r"[-–—\s]*\d{1,4}[-–—\s]*", s):
            continue
        # 纯符号/数字行（OCR 残留的乱码公式行）
        if _MATH_NOISE.match(s) and len(re.findall(r"[\u4e00-\u9fff]", s)) == 0:
            continue
        lines.append(s)
    out = "\n".join(lines)
    # ① 中文之间的空格/换行一律消掉（PDF 换行造成的词内断裂）
    out = re.sub(r"(?<=[\u4e00-\u9fff])[\s\u3000]+(?=[\u4e00-\u9fff])", "", out)
    # ② 中英文之间的空格保留但归一化为一个半角空格，便于后续切词
    out = re.sub(r"[\u3000]+", " ", out)
    # 压缩 3 个以上连续换行
    return re.sub(r"\n{3,}", "\n\n", out).strip()


# ---------------------------------------------------------------- 切块

def _split_long(text: str, limit: int, overlap: int) -> List[str]:
    """超长文本按段落边界递归细分，带重叠。"""
    if len(text) <= limit:
        return [text]

    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    # 单段落就超限时，按句子再次降级到硬切
    if len(paragraphs) == 1:
        return _hard_split(paragraphs[0], limit, overlap)

    pieces: List[str] = []
    buf = ""
    for p in paragraphs:
        if buf and len(buf) + len(p) + 2 > limit:
            pieces.append(buf.strip())
            buf = p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf.strip():
        pieces.append(buf.strip())

    # 相邻块补重叠（把前一块的尾部作为下一块的头部上下文）
    if len(pieces) > 1 and overlap > 0:
        merged: List[str] = []
        for i, piece in enumerate(pieces):
            if i == 0:
                merged.append(piece)
            else:
                prev_tail = pieces[i - 1][-overlap:]
                merged.append(prev_tail + "\n\n" + piece)
        pieces = merged
    return pieces


def _hard_split(text: str, limit: int, overlap: int) -> List[str]:
    """无段落结构时的兜底：按句号/分号切。"""
    units = re.split(r"(?<=[。！？；])", text)
    pieces, buf = [], ""
    for u in units:
        if buf and len(buf) + len(u) > limit:
            pieces.append(buf)
            buf = u
        else:
            buf += u
    if buf:
        pieces.append(buf)
    if not pieces:
        pieces = [text[i : i + limit] for i in range(0, len(text), limit)]
    return pieces


def build_chunks(
    sources: Optional[List[Path]] = None,
    max_chars: int = MAX_CHARS,
    overlap: int = OVERLAP_CHARS,
) -> List[Chunk]:
    """扫描语料目录，产出全部 Chunk。"""
    if sources is None:
        sources = discover_sources()

    chunks: List[Chunk] = []
    for path in sources:
        rel = _rel(path)
        if path.suffix.lower() == ".md":
            for title_path, body in parse_markdown(path):
                _append(chunks, body, rel, "md", title_path, None, max_chars, overlap)
        elif path.suffix.lower() == ".pdf":
            for title_path, body, page in parse_pdf(path):
                _append(chunks, body, rel, "pdf", title_path, page, max_chars, overlap)
        elif path.suffix.lower() == ".pptx":
            for title_path, body, page in parse_pptx(path):
                _append(chunks, body, rel, "pptx", title_path, page, max_chars, overlap)
    return chunks


def _append(
    chunks: List[Chunk],
    body: str,
    rel: str,
    stype: str,
    title_path: List[str],
    page: Optional[int],
    max_chars: int,
    overlap: int,
) -> None:
    for piece in _split_long(body, max_chars, overlap):
        piece = piece.strip()
        if len(piece) < MIN_CHARS:
            continue
        cid = hashlib.sha1(f"{rel}|{page}|{piece[:80]}".encode("utf-8")).hexdigest()[:16]
        chunks.append(
            Chunk(
                id=cid,
                text=piece,
                source=rel,
                source_type=stype,
                title_path=list(title_path),
                page=page,
                order=len(chunks),
            )
        )


def discover_sources(dirpath: Path = LITERATURE_DIR) -> List[Path]:
    """收集知识库语料。当前只收 literature/ —— 它是唯一确认高质量的领域语料。"""
    if not dirpath.exists():
        return []
    exts = {".md", ".pdf", ".pptx"}
    found: List[Path] = []
    for p in sorted(dirpath.rglob("*")):
        if p.is_file() and p.suffix.lower() in exts and "__pycache__" not in str(p):
            found.append(p)
    return found


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(p)


# ---------------------------------------------------------------- 落盘

def save_chunks(chunks: List[Chunk], index_dir: Path = DEFAULT_INDEX_DIR) -> Path:
    index_dir.mkdir(parents=True, exist_ok=True)
    out = index_dir / "chunks.json"
    payload = {
        "version": 1,
        "count": len(chunks),
        "chunks": [asdict(c) for c in chunks],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def load_chunks(index_dir: Path = DEFAULT_INDEX_DIR) -> List[Chunk]:
    p = index_dir / "chunks.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return [Chunk(**c) for c in data["chunks"]]


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="构建 GeoAgent 领域知识库")
    ap.add_argument("--dir", default=str(LITERATURE_DIR))
    ap.add_argument("--out", default=str(DEFAULT_INDEX_DIR))
    args = ap.parse_args()

    src = discover_sources(Path(args.dir))
    print(f"[语料] 发现 {len(src)} 个文件")
    chunks = build_chunks(src)
    path = save_chunks(chunks, Path(args.out))

    by_type: Dict[str, int] = {}
    chars = 0
    for c in chunks:
        by_type[c.source_type] = by_type.get(c.source_type, 0) + 1
        chars += len(c.text)
    print(f"[切块] {len(chunks)} 块，共 {chars:,} 字符")
    for k, v in sorted(by_type.items()):
        print(f"       {k:6s} {v} 块")
    print(f"[落盘] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
