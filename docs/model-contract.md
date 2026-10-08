# 模型交接约定

由模型训练负责人提供，Android开发负责人接入手机，数据与云端负责人部署云端CPU推理，组长验证。
当前GPU发布包为 `models/releases/campus-gpu-v1/`，模型、阈值和输入合同已冻结。公开验证准确率90.37%、宏F1=0.8993；独立实拍及Android/真实云端验收仍待完成，完整实验见 `ml-gpu-experiments.md`。历史CPU试验包保持原状态，较早合成fixture只作工具链验证。
完整可执行接入、预处理和测试说明见 `ml-handover.md`。

## 类别与输出

类别ID已冻结为0至9，当前类别版本 `campus-10-v2`，以 `shared/categories.json` 为准。键盘仅包含独立外接计算机键盘，排除笔记本内置键盘和笔记本整机。旧版类别文件保存在 `shared/category-versions/`，旧试验包继续使用其原版本。
`shared/categories.example.json` 保留为历史草案示例。

`labels.txt` 每行是一个 `label_key`，第 0 行对应输出索引 0；数据库类别 ID、Android 预测映射与模型输出索引一致，中文显示名称来自相同版本的类别清单。模型包保存类别版本与标签文件 SHA-256。

## 输入与预处理

固定输入 `[1,224,224,3]` RGB float32，0–255像素值。EXIF纠正方向，等比双线性
half-pixel缩放、灰色128居中补边，不裁剪、不额外抗锯齿，奇数余量右/下。
模型内部归一化 `x/127.5-1`，等价于`(x-127.5)/127.5`，映射到[-1,1]；Android和云端不得再执行该变换。输出 `[1,10]` float32 Softmax。实际模型张量须校验一致。

本期只导出FP32模型，使用TFLite内置算子，无量化和Flex依赖。
GPU预跑、训练、续训及导出入口统一关闭TensorFloat-32，使用完整float32计算，设置写入环境记录。
GPU默认TensorFloat-32会降低部分卷积与矩阵运算精度；同图比较仍以实际FP32 LiteRT输出和0.001分数差上限为准。

## 发布包

- `model.tflite`、`labels.txt`、`metadata.json` 和评估结果。
- 模型版本、SHA-256、类别版本、数据版本、实验 ID 与代码提交。
- 实际输入输出形状、数据类型、输出解释和完整预处理。
- 验证集确定的低置信阈值、导出环境版本、PC/Android/云端同图对照结果及不一致记录。

元数据模板见`models/metadata.template.json`，所有空值由实际导出和验证后填写。手机与云端使用同一份FP32 tflite、labels.txt和预处理说明；接收方校验哈希、标签数与输出维度，再用同批图片核对PC、手机和云端结果。

最终测试集只用于冻结后的评估。首版模型随 APK 打包，正式模型文件通过组内共享存储领取并复制到 `android/app/src/main/assets/models/`。

云端领取相同发布包，模型路径由配置提供，启动时校验并加载。计时先预热20次，再测至少100次；记录设备、运行时、线程、纯推理、预处理加推理及手机端网络总等待时间。记录云端CPU、内存和失败率，不能预设云端更快或更准确。

## 课程示例与转换约定

采用已验证TensorFlow 2工具链的TFLiteConverter接口，当前导出入口为`from_saved_model`，不照搬旧`from_session`示例。参考Classifier封装时校验实际张量、标签数和输出解释；本组输出为10类，不套用旧示例分类数。转换环境与依赖锁随发布包交接。
