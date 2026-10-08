# GPU训练环境实测记录

2026年10月8日重启后完成WSL2、Ubuntu及实际GPU训练链路验证。系统组件不再要求重启。

| 项目 | 实际环境 |
| --- | --- |
| WSL / Linux内核 | 3.0.1.0 / 6.18.40.1-1 |
| Ubuntu | 24.04.5 LTS，WSL发行版名Ubuntu-24.04 |
| GPU | RTX 4060 Laptop，8188MiB，Windows驱动592.82 |
| Python / TensorFlow | 3.12.3 / 2.21.0 |
| Keras / NumPy | 3.12.1 / 2.1.3 |
| 独立CPU运行时 | ai-edge-litert 2.2.0，不安装TensorFlow |
| 统一batch | 32 |
| GPU计算精度 | float32，TensorFloat-32关闭 |

依赖版本逐项锁定在`ml/requirements-wsl-gpu.lock`和`ml/requirements-wsl-runtime.lock`，两个环境的`pip check`均通过。保留原有Windows显卡驱动。

## 本机目录与激活

本机训练环境位于`/opt/campus-recognition/venvs/gpu`，独立运行时位于`/opt/campus-recognition/venvs/runtime`。仓库根目录`.venv-wsl`、`.venv-runtime-wsl`分别是指向它们的Linux链接，不提交Git。环境放在Linux文件系统，照片、清单与交付文件保留在仓库。

本次由`wsl.exe -d Ubuntu-24.04 -u root`完成系统安装和训练，不收集个人Linux密码。个人账号可由本人在Ubuntu创建；重建环境时使用本人可写的目录。账号选择不影响模型合同与冻结数据。

每个新的Ubuntu终端，从仓库根目录执行：

```bash
source scripts/activate-ml-wsl.sh
python -m recognition doctor
```

激活脚本设置当前终端的训练解释器和NVIDIA wheel动态库路径。直接调用环境的Python而未激活时，TensorFlow可能无法加载cuBLAS/cuDNN并回退到CPU。独立运行时使用自己的解释器，不需要GPU激活：

```bash
./.venv-runtime-wsl/bin/python scripts/check-local-runtime.py \
  --release models/releases/campus-gpu-v1 --run-id <新的核验ID>
```

在其他Ubuntu 24.04机器安装Python 3.12及venv支持后，用两个独立目录重建：

```bash
python3.12 -m venv /path/to/gpu
/path/to/gpu/bin/python -m pip install -r ml/requirements-wsl-gpu.lock
/path/to/gpu/bin/python -m pip install -e ml --no-deps
python3.12 -m venv /path/to/runtime
/path/to/runtime/bin/python -m pip install -r ml/requirements-wsl-runtime.lock
/path/to/runtime/bin/python -m pip install -e ml --no-deps
export ML_TRAIN_ENV=/path/to/gpu
source scripts/activate-ml-wsl.sh
python -m recognition doctor --training-check --require-gpu
```

## 已完成验证

`preflight.json`记录冻结骨干和最后两块微调的真实梯度更新，batch均为32。TensorFlow峰值分配分别为666,861,568和379,450,368字节；该数字是预跑中TensorFlow分配值，不是完整训练总显存或系统显存占用。

模型与优化器可保存和恢复，转换只使用TFLite内置算子，关闭量化。完整float32预跑的Keras/LiteRT最大分数差为8.0466e-7。84项检查在真实WSL/GPU环境通过，包含训练和续训入口的实际矩阵数值回归。

控制实验使用同一模型和合成输入：默认TensorFloat-32时分数差约5.35e-4，关闭后约1.16e-6。因此新GPU实验统一关闭该模式，不把不同计算条件混入同一候选比较。

合成小样本`smoke-gpu-fp32-20261008`完成训练、保存、FP32转换、加载、20张交接样例核验和本机CPU计时；合成准确率不作物品识别结论。真实照片实验及正式模型结果见`ml-gpu-experiments.md`生成后的记录。

训练源码提交`222ff37e777ea4cc076f644c23fd09c4ec3ab113`，模块摘要`1d77a1f2b326f9c84623ad1ec0efe89ad9292e6e79a6405ff4a95829585c600f`，提交字节核对证据为`experiments/reports/environment/gpu-training-source-20261008.json`。

证据集中在`experiments/reports/environment/`：`preflight.json`、`wsl-gpu-tests-20261008.json`、`gpu-fp32-precision-20261008.json`和`gpu-data-integrity-20261008.json`。早期CPU环境记录及默认TF32预跑保留在`history/`。这些环境验证不代表独立实拍、手机或真实云端验收。
