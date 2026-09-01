# content-judge

> **Decoupled LLM-as-a-Judge & Deterministic Quality Guardrails**  
> 零外部运行时依赖（Zero Runtime Dependencies）的高性能内容质量评估、编造拦截与问题定位引擎。

---

## 🎯 为什么需要 content-judge？

在 LLM 生成内容的工业级流水线中，传统让 LLM “直接打分”的方法存在三大致命缺陷：
1. **分数漂移（Score Drift）**：同一段内容不同时刻打分波动极大；
2. **高分幻觉（Polite Hallucination）**：LLM 倾向于给客套的高分，无法硬拦截缺少必要技术符号、编造 Issue 编号等客观硬伤；
3. **成本与延迟（Cost & Latency）**：简单的字数/符号/格式校验如果全走 LLM，会浪费大量 Token 并增加数百毫秒延迟。

**`content-judge` 的核心哲学：评分解耦（Decoupled Evaluation）**
- **LLM 只做 0/1 事实判定**：负责语义理解与二值事实推断；
- **Python 确定性计算分数**：根据预设 Spec 权重和硬门禁公式死算得分；
- **纯客观项零 LLM**：字数区间、代码块守恒、技术符号守恒、通用编造检查（Issue 编号 / 版本号 / Commit SHA）走极速确定性断言。

---

## 🚀 特性

- ⚡ **零运行时依赖**：基于 Python 标准库构建，安装即用，毫秒级执行；
- 🛡️ **分级硬门禁（Blocking Issues）**：关键合规/真实性问题一票否决降级（S/A/B/C 四档判据）；
- 📍 **段落级 Issue 定位**：违规项附带 `location`（段落索引）、`evidence`（证据片段）与 `severity`，供下游 Agent 精准定向重写；
- 🧩 **可插拔领域 Specs 库**：
  - `BLOG_ERROR`：技术排障/深度技术文章 Spec（字数、代码块、技术符号守恒、假数据拦截）；
  - `X_REPLY`：社交技术回帖 Spec（Anti-slop 废话拦截、量化/增长虚假指标过滤、Builder 现实检验）；
  - `content_potential`：内容传播潜力与选题硬门筛选（淘汰缺乏传播结构的原料）。

---

## 📦 快速上手

### 安装

```bash
pip install -e .
```

### 示例 1：技术排障博客质量门禁

```python
from content_judge import judge
from content_judge.specs import BLOG_ERROR

generated_text = """
# Next.js 15 SSR Bug Reproduction

When deploying with `output: 'standalone'`, we encountered `ERR_INVALID_URL`.
The fix is adding `--registry` to the build step.
"""

verdict = judge(
    text=generated_text,
    spec=BLOG_ERROR,
    symbols=["output: 'standalone'", "ERR_INVALID_URL"],
)

print(f"评级: {verdict.tier} ({verdict.total}/{verdict.full}分)")
if verdict.blocking:
    print("阻断项:", [i.detail for i in verdict.blocking])
```

### 示例 2：社交技术回复 Anti-slop 与防编造检查

```python
from content_judge import judge
from content_judge.specs import X_REPLY

reply_text = "We tested DeepSeek caching on 100 chapters. Cache hit reduces cost by 90%."
source_tweet = "How are you handling LLM costs in production?"

verdict = judge(
    text=reply_text,
    spec=X_REPLY,
    source=source_tweet,
    context={"source": source_tweet},
)

print(verdict.format())
```

---

## 🧪 运行测试

```bash
pytest tests/
```

---

## 📐 设计原则

1. **评分解耦**：LLM 仅可输出 0/1 事实断言，禁止输出任意连续分值；
2. **宁缺毋滥**：客观项 100% 确定可复现，不可测或高方差指标坚决不入门禁；
3. **闸门与 Prompt 配对**：Prompt 未明确要求的隐性约束，Spec 中严禁单方面加硬闸。

---

## 📄 License

MIT License.
