"""在独立意图测试集上，对比「不改动 4B 规划器」与「微调 4B」两条路线的意图判断方案。

为什么要有这个脚本
------------------
主评测集（100 条）里绝大多数问句都含正则关键词（坡度 / 下载 / 高程…），
会被 `_force_analysis` 直接旁路 —— 所以它**测不出意图判断的真实水平**。
本脚本用 `bench/intent_testset.json`（46 条不含任何关键词的改写问法 + 10 条含关键词对照）
来测。

对比的方法臂
------------
| 臂   | 规划器 4B 权重 | 意图怎么判                      | 属于哪条路线 |
|------|----------------|---------------------------------|--------------|
| M1   | **不动**       | 底座模型 + 现有 intent.txt       | 方案1 现状   |
| M2   | **不动**       | 底座模型 + 改进版提示词          | 方案1 提示词工程 |
| M3   | **不动**       | 专用小分类器（向量 + 逻辑回归）  | 方案1 小分类器 |
| M4   | **被微调**     | 意图微调模型 + 现有 intent.txt   | 方案2 微调   |

每个臂再分「裸用」和「叠加正则安全网 `_force_analysis`」两种部署形态。
安全网命中时直接判 analysis 并**跳过**模型调用 —— 所以「+网」形态的模型调用次数更少。

用法
----
    python bench/eval_intent_methods.py --model-base <基础模型.gguf> \
                                        --model-tuned <意图微调模型.gguf> \
                                        --out bench/eval_results/intent_methods.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "bench"))

from app.agent.nodes.planner import _force_analysis, extract_json  # noqa: E402

INTENTS = ("analysis", "knowledge", "action", "refuse", "chat")
PROMPTS_DIR = REPO / "backend" / "app" / "agent" / "prompts"
TESTSET = REPO / "bench" / "intent_testset.json"

# 与部署侧 _test_intent.py 同款的视图上下文，保证测试条件接近真实
VIEW_CONTEXT = (
    "当前视野范围：西 102.80，南 30.90，东 103.00，北 31.10\n"
    "中心点：102.90, 31.00\n"
    "覆盖面积约 380 平方公里\n"
    "视野中心落在地名词典收录的：四姑娘山"
)


def parse_intent(text: str):
    """从模型输出里抠出 intent。

    ⚠ 关键：绝不能退化成「文本里出现某个词就算」—— 案例 1 就是这么把
    「模型答非所问」误判成「模型能力为 0」的。这里要求：
      1. 能解析出合法 JSON 且 intent 取值合法 → 用它；
      2. 否则，文本里**恰好只出现一个**合法意图词 → 用它（容忍模型多说了几句）；
      3. 否则返回 None（宁可不判，也不瞎猜）。
    """
    obj = extract_json(text or "")
    if isinstance(obj, dict):
        v = str(obj.get("intent") or "").strip().lower()
        if v in INTENTS:
            return v
    found = re.findall(r"\b(analysis|knowledge|action|refuse|chat)\b", text or "")
    uniq = set(found)
    return found[0] if len(uniq) == 1 else None


def build_prompt(template_path: Path, query: str) -> str:
    """按部署侧 classify_intent 的同样方式渲染提示词。"""
    tpl = template_path.read_text(encoding="utf-8")
    prompt = tpl.replace("{{VIEW_CONTEXT}}", VIEW_CONTEXT).replace("{{QUERY}}", query)
    try:
        from app.agent.gazetteer import get_gazetteer

        annotated = get_gazetteer().annotate(query)
        if annotated and annotated != query:
            prompt += "\n\n" + annotated
    except Exception:  # noqa: BLE001
        pass
    return prompt


def ask_llm(llm, template_path: Path, query: str, max_tokens: int, errbox: list) -> str:
    prompt = build_prompt(template_path, query)
    for _ in range(2):
        try:
            resp = llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=max_tokens,
            )
            return resp.content or ""
        except Exception as exc:  # noqa: BLE001
            # 把异常记下来 —— 之前这里静默 return ""，导致"模型全判成 None"
            # 被误读成"模型判断力为 0"，实际是调用直接报错。
            errbox.append(f"{type(exc).__name__}: {exc}")
            time.sleep(1.0)
    return ""


def run_llm_arm(llm, tag: str, template_path: Path, items, max_tokens, cache: dict) -> dict:
    """跑一个「模型 + 提示词」臂，返回 {id: intent}。带缓存，重跑不重复请求。

    缓存里**同时存原始输出**，这样判定异常时能直接看模型到底说了什么，
    而不是只看到一个 None。
    """
    preds = {}
    errbox: list[str] = []
    n_new = 0
    for it in items:
        key = f"{tag}::{it['id']}"
        ent = cache.get(key)
        if isinstance(ent, dict):
            preds[it["id"]] = ent.get("pred")
            continue
        raw = ask_llm(llm, template_path, it["query"], max_tokens, errbox)
        pred = parse_intent(raw)
        cache[key] = {"pred": pred, "raw": (raw or "")[:800]}
        preds[it["id"]] = pred
        n_new += 1
        if n_new % 10 == 0:
            print(f"    [{tag}] 已请求 {n_new} 条…", flush=True)
    if errbox:
        print(f"    ⚠️ {tag} 出现 {len(errbox)} 次调用异常，例如：{errbox[0][:200]}")
    n_none = sum(1 for v in preds.values() if v is None)
    if n_none:
        sample = next((cache[f"{tag}::{i['id']}"]["raw"]
                       for i in items if preds.get(i["id"]) is None), "")
        print(f"    ⚠️ {tag} 有 {n_none}/{len(items)} 条解析不出意图。原始输出示例：\n"
              f"        {sample[:300]!r}")
    print(f"    [{tag}] 本轮新请求 {n_new} 条（缓存命中 {len(items) - n_new} 条）")
    return preds


def score(preds: dict, items) -> dict:
    """按子集统计准确率。preds 为 None 表示"模型没给出判断"。"""
    out = {}
    for sub in ("all", "paraphrase", "keyword"):
        sel = [it for it in items if sub == "all" or it["subset"] == sub]
        if not sel:
            continue
        hit = sum(1 for it in sel if preds.get(it["id"]) == it["expected"])
        n_none = sum(1 for it in sel if preds.get(it["id"]) is None)
        out[sub] = {"n": len(sel), "acc": hit / len(sel), "no_answer": n_none}
    return out


def all_analysis(items) -> dict:
    """退化解：一律判 analysis。用来标定「不判断」能拿多少分。"""
    return {it["id"]: "analysis" for it in items}


def load_intent_train():
    """v1 意图训练集（720 条），用于训练专用小分类器。"""
    rows = json.loads((REPO / "bench" / "sft_data" / "train.json").read_text(encoding="utf-8"))
    xs, ys = [], []
    for r in rows:
        msgs = r["messages"]
        q = msgs[1]["content"]
        lab = json.loads(msgs[2]["content"])["intent"]
        if q and lab in INTENTS:
            xs.append(q)
            ys.append(lab)
    return xs, ys


def train_linear_classifier():
    """专用小分类器：bge 向量 + 多项逻辑回归（自己用 numpy 实现，不依赖 sklearn）。

    为什么这样选：
      - 它**不碰 4B 规划器的任何一个权重**，从物理上不可能像 LoRA 那样把规划能力带坏；
      - 24M 参数的小模型只做一件事（分类），容量不会被浪费在别处；
      - 训练成本近乎为零（几秒）。
    """
    import numpy as np

    from app.rag.embed import LlamaCppEmbedder

    emb = LlamaCppEmbedder()
    xs, ys = load_intent_train()
    print(f"  小分类器训练集：{len(xs)} 条，类别分布 "
          f"{ {k: ys.count(k) for k in INTENTS} }", flush=True)
    X = np.asarray(emb.embed_documents(xs), dtype=np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
    Y = np.zeros((len(ys), len(INTENTS)), dtype=np.float32)
    for i, lab in enumerate(ys):
        Y[i, INTENTS.index(lab)] = 1.0

    rng = np.random.default_rng(0)
    W = rng.normal(0, 0.01, (X.shape[1], len(INTENTS))).astype(np.float32)
    b = np.zeros(len(INTENTS), dtype=np.float32)

    # 梯度下降 + L2 正则（权重衰减），学习率手调，1000 轮足够收敛
    lr, l2, steps = 0.5, 1e-4, 1000
    for s in range(steps):
        logits = X @ W + b
        logits -= logits.max(axis=1, keepdims=True)
        p = np.exp(logits)
        p /= p.sum(axis=1, keepdims=True) + 1e-9
        g = (p - Y) / len(X)
        W -= lr * (X.T @ g + l2 * W)
        b -= lr * g.sum(axis=0)
    return emb, X, W, b


def run_classifier_arm(emb, W, b, items):
    import numpy as np

    Z = np.asarray(emb.embed_documents([it["query"] for it in items]), dtype=np.float32)
    Z /= np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9
    pred = (Z @ W + b).argmax(axis=1)
    return {it["id"]: INTENTS[p] for it, p in zip(items, pred)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-base", default="", help="底座模型 GGUF")
    ap.add_argument("--model-tuned", default="", help="意图微调模型 GGUF")
    ap.add_argument("--n-ctx", type=int, default=4096)
    ap.add_argument("--max-tokens", type=int, default=64)
    ap.add_argument("--cache", default=str(REPO / "bench" / "eval_results" / "_intent_cache.json"))
    ap.add_argument("--out", default=str(REPO / "bench" / "eval_results" / "intent_methods.json"))
    ap.add_argument("--skip-llm", action="store_true", help="只跑小分类器与安全网")
    args = ap.parse_args()

    items = json.loads(TESTSET.read_text(encoding="utf-8"))["items"]
    print(f"测试集：{len(items)} 条（paraphrase {sum(1 for i in items if i['subset']=='paraphrase')} / "
          f"keyword {sum(1 for i in items if i['subset']=='keyword')}）")

    cache = {}
    cp = Path(args.cache)
    if cp.exists():
        cache = json.loads(cp.read_text(encoding="utf-8"))

    results = {}   # 臂名 -> 分数
    preds_store = {}

    # ---------- 正则安全网本身 ----------
    net = {it["id"]: ("analysis" if _force_analysis(it["query"]) else None) for it in items}
    preds_store["M0 正则安全网（单独）"] = net
    results["M0 正则安全网（单独）"] = score(net, items)

    # ---------- 退化解，用于标定 ----------
    preds_store["D  一律判 analysis"] = all_analysis(items)
    results["D  一律判 analysis"] = score(all_analysis(items), items)

    os.environ.setdefault("TMP", "D:/llama_build/tmp")
    os.environ.setdefault("TEMP", "D:/llama_build/tmp")

    def with_net(preds):
        return {it["id"]: ("analysis" if _force_analysis(it["query"]) else preds.get(it["id"]))
                for it in items}

    # ---------- LLM 臂 ----------
    if not args.skip_llm:
        # 用**项目自己的客户端**而不是裸 Llama：它负责关掉推理模型的思考模式
        # （Qwen3.5 的 chat template 在思考开启时会注入 <think>，导致输出里
        #  根本没有 JSON），并且统一了 chat handler 与停止符。
        from app.agent.llm import EmbeddedLlamaClient

        arms = []
        if args.model_base:
            arms += [
                ("M1 底座+现有提示词", args.model_base, PROMPTS_DIR / "intent.txt"),
                # M2 把原提示词里"出现关键词就判 analysis"那条**整段换掉**了，
                # 结果关键词类从 100% 掉到 60% —— 属于过度改动。
                ("M2 底座+改写版提示词", args.model_base,
                 REPO / "bench" / "intent_prompt_v2.txt"),
                # M2b 保留原提示词的全部规则，只在后面**追加**一段改写示例。
                ("M2b 底座+现有提示词+改写示例", args.model_base,
                 REPO / "bench" / "intent_prompt_v2b.txt"),
            ]
        if args.model_tuned:
            arms += [("M4 微调模型+现有提示词", args.model_tuned, PROMPTS_DIR / "intent.txt")]

        cur_model = None
        llm = None
        for name, mpath, tpl in arms:
            if mpath != cur_model:
                print(f"\n>>> 加载模型 {Path(mpath).name}", flush=True)
                llm = EmbeddedLlamaClient(model_path=mpath, n_ctx=args.n_ctx,
                                          n_gpu_layers=-1, verbose=False)
                cur_model = mpath
            print(f"\n>>> 跑臂：{name}", flush=True)
            t0 = time.perf_counter()
            raw = run_llm_arm(llm, name.split()[0], tpl, items, args.max_tokens, cache)
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"    用时 {time.perf_counter()-t0:.0f}s")
            preds_store[name] = raw
            results[name] = score(raw, items)
            preds_store[name + " +正则网"] = with_net(raw)
            results[name + " +正则网"] = score(with_net(raw), items)
            # 每个臂跑完立刻落盘，避免中途崩了全丢
            _dump(preds_store, results, items, args.out)

    # ---------- 专用小分类器 ----------
    print("\n>>> 训练专用小分类器（bge 向量 + 逻辑回归）", flush=True)
    try:
        emb, _X, W, b = train_linear_classifier()
        clf = run_classifier_arm(emb, W, b, items)
        preds_store["M3 专用小分类器"] = clf
        results["M3 专用小分类器"] = score(clf, items)
        preds_store["M3 专用小分类器 +正则网"] = with_net(clf)
        results["M3 专用小分类器 +正则网"] = score(with_net(clf), items)
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ 小分类器失败：{type(exc).__name__}: {exc}")

    _dump(preds_store, results, items, args.out)

    # ---------- 打印 ----------
    print("\n" + "=" * 88)
    print(f"{'方法臂':<34}{'全体':>10}{'改写问法':>12}{'含关键词':>12}{'未作答':>10}")
    print("-" * 88)
    for name, sc in results.items():
        a = sc.get("all", {})
        p = sc.get("paraphrase", {})
        k = sc.get("keyword", {})
        na = sum(v["no_answer"] for v in sc.values())
        print(f"{name:<34}{a.get('acc', 0):>10.1%}{p.get('acc', 0):>12.1%}"
              f"{k.get('acc', 0):>12.1%}{na:>10}")
    print("=" * 88)
    return 0


def _dump(preds_store, results, items, out_path):
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps({
        "testset": str(TESTSET),
        "results": results,
        "predictions": preds_store,
        "items": [{"id": i["id"], "subset": i["subset"], "expected": i["expected"],
                   "query": i["query"]} for i in items],
    }, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
