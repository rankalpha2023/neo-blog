---
title: "quasivision：给 LLM 装上廉价的眼睛，让它先看见再说"
description: "当所有人都在把图片喂给多模态大模型时，quasivision 选择了一条相反的路径——用纯本地 Rust 引擎做视觉感知，不用理解、只需看见。本文深入剖析其五层感知架构、Rust 选型逻辑与 MCP Tool 集成方案。"
pubDate: 2026-06-09
tags: ["AI", "工具", "视觉", "Rust", "MCP", "LLM"]
draft: false
category: "tools"
---

## 一个不对劲的共识

AI 圈有个默认的肌肉记忆：**只要提到"给 AI 看图片"，所有人条件反射——"用 VLM 啊，GPT-4V、Claude Vision、Qwen-VL"。**

但绝大多数场景真的需要大模型来"理解"图片吗？

三个典型场景：

| 场景 | VLM 方案 | quasivision 方案 |
|---|---|---|
| 截图里有文字，你想让 AI 读 | 上传图片→多模态推理→提取文字→返回 | 本地 OCR→文字提取→返回 |
| 1000 张 PDF 截图批量转 Markdown | API 调用 1000 次→几百块钱→等半小时 | `cargo run -- -i ./screenshots/ --recursive`→零成本→几秒 |
| 想知道页面上有哪些按钮、分别在什么坐标 | 大模型"看"图→输出可能对也可能错→每次都花钱 | 本地结构化提取→稳定坐标+分类→喂给 LLM 当上下文 |

**发现没？大多数时候根本不需要"理解"，只需要"看见"。**

就像你不需要哈佛博士帮你读路牌——你需要的是视力 5.0 的路人，看一眼然后告诉你"前方 500 米右转"。quasivision 就是这个路人。

[quasivision](https://github.com/WeiChens/quasivision) 是一个 Rust 编写的本地视觉感知引擎，它不做语义理解，只做精确的结构化感知——文字识别、UI 组件检测、物体检测、图标分类、颜色提取。这个定位精准得像一把手术刀：**VLM 当大脑，我当眼睛**。

---

## 架构：LLM 下方的感知层

quasivision 被设计为一个**基础设施层的工具**，它的位置不是"替代 VLM"，而是"填 VLM 下方的空"：

```
┌─────────────────────────────────────────────┐
│            LLM（GPT / Claude / 本地模型）      │
├─────────────────────────────────────────────┤
│          🔧 MCP / AI Tools 层               │
├─────────────────────────────────────────────┤
│     👁️ quasivision（本地视觉感知引擎）        │
│     ├─ 文字识别（PaddleOCR PP-OCRv5）        │
│     ├─ UI 组件检测（7 类元素）                │
│     ├─ 物体检测（860 类日常物体, YOLOE-26n）  │
│     ├─ Icon 含义分类（81 种）                 │
│     └─ 颜色提取                              │
├─────────────────────────────────────────────┤
│          输入：一张图片                       │
│          输出：结构化 JSON + 文本 Tree         │
└─────────────────────────────────────────────┘
```

它的"眼睛是假的"——看不懂设计风格、读不懂情绪、不知道隐喻。但它能精确告诉你：

- 这里有文字："提交"
- 这里有按钮：坐标 `[100,200, 300,250]`
- 这里有物体：人（87%置信度），戴着帽子
- 这里有图标：搜索

**很多场景下，"看见了表面"就已经够了。** 你给 LLM 的不是一张模糊的 JPG，而是精确的结构化上下文。

---

## 五感：比 VLM 更细粒度的感知

quasivision 把自己的感知能力拆成五个独立模块，每个都输出结构化数据而非自然语言：

### 1. UI 元素检测（主视觉）

把截图拆碎成组件树——7 类元素，像素级坐标：

```
Root (1280×800)
├── Block: 导航栏
│   ├── Icon: logo
│   ├── Text: "首页"
│   └── Button: "登录"
├── Block: 搜索区域
│   ├── Input: 搜索框
│   └── Button: "搜索"
└── Block: 结果列表
    ├── Block: 结果项 1
    │   ├── Text: "标题..."
    │   └── Text: "描述..."
    └── Block: 结果项 2
```

这不是"模型觉得这可能是个按钮"。这是边界检测 + 连通域分析 + 规则分类的确定性产出——**每次运行结果一致，无幻觉**。

### 2. OCR 文字识别

基于 PaddleOCR PP-OCRv5，中英文识别，Windows 上 DirectML GPU 加速。关键细节：长文本（>5 字符）自动绕过高度限制过滤器，防止正文被误杀。

### 3. 物体检测（YOLOE-26n）

860 类日常物体，自动构建父子包含关系树：

```
Objects — 6 found:
└─ [0,278 433×436] person (87%)
   ├─ [111,277 118×93] cap (39%)
   │  └─ [111,277 118×93] hat (82%)
   │     └─ [112,345 88×38] glasses (65%)
   ├─ [1,649 46×65] glove (21%)
   └─ [55,342 373×372] jacket (20%)
```

模型只有 11.1 MB——比上代 YOLO-World（49.5 MB）小 77%，ONNX Runtime 推理，端到端 NMS。

### 4. Icon 含义分类

不是图像分类，是**语义层分类**。81 种常见 UI 图标：设置、搜索、分享、返回、菜单、收藏……置信度 >40% 展示候选含义。模型同样是 ONNX，跑在本地。

### 5. 颜色检测

每个元素的前景色/背景色，十六进制输出。对 UI 自动化尤其有用。

---

## 为什么是 Rust？

如果只是"调一下 OpenCV"，Python 也行。但 quasivision 的野心是**系统级 AI Tools 基础设施**：

**零依赖部署。** Python 方案需要 `pip install torch → opencv → onnxruntime → paddleocr → 解决 CUDA 版本冲突`。quasivision 方案：`cargo run -- --input 图片.png`，或者编译完一个二进制扔过去。没有 Python 环境、没有 Node.js、没有依赖地狱。

**编译期跨平台适配。** 通过 Cargo 的条件编译：

```toml
[target.'cfg(target_os = "windows")'.dependencies]
oar-ocr = { version = "0.6", features = ["directml"] }

[target.'cfg(target_os = "macos")'.dependencies]
oar-ocr = { version = "0.6", features = ["coreml"] }
```

Windows 用 DirectML、macOS 用 CoreML、Linux 走 CPU 优化，全部编译期自动选择。开发者只管写 `cargo run`。

**性能。** Rust 的零成本抽象 + ONNX Runtime 原生绑定 = 推理性能对标 C++，内存安全由编译器保障。模型文件（YOLOE-26n 11 MB）支持动态输入，端到端 NMS，与主流程并行执行——物体检测和 OCR 在后台线程跑，不增加额外等待。

**一句话**：这不是"用 Rust 重写了 Python 脚本"，而是为"作为系统级工具被四处集成"而设计的。

---

## 输出设计：实用主义的胜利

quasivision 的输出走的是少即是多路线——没有 `--format json|yaml|xml|csv` 这种排列组合，每个图片就两套文件：

| 文件 | 用途 |
|---|---|
| `elements.tree.json` | JSON 树结构，给程序/AI 吃 |
| `elements.tree.txt` | 纯文本树，给人看，也可以粘进 prompt |
| `visualization.jpg` | UI 边框标注图，不同颜色区分类型 |
| `objects.tree.json` | 物体检测 JSON 树 |
| `objects.tree.txt` | 物体检测文本 |
| `objects.jpg` | 物体检测可视化 |

坐标用原始像素值，不做 0-1000 归一化。需要归一化坐标喂给 LLM？下游自己除一下图片宽高，一行代码的事。

这种设计取舍的背后是：**少一个选择，少一个心智负担。** 固定输出，拿到就能用。不做过度设计。

---

## 黄金场景：quasivision 真正发光的地方

### 批量图片 OCR

100 张 PDF 截图要提取文字？

```bash
cargo run -- -i ./docs/ --recursive
```

不上传云端 OCR 服务，不花一分钱 API 费。本地一次跑完，结构化数据直接喂下游。

### 做 MCP Tool

把 quasivision 封装成 MCP Server——LLM 需要"看图"时自动调用：

```
用户：这个页面的按钮在哪里？
LLM → 调用 quasivision → 获取结构化 UI 树 → 告诉你按钮坐标和文字

用户：这张照片里有什么？
LLM → 调用 quasivision → 获取物体检测结果 → 列出所有物体，带坐标
```

**关键优势**：不需要网络、不需要 API Key、没有速率限制。LLM 可以免费地、无限次调用本地视觉能力。这是 VLM 永远做不到的。

### 系统级 AI 工具

因为是纯 Rust 二进制，可以集成到操作系统层面：

- 全局快捷键截图 → 自动 OCR → 粘贴到剪贴板
- 窗口内容监控 → 实时提取 UI 结构 → 驱动自动化脚本
- 文件管理器右键 → "一键提取图片文字"

这些场景依赖 VLM 根本不可行——延迟和成本无法接受。quasivision 足够轻、足够快、足够便宜。

### 参数调优参考

```bash
# App 截图（推荐参数）
cargo run -- -i app.png --gradient 4

# Web 页面
cargo run -- -i webpage.png --gradient 1 --rec-corner-skip 0.1

# 批量递归
cargo run -- -i ./screenshots/ --recursive

# 高召回物体检测
cargo run -- -i photo.jpg --detect-conf 0.1

# 带段落合并的文档
cargo run -- -i document.png --paragraph true --text-max-h 0.15
```

---

## 诚实地说：quasivision 不是 VLM 替代品

必须把这个说清楚——**它们不在一个赛道上**。

| 维度 | VLM | quasivision |
|---|---|---|
| 理解深度 | 能懂情绪、风格、隐喻、图表逻辑 | 只看表面：文字、物体、坐标 |
| 输出形式 | 自然语言，灵活但有幻觉 | 结构化 JSON/Tree，精确、稳定 |
| 坐标精度 | 模糊，依赖推理 | 像素级，每次一致 |
| 运行环境 | 云端 API 或超大本地模型 | 纯本地，一个二进制 |
| 调用成本 | 按 token 计费 | 一次编译，无限使用，零边际成本 |
| 处理速度 | 秒级响应，批量排队 | 毫秒级 UI 检测，批量一键跑完 |
| 隐私安全 | 图片上传云端 | 完全离线，数据不出机器 |
| 零样本适应 | 没见过也能理解 | 依赖规则和训练数据 |

**怎么选？**

| 场景 | 选谁 |
|---|---|
| 这张图表达了什么情绪？ | VLM |
| 把这个截图里的文字提取出来 | quasivision |
| 分析图表的数据趋势 | VLM |
| 这一千张图里有哪些按钮？ | quasivision |
| 这个按钮的精确坐标和颜色是什么？ | quasivision |
| 给我描述这张照片 | VLM |
| 照片里所有物体列出来，带坐标 | quasivision |

VLM 是"博士生看图写作文"，quasivision 是"视力 5.0 的路人指路"。博士生能写诗，但指路——又快又准还便宜的路人才是日常刚需。

**最好的架构：VLM 做大脑做决策，quasivision 做眼睛做感知。各司其职。**

---

## 一行命令上手

```bash
git clone https://github.com/WeiChens/quasivision.git
cd quasivision
cargo run -- --input demo/ui.jpg
```

首次运行会自动从 Hugging Face 下载模型。国内用户：

```bash
set QUASIVISION_MODELS_URL=https://hf-mirror.com/WeiChens/quasivision-models/resolve/main
cargo run -- --input demo/ui.jpg
```

项目 MIT 开源，5 个模型文件不到 20 MB——一个真正轻量的、能嵌入任何工具链的视觉感知层。如果你在做 MCP Tools、AI Agent、UI 自动化，quasivision 不一定最聪明，但它一定是你工具箱里最务实的选择。