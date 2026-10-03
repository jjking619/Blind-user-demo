# AI 光影自适应盲文即时转换系统（Blind User Demo）

摄像头实时拍摄印刷文字 → 光影自适应预处理 → OCR 识别 → （待实现）中文转盲文点阵。

本仓库当前阶段：**方案一（纯 CPU / PaddleOCR）已跑通**，可在 aarch64 开发板上用 USB 摄像头实时取字；
「中文 → 现行盲文（GB/T 15720）编码」与「盲文点阵硬件驱动」尚未实现（接口已预留）。

## 目录结构

```text
.
├─ ocr_cpu_test.py       # 主程序：摄像头 → 光影自适应 → PaddleOCR → 文本（+ 盲文编码钩子）
├─ diag_ocr.py           # 链路诊断：合成图 vs 实拍帧，区分"模型坏了"和"画面里没字"
├─ requirements.txt      # 依赖与版本（含 aarch64 上的版本自洽说明）
├─ docs/
│  └─ board-setup.md     # 板端环境准备与常见故障排查
└─ README.md
```

## 硬件与环境（Requirements）

| 项 | 说明 |
|---|---|
| 开发板 | Quectel Pi（本仓库在 aarch64、Debian 13 上验证） |
| 摄像头 | USB UVC 摄像头（验证型号：Microdia/UGREEN 2K，`0c45:636f`），支持 MJPG |
| 系统依赖 | Python 3.10+（板端有两套解释器时，注意装到「你终端里那个 python3」）、OpenCV、NumPy |
| OCR | PaddlePaddle（CPU 版）+ PaddleOCR，首次运行会自动下载 PP-OCR 权重到 `~/.paddleocr/` |

## 快速开始（Quick Start）

```bash
# 1) 安装依赖（详见 requirements.txt；离线安装方式见 docs/board-setup.md）
python3 -m pip install -r requirements.txt

# 2) 找到摄像头节点（不一定就是 video0）
python3 ocr_cpu_test.py --list-cams
#   例：/dev/video2  OK  1280x720  mean=36.0  →  可用节点: 2

# 3) 实时识别：把书页正对摄像头（20–30cm，占画面一半以上）
python3 ocr_cpu_test.py --cam 2
#   s = 识别一次    a = 连续识别    q = 退出

# 4) 没有桌面 / 远程调试：无窗口模式，结果落盘后用 adb pull 取回
python3 ocr_cpu_test.py --cam 2 --no-window
```

## 参数（Options）

| 参数 | 说明 |
|---|---|
| `--cam N` | 指定摄像头节点 `/dev/videoN` |
| `--list-cams` | 遍历探测可用摄像头节点后退出 |
| `--image FILE` | 对单张图片识别（无摄像头也能验证链路） |
| `--no-window` | 不弹预览窗，只打印并落盘 |
| `--window` | 强制显示预览窗（配合 `--auto-secs`） |
| `--auto-secs S` | 无人值守：每 `--interval` 秒识别一次，跑满 S 秒自动退出 |
| `--interval S` | 连续识别间隔，默认 3.0 秒 |
| `--no-adaptive` | 关闭光影自适应预处理（对照实验用） |
| `--braille` | 识别后调用盲文编码钩子（当前未实现，仅提示） |

## 输出（Outputs）

每次识别写入 `$OCR_OUT`（默认 `$HOME/ocr_out`）：

```text
shot_<时间戳>.jpg     原始帧
marked_<时间戳>.jpg   画出文字框的帧
result_<时间戳>.txt   识别文本（UTF-8）
```

取回：`adb pull /home/<user>/ocr_out`

## 光影自适应（Light Adaptation）

页面在弱光/反光下 OCR 命中率会明显下降，脚本在识别前做两步处理（可用 `--no-adaptive` 关闭对比）：

1. LAB 空间 CLAHE：提高局部对比度，不改变色相
2. 暗光伽马补偿：帧平均亮度低于阈值时按比例提亮（`gamma = clamp(mean/阈值, 0.5, 1)`）

实测示例：暗帧 `mean=33.7 → gamma=0.50 → 107.3` 后可正常识别。

## 常见问题（Troubleshooting）

| 现象 | 原因与处理 |
|---|---|
| `No module named 'paddleocr'`（明明装过） | 板上有**两套 Python**：交互式终端用 `pyenv` 的 python3，非交互 shell 用 `/usr/bin/python3`。用 `which python3` 确认，装到同一套即可 |
| `--list-cams` 报"未找到可用摄像头节点" | 摄像头未插好、不在 `video` 组，或节点号不是 video0；用 `v4l2-ctl --list-devices` 确认归属 |
| 采集只有 640×480 | UVC 默认协商成 YUYV；程序已先请求 MJPG fourcc，若仍是 640×480，说明该分辨率不被支持 |
| 一直"未识别到文字" | 先用 `diag_ocr.py` 判断：合成图能识别 → 模型没问题，是画面里没有清晰文字（镜头没对准/太远/太暗/手抖） |
| 依赖装到一半中断 | 企业网络/镜像对大文件长连接不稳定，改用离线 wheel 安装（见 `docs/board-setup.md`） |
| `ImportError: numpy.core.multiarray failed to import` | NumPy 2.x 与按 NumPy 1.x 构建的轮子（paddlepaddle / opencv 4.6）不兼容，按 `requirements.txt` 固定到 NumPy 1.26.4 |

## 已知限制（Limitations）

- 只做「取字」：`text_to_braille()` 是钩子，尚未实现（`--braille` 会打印未实现提示）
- 单帧 CPU 推理约 0.7–0.9 s（1280×720），实时性受限；后续可走 NPU（板端 NPU 路线与 CPU 路线并存，见 docs）
- 取景敏感：文字需占画面足够比例、光照均匀；未做自动对焦/防抖
- 长文本未做版面分析（仅按行/列粗排阅读顺序）

## 路线图（Roadmap）

1. 中文 → 现行盲文（GB/T 15720）编码 + 6 点阵字节映射
2. 盲文点阵硬件驱动接口
3. NPU 加速推理（将现有 ONNX/exporter 链路接到板端 NPU）
4. 版面分析：多栏、段落顺序、翻页自动触发

## 许可（License）

内部 demo，未附许可证；如需开源请补充 LICENSE。
