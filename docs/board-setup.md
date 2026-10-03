# 板端环境准备与排障（board-setup）

面向 aarch64 开发板（Debian 系）跑 `ocr_cpu_test.py` 的环境准备记录。**所有命令都在板子上执行。**

## 一、确认板子自身状态

```bash
cat /proc/device-tree/model          # 板型（不要用 adb devices -l 的 model，可能是假值）
uname -m; python3 -V                 # 架构与解释器版本
df -h /                              # 根分区剩余空间（装依赖前先看）
```

## 二、摄像头：节点号与采集格式

```bash
ls -l /dev/video*
v4l2-ctl --list-devices              # 哪个节点真正属于摄像头
v4l2-ctl -d /dev/video2 --list-formats-ext | head -30
```

要点：

① 摄像头**不一定是 video0**：板上其它多媒体设备（视频编解码器、ISP 等）会占用低位节点号，UVC 摄像头可能落在 video2 甚至更高的编号上。
② MJPG 与 YUYV 支持的分辨率通常不同。UVC 默认协商成 YUYV 时往往只有 640×480，程序里先请求 MJPG fourcc 才能拿到 1280×720 / 1920×1080。
③ 权限：`/dev/video*` 属 `video` 组，把登录用户加进去后**需要重新登录**才生效：

```bash
sudo usermod -aG video $USER
```

## 三、解释器：先确认你终端里用的是哪一个

同一块板子上常存在两套 Python，装错会表现为「明明装了却 No module named ...」：

```bash
which python3            # 交互式终端（含 pyenv/conda）里的 python3
python3 -V
bash -c 'which python3'  # 非交互 shell 里可能是另一套
```

**结论：装依赖时用的解释器，必须和你运行时用的解释器是同一个。**
如果终端里 `python3` 指向 pyenv（如 `~/.pyenv/shims/python3`），就直接装进那一套：

```bash
python3 -m pip install -r requirements.txt
```

## 四、装依赖：网络不稳定时用离线 wheel 安装

企业网络对大文件长连接不稳定时，`pip install` 常在下载中途报 `ReadTimeoutError` 或 SSL 相关错误。
可靠做法是**在电脑上按目标平台把轮子下好，再推进板子离线安装**。

电脑上（与板子同为 Linux/aarch64 目标；Python 版本要对上）：

```bash
pip download -d ./wheels \
  --platform manylinux2014_aarch64 --platform manylinux_2_17_aarch64 \
  --platform manylinux_2_27_aarch64 --platform manylinux_2_28_aarch64 \
  --python-version 3.10 --implementation cp --only-binary=:all: \
  -c constraints.txt \
  paddlepaddle==2.6.2 paddleocr==2.7.3
```

> `constraints.txt` 里主要固定 `numpy==1.26.4` 等版本（见仓库根目录 `requirements.txt` 的说明）。
> 注意：`--python-version` 只影响轮子的标签匹配，**不会改变环境标记(marker)的求值**；
> 形如 `exceptiongroup; python_version < "3.11"` 这类「仅低版本 Python 需要」的包可能不会被下到，
> 若离线安装报缺包，按报错提示单独 `pip download` 补上即可（这类包通常很小、纯 Python）。

推进板子并离线安装：

```bash
adb push ./wheels /home/pi/ocr_test/wheels
# 板子上：
python3 -m pip install --no-index --find-links /home/pi/ocr_test/wheels -r requirements.txt
```

如果 pip 受 PEP 668 管控（`externally-managed-environment`），加 `--break-system-packages`；
或者干脆装进虚拟环境 / 用户目录，避免动系统包。

## 五、运行与验证

```bash
python3 ocr_cpu_test.py --list-cams              # 期望：列出可用节点与实测分辨率
python3 ocr_cpu_test.py --cam 2                  # 实时识别（桌面环境带预览窗）
python3 ocr_cpu_test.py --cam 2 --auto-secs 30   # 远程无人值守 30 秒
python3 ocr_cpu_test.py --image shot.jpg         # 单图识别
```

判断"识别不出来"到底是谁的问题：

```bash
python3 diag_ocr.py                 # 合成图：识别到内容 = 模型与解码链路正常
python3 diag_ocr.py shot.jpg        # 实拍帧：det 框数 0 = 画面里没有文字（去对准镜头）
```

## 六、常见故障速查

| 现象 | 处理 |
|---|---|
| `No module named 'paddleocr'` | 第三节：装到了另一套 Python |
| `numpy.core.multiarray failed to import` | NumPy 2 与旧轮子冲突：固定 `numpy==1.26.4` |
| `AttributeError: module 'cv2' has no attribute 'INTER_NEAREST'` | 多份 opencv 轮子混装的残留：三种 opencv 全部卸载 + 删除 `site-packages/cv2*` 后只装一种 |
| 识别一直为空 | `diag_ocr.py` 判断是模型问题还是取景问题 |
| 只有 640×480 | 见第二节 MJPG |
| 强杀进程时出现 `FatalError: Termination signal ...` | 被 `timeout`/`kill` 中断的收尾输出，非缺陷；正常按 `q` 退出不会出现 |
| 首次运行卡在下载权重 | PaddleOCR 首次会下载 PP-OCR 权重到 `~/.paddleocr/`；离线环境需提前拷入该目录 |
