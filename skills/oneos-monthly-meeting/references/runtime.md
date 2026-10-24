# 运行与交付（给执行 AI）

使用者不需要执行下面的命令。由你发现已安装的技能绝对路径，检查运行环境，创建私有工作目录，填写内部数据并执行。

## 依赖

- Python 3.10+；依赖在本技能根目录 `requirements.txt`。
- `ffmpeg` 和 `ffprobe` 在 PATH 中，支持 H.264/AAC。
- 中文字库：优先本机 Hiragino Sans GB，其次 Microsoft YaHei 或 Noto Sans CJK。允许 `--font` 指定可用字库；需要核对全部字符，不允许用方框代替。
- 联网 Edge TTS。固定 `zh-CN-XiaoxiaoNeural`、`+20%`、`-2Hz`。仅向语音服务提交已脱敏口播，不提交附件、截图、来源台账或隐私。

优先复用 Codex 提供的依赖运行时；否则在本技能或任务工作目录新建独立虚拟环境，安装 `requirements.txt`。不改其他项目依赖、不分发字体、不写死创建者机器路径或代理地址。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Windows 使用虚拟环境的 `Scripts/python.exe`。FFmpeg 缺失时先发现可用安装方式；需要管理员权限或策略不允许时说明具体阻塞，不宣称视频已生成。

## 私有工作目录

原始材料、截图、内部来源表、manifest 放在任务私有目录中，不能放公开仓库。源与最终目录分开。输出目录使用新的空目录，避免误覆盖先前成果。

构建 JSON 由 AI 自动建立，见 [manifest.md](manifest.md)。审核字段意味着实际完成了审查，不能为了通过脚本机械设为 true。

## 调用

在技能目录运行（实际使用时将路径替换为你发现的绝对路径）：

```bash
python scripts/build.py /private/work/manifest.json --output /private/deliverables/monthly-report
```

必要时使用 `--font /path/to/cjk-font.ttc`。`--skip-video` 仅用于提前检查图片和PPT；最终交付需要不带该参数重建。

`--no-audio` 是明确标识的草稿模式，用于网络或配音依赖未就绪时看版式，不能作为完整交付。不要用系统发声或静音文件冒充指定音色。失败时保留已有安全稿、报告真正原因，再修复重试；不能修改业务事实来绕过失败。

## 成品目录

| 文件 | 用途 |
| --- | --- |
| `report.pptx` | 静态高清页面 PPT |
| `report-with-audio.pptx` | 逐页内嵌声音及自动切页时序 |
| `report-4k.mp4` | 默认主播放文件，4K、30fps、无字幕 |
| `narration.wav` | 与页面时序一致的完整声音 |
| `script.md` | 逐页口播和时间信息 |
| `slides/` | 逐页4K图片 |
| `audio/` | 逐页声音 |
| `screenshots/` | 仅包含已永久脱敏的截图 |
| `qa.json` | 实际媒体参数、页时长和结构检查 |

文件存在并不等于检查通过。总时长超过编辑目标时先精简，再生成；用户明确硬时限时必须满足。不得直接剪掉句尾音频。

## 最后检查

1. 看每页完整图片，放大截图和掩码；核对月份、状态、数字、错字和溢出。
2. 听完整配音，检查简称、数字和多音字；视频开头、中间、末尾与各页切换一致。
3. 读取 `qa.json` 与 ffprobe 实际输出，确认4K/30fps/H.264/AAC/无字幕、时长和音画一致。
4. 检查 PPT 中的音频关系、时序和安全图片；原图、原始JSON、来源路径均不进入成品。
5. 在实际可用的 PowerPoint/WPS 放映检查自动播声与翻页。未试播时如实写明；结构检查不能代替演示机兼容性验证。
6. 打包只取上述安全文件。发送沿用本轮授权；生成请求本身不授予群发或公开发布每月材料的权限。

技能包可公开，真实业务材料及成品的共享范围按本次授权执行。不要把这两种权限混在一起。
