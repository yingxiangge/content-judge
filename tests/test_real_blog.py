"""用今天博客产线的**两篇真实产出**验证：判分要能区分好坏。

· good —— 最后一跑：中文 1032 / 总长 2561 / 8 个代码块 / Reviewer 100 分
· thin —— 中间一跑：中文 448 / 4 个代码块，内容对但薄
· faked —— 在 good 基础上注入一个素材里没有的 issue 编号（真实发生过：
           模型编出 `Issue #15352`，而真实是 #15591）

只跑客观项，不调 LLM —— 这几项本来就该零随机、零成本。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from content_judge import judge  # noqa: E402
from content_judge.specs import BLOG_ERROR  # noqa: E402

SOURCE = (
    "/save fails with pull model manifest: file does not exist for "
    "nemotron-3.5-lightning (nemotron_h_moe arch). "
    "See https://github.com/ollama/ollama/issues/1770 . "
    "ollama show and run work, only /save fails. version 0.12.4"
)
SYMBOLS = ["manifest", "nemotron_h_moe", "/save", "nemotron-3.5-lightning"]

GOOD = """# Ollama /save 报错：本地 manifest 在，远端校验才是断点

这个 `/save` 报错不是 tag 拼错，也不是模型没拉全。

## 现象与证据

```bash
ollama run nemotron-3.5-lightning:30b
/save lightning-test
```

结果是：

```text
Error: pull model manifest: file does not exist
```

不管 `/save` 后面给什么名字，错误都在。模型本身能跑，其他读本地 manifest 的
命令也正常，只有 `/save` 炸。这个现象先把两个最常见的解释排除掉。

第一个是 tag 拼写错误。很多 `pull model manifest` 报错是 tag 不在远端，但这里
模型是刚 pull 成功的，`ollama list` 和 `run` 都认这个 tag，拼写错误不成立。
第二个是本地 manifest 损坏或缺失，但模型能正常加载，所以本地文件没丢。

于是重点落在 `/save` 的路径上。它不像 `run` 那样先读本地 manifest，而是复用了
`pull` 的远端查询逻辑。`nemotron_h_moe` 架构比较新，远端 manifest 里的架构字段
和 `/save` 预期对不上。这个结论是我根据报错串和行为推的，不是抓日志坐实的。

## 怎么绕过

```bash
cd /usr/share/ollama/.ollama/models
```

按目录结构重建 Modelfile，至少不阻塞你把这版权重固化成本地模板。

```bash
ollama create lightning-test -f Modelfile
```
""" + "这一段是为了凑够真实文章的长度而保留的正文叙述内容。" * 30

THIN = """# Ollama /save 报错

`/save` 失败但 `run` 正常。

```text
Error: pull model manifest: file does not exist
```

我的判断是问题出在远端 manifest 校验。这条没验证。
""" + "简短叙述。" * 20

FAKED = GOOD.replace("这个结论是我根据报错串",
                     "上游 Issue #15352 里也有人报了同样的问题，这个结论是我根据报错串")

FAIL = []


def check(name, cond, extra=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAIL.append(name)


def main():
    g = judge(GOOD, BLOG_ERROR, source=SOURCE, symbols=SYMBOLS)
    t = judge(THIN, BLOG_ERROR, source=SOURCE, symbols=SYMBOLS)
    f = judge(FAKED, BLOG_ERROR, source=SOURCE, symbols=SYMBOLS)

    print("\n【好文】"); print(g.format())
    print("\n【薄文】"); print(t.format())
    print("\n【注入假编号】"); print(f.format())

    print("\n【判定】")
    check("好文分数高于薄文", g.total > t.total, f"{g.total:.0f} > {t.total:.0f}")
    check("好文进 S/A 档", g.tier in ("S", "A"), f"tier={g.tier} ({100*g.total/g.full:.0f}%)")
    check("薄文落 B/C 档", t.tier in ("B", "C"), f"tier={t.tier}")
    check("假编号被抓为阻断问题", any(i.kind.startswith("fabricated") for i in f.blocking),
          f"{len(f.blocking)} 处阻断")
    check("假编号直接压到 C 档", f.tier == "C", f"tier={f.tier}")
    check("好文无阻断问题", not g.blocking)
    check("问题带定位", all(i.location is not None or i.evidence
                            for i in f.issues if i.severity.value == "high"))
    check("客观项可复现", judge(GOOD, BLOG_ERROR, source=SOURCE,
                                symbols=SYMBOLS).total == g.total)

    print("\n" + "=" * 58)
    print("❌ 失败: " + ", ".join(FAIL) if FAIL else "✅ 全部通过")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
