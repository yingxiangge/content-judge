"""用真实博客产出验证：判分能区分好坏，客观项零随机、零成本。"""
from content_judge import judge
from content_judge.specs import BLOG_ERROR

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


class TestBlogJudge:
    def test_good_vs_thin_score_distinction(self):
        g = judge(GOOD, BLOG_ERROR, source=SOURCE, symbols=SYMBOLS)
        t = judge(THIN, BLOG_ERROR, source=SOURCE, symbols=SYMBOLS)
        assert g.total > t.total
        assert g.tier in ("S", "A")
        assert t.tier in ("B", "C")

    def test_fabricated_number_triggers_blocking_issue(self):
        f = judge(FAKED, BLOG_ERROR, source=SOURCE, symbols=SYMBOLS)
        assert any(i.kind.startswith("fabricated") for i in f.blocking)
        assert f.tier == "C"

    def test_good_content_has_no_blocking_issues(self):
        g = judge(GOOD, BLOG_ERROR, source=SOURCE, symbols=SYMBOLS)
        assert not g.blocking

    def test_issues_have_location_or_evidence(self):
        f = judge(FAKED, BLOG_ERROR, source=SOURCE, symbols=SYMBOLS)
        assert all(i.location is not None or i.evidence
                   for i in f.issues if i.severity.value == "high")

    def test_objective_deterministic_reproducibility(self):
        g1 = judge(GOOD, BLOG_ERROR, source=SOURCE, symbols=SYMBOLS)
        g2 = judge(GOOD, BLOG_ERROR, source=SOURCE, symbols=SYMBOLS)
        assert g1.total == g2.total
