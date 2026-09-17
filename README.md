# Quadcopter：LicheeRV Nano 视觉与监控

本目录是准备合入 `https://gitee.com/Homeless-Yin/quadcopter.git` 的独立模块整理包，不是远端仓库的完整副本。上传时必须先拉取并保留远端历史及已有文件；不要直接强推此整理包。

已实现：GC4653 摄像头硬件 H.264 编码、板卡轻量 TCP 发送、电脑 FFmpeg 无重编码封装、浏览器实时监控。深度估计尚未实现。

- [运行与从零配置](licheerv-nano/docs/运行指南.md)
- [实现与验证记录](licheerv-nano/docs/实现与验证.md)
- [单目深度估计开发计划](licheerv-nano/docs/深度估计计划.md)
- [项目协作约定](AGENTS.md)
- [任务状态](TODO.md)

## 快速启动

板卡干净上电后，通过 SSH 登录，确认没有摄像头程序运行，再执行：

```sh
export LD_LIBRARY_PATH=/mnt/system/usr/lib:/mnt/system/lib
nohup python3 /mnt/data/codex-h264-sender/h264_sender.py > /tmp/h264-sender.log 2>&1 < /dev/null &
```

电脑安装 Python 3 和 FFmpeg 后，在本整理包根目录运行：

```sh
python3 licheerv-nano/scripts/start_pc_preview.py --board 10.225.161.1 --ffmpeg /usr/bin/ffmpeg
```

Windows 将 `python3` 替换为 `python`，并通过 `--ffmpeg` 指定实际 EXE 路径。浏览器打开 <http://127.0.0.1:8080/>。本版本没有配置开机自启。

离线测试（不访问板卡，不启动编码器）：

```sh
python3 -m unittest discover -s licheerv-nano/tests -v
```

#### 软件架构

```text
板卡：GC4653 → VI / ISP → 硬件 VENC → H.264 FIFO → 轻量 TCP 发送器 :9000
                                                        ↓ USB 网络 / Wi‑Fi
电脑：FFmpeg 复制码流、添加时间戳、封装分片 MP4 → Python 本地 HTTP :8080 → 浏览器
```

#### 参与贡献

1.  Fork 本仓库
2.  新建 Feat_xxx 分支
3.  提交代码
4.  新建 Pull Request

#### 特技

1.  使用 Readme\_XXX.md 来支持不同的语言，例如 Readme\_en.md, Readme\_zh.md
2.  Gitee 官方博客 [blog.gitee.com](https://blog.gitee.com)
3.  你可以 [https://gitee.com/explore](https://gitee.com/explore) 这个地址来了解 Gitee 上的优秀开源项目
4.  [GVP](https://gitee.com/gvp) 全称是 Gitee 最有价值开源项目，是综合评定出的优秀开源项目
5.  Gitee 官方提供的使用手册 [https://gitee.com/help](https://gitee.com/help)
6.  Gitee 封面人物是一档用来展示 Gitee 会员风采的栏目 [https://gitee.com/gitee-stars/](https://gitee.com/gitee-stars/)
