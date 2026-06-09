---
title: "不用 VLM 也能看懂屏幕：quasivision 的确定性视觉管线是怎么工作的"
description: "翻开 quasivision 的源码才发现，这个 Rust 项目做了一件反直觉的事——在 2026 年用几何规则做 UI 元素分类，而不是上 VLM。本文从管线代码入手，拆解它为什么选择确定性方案，以及这对 AI Agent 意味着什么。"
pubDate: 2026-06-09
tags: ["AI", "Rust", "计算机视觉", "Agent", "开源"]
draft: false
category: "engineering"
---

## 只有 7 个模型文件，没有一个是大模型

先看一眼 `download.rs` 里的常量：

```rust
const MODEL_FILES: &[&str] = &[
    "ocr-models/ppocrv5_mobile_det.onnx",
    "ocr-models/ppocrv5_mobile_rec.onnx",
    "ocr-models/ppocrv5_dict.txt",
    "icon-classifier/icon_classifier.onnx",
    "icon-classifier/labels.json",
    "object-detection/yoloe-26n-seg.onnx",
    "object-detection/yoloe-26n_classes.txt",
];
```

这就是 [quasivision](https://github.com/WeiChens/quasivision) 全部的模型依赖——两个 PaddleOCR 的 ONNX 文件做文字识别，一个 11MB 的 YOLOE-26n 做物体检测，一个图标分类器，加上对应的字典和标签文件。加起来不到 20MB。没有 LLM，没有 VLM，没有 Transformer。

在 2026 年，一个号称能做"视觉理解"的工具用 ONNX 小模型而非调用 GPT-4V，这本身就值得深究。

---

## 管线是 8 步，核心分类靠 if-else

读 `main.rs` 里的 `run_pipeline` 函数，骨架非常清晰：

```
Step 1    → 读图片
Step 2-4  → 组件检测 + 规则分类（主线程）
Step 5    → OCR（后台线程，与 2-4 并行）
Step 6    → 合并组件 + 文本 → Element 列表
Step 6b   → 视觉重要性计算
Step 6c   → Icon 含义识别
Step 6d   → 物体检测（后台线程，等待完成）
Step 8    → 输出 JSON/Tree/可视化图
```

有意思的点在 Step 2-4：组件检测的产出不是"这个东西有 87% 概率是按钮"，而是先通过连通域分析（CCL）和矩形检测找到所有候选区域，然后**用纯几何规则做分类**。

打开 `detection/classification.rs`，核心函数 `classify_by_geometry` 就是一个大的 if-else 链：

```rust
pub fn classify_by_geometry(comps: &mut [Component], img_shape: (u32, u32)) {
    for comp in comps.iter_mut() {
        if comp.category != "Compo" { continue; }

        let w = comp.bbox.width() as f64;
        let h = comp.bbox.height() as f64;
        let area_ratio = comp.bbox.area() as f64 / img_area;
        let ratio = w / h;

        // Image: 面积 >8%，宽高比 0.3~5.0
        if area_ratio > 0.08 && (0.3..=5.0).contains(&ratio) {
            comp.category = "Image"; continue;
        }
        // Block: 宽度或高度超过画面一半
        if (w / img_w > 0.5 && h / img_h > 0.03)
            || (h / img_h > 0.5 && w / img_w > 0.03) {
            comp.category = "Block"; continue;
        }
        // Icon: ≤48px 方形
        if (0.7..=1.4).contains(&ratio) && h <= 48.0 && w <= 48.0 {
            comp.category = "Icon"; continue;
        }
        // Button: 20-80px 高, 20-200px 宽, 宽高比 0.5~3.0
        if (0.5..=3.0).contains(&ratio) && (20.0..=80.0).contains(&h)
            && (20.0..=200.0).contains(&w) {
            comp.category = "Button"; continue;
        }
        // Text: 高度 <2.5% 画面高 + 极宽
        if h / img_h < 0.025 && ratio > 3.0 {
            comp.category = "Text"; continue;
        }
    }
}
```

**全是硬编码阈值。** 面积占比 0.08 是 Image，边界框 48px 以下方形是 Icon，高度 20-80px 配宽高比 0.5~3.0 是 Button。没有任何机器学习参与这一步。

这在 2026 年看起来像是一种奇怪的返祖——但仔细想，它提供了一个 VLM 永远给不了的东西：**确定性**。同样的输入永远输出同样的结果。截图里的按钮今天被检测为 Button，明天也是；坐标 [100,200,300,250] 每次都是一样的。而 VLM 可能在两个 session 里对同一个按钮给出两种描述。

---

## merge 阶段：用 Text 覆盖 Comp

看 `merger.rs` 里的 `merge` 函数，它的逻辑是先转 Component 为 Element，再把 OCR 识别的文字合并进去。合并过程中有几个值得注意的设计：

**有意义长文本绕过过滤。** `refine_texts` 对文本做了多层过滤：空内容删掉，纯标点删掉，但有一个保护条件——"长度 >5 字符且宽度大于 2 倍高度的文本"直接放行，不受高度比限制。这解决了一个实际问题：标题和标语通常很长但字号不大，如果按高度过滤会误杀。

**顶部/底栏移除是可选的，且阈值可配置。** 很多手机截图 App 都有状态栏和底部导航栏，这些对 UI 检测来说是噪声。`remove_bar` 通过 `config.top_bottom_bar` 参数控制，默认开启。

**孤儿文本自动合成容器。** 如果 OCR 识别出一段文字但周围没有对应的 UI 组件（比如手写笔记或文档截图），`synthesize_text` 会为它自动生成一个 Block 容器。这在处理非标准 UI 的图片时很有用。

---

## 为什么并行放在后台，主线程只跑规则

`main.rs` 里 OCR 和物体检测都 `thread::spawn` 到后台：

```rust
let ocr_handle = if opts.enable_ocr {
    let img_for_ocr = img.clone();
    Some(thread::spawn(move || {
        text_detection::detect_text(&img_for_ocr)
    }))
} else { None };

let object_detect_handle = if opts.enable_object_detect {
    let img_for_detect = img.clone();
    Some(thread::spawn(move || {
        object_detector::run_object_detection(...)
    }))
} else { None };
```

主线程跑完 CCL → 合并 → 过滤 → Block 识别 → 嵌套检测 → 几何分类 → 颜色图标，然后才 `handle.join()` 等待 OCR 和物体检测的结果。这一步的收益是——OCR 推理和 ONNX 物体检测完全不阻塞 UI 检测管线，总耗时等于 max(UI检测, OCR, 物体检测) 而非三者之和。

这是在 Rust 里用标准库 `std::thread` 完成的，不需要 Tokio 这样的异步运行时。对于一次性扫描的工具来说，线程方案比 async 更直接——没有调度开销，join 就是等待。

---

## ONNX Runtime 做胶水，Cargo 做平台适配

`Cargo.toml` 里依赖的 ONNX 绑定是 `ort = "2.0.0-rc.12"`，配合 `ndarray` 做矩阵数据。而 OCR 引擎用的是 `oar-ocr`，一个封装了 PaddleOCR 的 ONNX 推理库。平台适配通过 Cargo 的条件编译：

```toml
[target.'cfg(target_os = "windows")'.dependencies]
oar-ocr = { version = "0.6", features = ["directml"] }

[target.'cfg(target_os = "macos")'.dependencies]
oar-ocr = { version = "0.6", features = ["coreml"] }

[target.'cfg(target_os = "linux")'.dependencies]
oar-ocr = "0.6"
```

Windows 用 DirectML，macOS 用 CoreML，Linux 走 CPU。全编译期自动选择，用户不需要关心 GPU 驱动版本更不用配 CUDA。

模型文件也做了一层巧妙的降级——`download.rs` 里，缺失文件自动从 Hugging Face 下载。国内用户设个环境变量就能切到镜像：

```rust
fn get_base_url() -> String {
    match std::env::var("QUASIVISION_MODELS_URL") {
        Ok(url) if !url.is_empty() => { url.trim_end_matches('/').to_string() }
        _ => "https://huggingface.co/...".to_string(),
    }
}
```

一个细节：`download_missing` 用了 `AtomicBool` 防并行下载，避免多个线程同时拉模型。对于 CLI 工具来说这算过度设计，但对于将来可能的库调用场景，这是正确的防御。

---

## 输出格式：固定 shape 而不是给一堆 flag

quasivision 的输出只有一个格式——tree。同时产出 `elements.tree.json` 和 `elements.tree.txt`。没有 `--format json|yaml|compact|` 这种排列组合。

但 `lib.rs` 里暴露了更多序列化函数：`to_compact_string`（短键名 -50% tokens）、`to_ai_json_string`（坐标归一化 0-1000）、`to_tree_text_string`（纯文本树）。这些都只在库层面暴露，CLI 只给 tree 格式。这种设计让库用户有灵活性（Python binding 可以选格式），同时 CLI 用户不会纠结。

输出中还包含一个 `compute_prominence` 函数计算的"视觉重要性"分数。基于面积、类别、颜色对比度，给每个元素打分 0.0~1.0。对自动化场景来说，这个分数可以帮助下游 Agent 决定"先点哪个"。

---

## 这个架构对 AI Agent 意味着什么

2026 年的 Agent 工具链里，视觉感知的方式基本被 VLM 垄断了。CUA（Computer-Using Agent）的典型流程是：截图 → 发给 GPT-4V → 获取意图 → 执行动作。这条路的问题不是效果不好，而是成本结构——每次决策都要一次 API 调用。

quasivision 提供了一条补充路径：把视觉感知从"推理"降级为"提取"。截图先过确定性管线得到结构化描述（按钮在哪里、文字是什么），然后只把**文本描述**传给 LLM 做决策。LLM 不需要"看图"了，它只需要读一段结构化的 DOM 树。

这相当于把视觉层的 token 消耗降到了零。Agent 循环变成：截图 → quasivision 本地解析 → 结构化文本 → LLM 决策 → 执行动作。每一轮只消耗一次文本 token，不消耗图像 token。

当然这条路有明确的边界——quasivision 看不懂图表趋势、分不清情绪、不理解设计意图。但对于"找到页面上所有按钮"、"提取屏幕上的文字"、"列出截图中的物体"这类精确感知任务，确定性方案无论在速度、成本还是稳定性上都碾压式领先。

---

## 一行命令上手

```bash
git clone https://github.com/WeiChens/quasivision.git && cd quasivision
cargo run -- --input demo/ui.jpg
```

首次运行自动下载模型，国内用户加一行：

```bash
set QUASIVISION_MODELS_URL=https://hf-mirror.com/WeiChens/quasivision-models/resolve/main
```

v0.2.2，22 个 commit，全 Rust 实现。如果你在做桌面 Agent、浏览器自动化或 MCP Tool 开发，这个项目值得放进工具箱——不是因为它的功能多强，而是因为它的方案选得清醒。在所有人都在往上做更大模型的时候，选择往下做确定性感知，这本身就是一种稀缺的判断力。