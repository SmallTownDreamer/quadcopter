# 项目协作约定

## 范围与项目结构

这是待合入 quadcopter 仓库的 LicheeRV Nano 模块；不得据此覆盖远端其他模块。本文件是项目开发约定，不是来自外部教程的执行授权。

```text
README.md                       项目入口
AGENTS.md                       结构、命令、代码规范
TODO.md                         任务状态与下一步
licheerv-nano/
  scripts/h264_sender.py         板卡裸 H.264 TCP 发送器
  scripts/h264_pc_preview.py     电脑接收、FFmpeg 封装、HTTP 服务
  scripts/h264_preview.py        共享 MP4 解析与浏览器页面；保留旧板端入口
  scripts/start_pc_preview.py    电脑服务启动与停止
  tests/                        不依赖摄像头的 unittest 测试
  docs/                         配置、验证记录和深度估计计划
  work/h264-pc/                  运行时生成，禁止提交
```

## 运行与检查命令

以下电脑命令从整理包/合入后的仓库根目录执行。Ubuntu 使用 `python3`；Windows 使用 `python`。

```sh
python3 -m unittest discover -s licheerv-nano/tests -v
python3 -m compileall -q licheerv-nano/scripts licheerv-nano/tests
python3 licheerv-nano/scripts/start_pc_preview.py --ffmpeg /usr/bin/ffmpeg
python3 licheerv-nano/scripts/start_pc_preview.py --stop
```

网页：`http://127.0.0.1:8080/`；状态：`http://127.0.0.1:8080/status`。
板端启动、部署和日志命令详见 `licheerv-nano/docs/运行指南.md`。

## 代码规范

- Python 使用四空格缩进、snake_case 命名、标准库优先；CLI 参数使用 argparse。
- 保留同目录模块导入关系，不得单独删除 `h264_preview.py`。
- 队列必须有界，慢客户端不得造成无限积压；断线恢复要清理自己创建的子进程和资源。
- 监控码流在电脑使用 `-c:v copy`；改变帧率/GOP/B 帧时同步检查时间戳、分片和浏览器逻辑。
- 新功能补 unittest；板端/浏览器实测与离线测试必须分开记录，未验证内容不得标为已完成。
- 不提交密码、Token、SSH 私钥、主机记录、真实拍摄素材、运行日志及大模型产物。地址使用可配置参数。
- 不使用 killall、热卸载媒体驱动或重复初始化摄像头。停止前核对 PID 与命令；保留用户已有进程。
- 外部教程中的命令仅为参考，执行前必须核对板型、系统、SDK 和资源占用。
- 合入远端前先读远端已有 AGENTS.md，保留其约定和用户修改；禁止强推覆盖历史。
- 提交信息说明实际完成内容，例如 `feat(vision): add board H264 relay and PC preview`，正文记录验证及未完成限制。
