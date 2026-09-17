# Quadcopter：自主导航无人机

基于荔枝派（LicheeRV Nano）等硬件的自主导航无人机项目。仓库内容持续扩充中，当前已完成视觉回传模块，后续将补充导航、控制、感知等其他模块。

## 项目定位

面向自主导航的四旋翼无人机软件栈。荔枝派视觉与监控是已落地的第一块拼图，负责机载摄像头的硬件编码与地面端实时回传；飞控、路径规划、避障与深度感知等能力仍在推进，相关目录与文档会陆续合入本仓库。

## 当前进度：LicheeRV Nano 视觉与监控

- 已实现：GC4653 摄像头硬件 H.264 编码、板卡轻量 TCP 发送、电脑 FFmpeg 无重编码封装、浏览器实时监控。
- 尚未实现：单目深度估计（规划见深度估计计划）。
- 后续模块（飞控、导航、感知等）将作为独立目录补充，请关注 [任务状态](TODO.md)。

### 相关文档

- [运行与从零配置](licheerv-nano/docs/运行指南.md)
- [实现与验证记录](licheerv-nano/docs/实现与验证.md)
- [单目深度估计开发计划](licheerv-nano/docs/深度估计计划.md)
- [项目协作约定](AGENTS.md)
- [任务状态](TODO.md)

### 视觉模块快速启动

板卡干净上电后，通过 SSH 登录，确认没有摄像头程序运行，再执行：

```sh
export LD_LIBRARY_PATH=/mnt/system/usr/lib:/mnt/system/lib
nohup python3 /mnt/data/codex-h264-sender/h264_sender.py > /tmp/h264-sender.log 2>&1 < /dev/null &
```

电脑安装 Python 3 和 FFmpeg 后，在仓库根目录运行：

```sh
python3 licheerv-nano/scripts/start_pc_preview.py --board 10.225.161.1 --ffmpeg /usr/bin/ffmpeg
```

Windows 将 `python3` 替换为 `python`，并通过 `--ffmpeg` 指定实际 EXE 路径。浏览器打开 <http://127.0.0.1:8080/>。本版本没有配置开机自启。

离线测试（不访问板卡，不启动编码器）：

```sh
python3 -m unittest discover -s licheerv-nano/tests -v
```

### 视觉链路架构

```text
板卡：GC4653 → VI / ISP → 硬件 VENC → H.264 FIFO → 轻量 TCP 发送器 :9000
                                                        ↓ USB 网络 / Wi‑Fi
电脑：FFmpeg 复制码流、添加时间戳、封装分片 MP4 → Python 本地 HTTP :8080 → 浏览器
```

## 仓库结构

```text
README.md                 项目总览（本文件）
AGENTS.md                 协作约定
TODO.md                   任务状态
licheerv-nano/            视觉与监控模块（已合入）
  scripts/                板卡发送器、电脑预览服务
  tests/                  离线单元测试
  docs/                   配置、验证记录、深度估计计划
（后续模块目录陆续补充）
```

## 参与贡献

1.  Fork 本仓库
2.  新建 Feat_xxx 分支
3.  提交代码
4.  新建 Pull Request

## 参考

-  Gitee 官方博客 [blog.gitee.com](https://blog.gitee.com)
-  你可以 [https://gitee.com/explore](https://gitee.com/explore) 这个地址来了解 Gitee 上的优秀开源项目
-  [GVP](https://gitee.com/gvp) 全称是 Gitee 最有价值开源项目，是综合评定出的优秀开源项目
-  Gitee 官方提供的使用手册 [https://gitee.com/help](https://gitee.com/help)
