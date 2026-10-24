# 内部数据协议（AI 建立，使用者不用填写）

先完成内容筛选、事实核验、正文及口播脱敏，再创建 JSON。相对截图路径按 manifest 所在目录解析。内部来源表另外保存在私有目录，构建器不应把它复制到交付目录。

```json
{
  "title": "ONEOS 月度例会（虚构示例）",
  "month": "2026-10",
  "date": "2026年10月",
  "content_reviewed": true,
  "narration_reviewed": true,
  "slides": [
    {
      "kind": "cover",
      "title": "ONEOS 月度例会",
      "subtitle": "虚构示例",
      "narration": "下面汇报本月重点进展。"
    },
    {
      "kind": "contents",
      "title": "汇报目录",
      "bullets": ["重点建设"]
    },
    {
      "kind": "content",
      "chapter_number": 1,
      "title": "事项A进展",
      "status": "开发中",
      "bullets": ["用于简化日常协作。", "本月完成方案评审，进入开发阶段。"],
      "narration": "事项A用于简化协作，已完成方案评审，当前处于开发阶段。"
    }
  ]
}
```

## 字段

- `title`：本次报告名称；`month`、`date`：从真实材料确定。
- `content_reviewed`：你已经实际检查正文的真实性和披露范围，必须为 true。
- `narration_reviewed`：你已完成口播脱敏，联网生成声音前必须为 true。
- `slides`：有序页面；`title` 必填。
- `kind`：`cover`、`contents`、`chapter`、`content`、`metrics`、`plan`、`closing`。
- `subtitle`、`status`、`narration` 是字符串，`bullets` 是字符串数组。正式配音模式中，除目录外每页必须有口播；目录无旁白、停留3秒。
- `chapter_number`：对应目录的 1、2、3。章节页必须填写且标题匹配目录；正文、指标、计划页显式填写或继承前一章。第一个正文页必须指定。目录必须在正文前，顺序不得跳号或倒退，每章必须有正文。
- 正文大编号显示所属章节，旁边是章节名，页标题写具体工作；物理页码只放页脚。旧版 manifest 需补齐目录与章节归属。
- `narration` 中 ONEOS／One OS 自动替换为“系统”，正文品牌不变。脚本与实际配音使用替换后的同一文本。
- `max_duration_seconds`：可选，只有用户明确给硬时限时填写；普通月报不把历史105.514秒当硬上限。
- `metrics`：指标页1—3项，每项为 `{"value":"8","label":"示例指标","note":"虚构测试数字"}`。value为短字符串，真实使用必须有可靠口径。

各版式可用字段（均包含必填的 `kind` 和 `title`）：

| kind | 其他字段 |
| --- | --- |
| cover / closing | subtitle、narration |
| contents | bullets；narration 必须为空或省略 |
| chapter | chapter_number（必填）、narration |
| content / plan | chapter_number、subtitle、status、bullets、narration、screenshot |
| metrics | chapter_number、status、metrics、narration、screenshot；说明写在每个指标的 note 中，不混用 subtitle / bullets |

## 截图字段

只在截图已逐块检查后加入：

```json
{
  "path": "source/screen.png",
  "reviewed": true,
  "image_sha256": "由AI对已查看原图计算的64位SHA-256",
  "layout": "desktop",
  "redactions": [[120, 200, 240, 48], [700, 200, 180, 48]]
}
```

把这个对象作为对应页的 `screenshot`。示例哈希不是可执行值，必须计算原文件的真实哈希。矩形是原图像素坐标、正整数面积、不得越界；`redactions` 必须显式给出，只有确认整图无敏感内容才允许空数组。手机截图设置 `layout: "phone"`。

脚本会先打码、重编码、再缩放并嵌入。哈希不符意味着原图变化，必须重新查看，不自动改哈希来绕过。字数过长、字符缺失或不支持字段导致失败时，按报错修复，不静默丢内容。

## 审核字段的证据

布尔值只供脚本检查流程，不证明内容自动安全。私有工作记录至少注明：读取过的材料、冲突处理、哪些内容删减／匿名、截图敏感区域检查结果、何时查看过脱敏图。不得把源隐私值写入公开测试或成品审核报告。

## 计划页编排

计划页放在下月目标章。通常一页用三个短段说明三批上线模块，长时可分三页，但都使用同一章节号。里程碑的模块、范围和日期来自使用者提供内容，来源映射留在私有依据，构建器不替代 AI 的事实核验。
