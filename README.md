# content-judge

内容质量评分、编造检测与问题定位器（Quality Assessment & Issue Locator）。

## 核心职责

1. **客观项走正则 / 确定性断言**：字数区间、代码块数、技术符号守恒、通用编造检查（Issue 编号 / 版本号 / Commit SHA 等在素材中是否存在）。零 LLM、零随机、零成本。
2. **段落级 Issue 定位**：每个违规项附带 `location`（段落索引）、`evidence`（证据片段）与 `severity`（BLOCKING / HIGH / MEDIUM / LOW），供下游 `content-writer` 定向修复。
3. **输出标准化分档 Verdict**：S / A / B / C 四档判定，高危/阻断项一票否决降至 C 档。
4. **可插拔领域 Specs 库**：
   - `BLOG_ERROR`：技术排障博客 Spec（字数、代码块、技术符号、假数据阻断）
   - `SPEC_BY_KIND` (`daily` / `weekly` / `preview`)：量化 PK 短视频口播 Spec（身份句、预测情绪词差集过滤、行间自复读、跨期重合度）

## 快速上手

```python
from content_judge import judge
from content_judge.specs import BLOG_ERROR

verdict = judge(
    text=generated_article,
    spec=BLOG_ERROR,
    source=raw_source_material,
    symbols=["--use-ck-attention", "ComfyUI"],
)

print(verdict.format())
print(f"得分: {verdict.total}/{verdict.full} (等级: {verdict.tier})")

if verdict.blocking:
    print("阻断问题:", [i.detail for i in verdict.blocking])
```

## 测试

```bash
pytest tests/
```

## 设计原则

- **评分解耦**：LLM 仅可做 0/1 事实判定，分数由 Python 死公式计算。
- **宁缺毋滥**：客观项 100% 确定可复现，不可测或失真指标坚决不加。
- **闸门与 Prompt 配对**：Prompt 未明确要求的约束，Spec 中严禁单方面加闸。
