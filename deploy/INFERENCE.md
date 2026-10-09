# campus-gpu-v1 云端 CPU 推理

Flask/Gunicorn 保留 Python 3.14 环境，通过 `/run/mobile-cloud-inference/model.sock` 调用独立 Python 3.12 CPU 进程。
模型包来自组内交付目录，权重、样例照片、参考张量和运行环境不提交 Git。
模型 SHA-256 固定为 `a58ca2be234d0d7e7db6bdec3853b3e077df6a88321da4f6bd7a8a5d5be51d13`，类别版本为 `campus-10-v2`。

## 独立环境

服务端模型包位置为 `/home/gongyi/apps/mobile-cloud-backend/models/campus-gpu-v1-backend`。
包内 `checksums.json` 校验 62 个交付文件；保持原文件字节，新增结果使用新路径。
在包目录执行：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: -r locks/linux-py312-runtime.lock
.venv/bin/python -m pip check
.venv/bin/python -B verify_package.py
.venv/bin/python -B self_check.py --out results/actual-server-self-check-NEW_RUN.json
```

服务器已有项目专用 CPython 3.12.15，位于 `runtimes/cpython-3.12.15-linux-x86_64-gnu/bin/python3.12`；安装由 uv 管理，不更改系统 Python 或原后端环境。
固定依赖为 LiteRT 2.2.0、NumPy 2.1.3、Pillow 12.3.0，其余版本以交付锁文件为准；不安装 TensorFlow、CUDA 或训练组件。

## 发布与运行

先按 `deploy/README.md` 从固定 Git 提交部署 Flask 发布包并执行 `provision.py application`。
确认交付包自检通过后，在该发布包的 backend 目录执行：

```bash
.venv/bin/python ../deploy/scripts/provision.py inference
```

此步骤核对模型身份、幂等登记元数据、保存原有凭据、配置 Unix socket、安装并启用 `mobile-cloud-inference.service`，等待模型就绪后重启 Flask。
模型每个推理进程只加载一次，启动前预热 20 次；沿用交付包的 Interpreter 锁。
外部认证仍由 Nginx Bearer 令牌实现。推理进程只监听权限为 0700 的运行目录下的 Unix socket，不开放公网端口。
同一时刻仅处理一张图片，额外请求返回 503 `INFERENCE_BUSY`；不建立等待队列。服务失败不阻断记录接口，health 仍返回 200，但 `model_loaded=false`。
工作进程限制为单解释器线程、一核 CPU 配额、MemoryHigh=256MiB、MemoryMax=512MiB。

```bash
sudo systemctl status mobile-cloud-inference mobile-cloud-backend
sudo journalctl -u mobile-cloud-inference -n 50 --no-pager
sudo systemctl restart mobile-cloud-inference
```

模型工作进程重启会校验包内文件。正常退出或每次请求完成后删除临时图片；异常进程退出由 systemd 清理运行目录。
推理输出由客户端确认采用后调用 `/api/records` 保存，不自动写记录或收集训练照片。

## 实际服务器回传

使用 CPU 环境运行仓库验收脚本，输出目录必须是未使用的新路径：

```bash
.venv/bin/python /实际发布路径/deploy/scripts/verify_cloud_model.py \
  --package /home/gongyi/apps/mobile-cloud-backend/models/campus-gpu-v1-backend \
  --out-dir /home/gongyi/apps/mobile-cloud-backend/shared/cloud-model-return-NEW_RUN \
  --scope 'ACTUAL TENCENT CLOUD CPU'
```

生成 `cloud-reference_tensor.json`、`cloud-image_chain.json`、`image_chain_inputs/*.bin` 与 `actual-host-summary.json`。
两种模式使用不同 run_id，保存真实 CPU/OS、Python/LiteRT、线程数、每张图片的实际分数和输入字节。
按参考 predicted_id 核对 Top-1，不以真实 category_id 替代参考预测；分数和像素最大差限值均为 0.001。
脚本另预热 20 次、测量 100 次，分别报告预处理、纯推理和模型调用耗时。这些数值不包含 HTTP 或网络时间。
交付包的原 `self_check.py` 在 scope 文本中固定使用 LOCAL CPU 标签，保留原输出；实际服务器范围由新回传文件的 scope、主机信息和执行记录证明。

HTTP 验收另记录公网 TLS、20 张图片 Top-1/分数、认证/格式/大小/模型版本错误、并发忙碌和模型进程失败后的记录可用性。
验收文件与输入张量保存在运维目录和本地 `tmp/`，回传前遵循组内证据流程，不直接提交 `tests/evidence/`。

## 回退

先把 current 指回上一个发布目录，重启 `mobile-cloud-backend`。旧发布不提供 infer，记录接口继续使用原数据库。
然后停止 `mobile-cloud-inference`；保留已登记的模型、交付包和验收结果，不回写旧模型哈希。
恢复新发布时，先启动 inference worker 再检查 health；工作进程的代码路径随 current 变化，更新后须重启工作进程。
