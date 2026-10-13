# 模型发布与交接

负责人：模型训练负责人。当前默认 `campus-evolve-v3` 已批准发布；安卓本地与云端可选择 v2/v3，原v2保留用于对比和回退。Git保存发布元数据及小型证据，实际模型二进制位于本地交付目录和服务器受控目录。详见 [范围判断交接](../docs/open-set-recognition.md)。

本地发布包使用 `releases/<模型版本>/`，包括：

```text
releases/<模型版本>/
├── model.tflite
├── labels.txt
├── metadata.json
└── evaluation.json
```

`metadata.template.json` 只有待填写字段，不能作为正式模型信息。`labels.txt` 每行写一个正式类别的 `label_key`，行号从 0 起对应模型输出索引；中文显示名称来自同版本类别清单。

模型二进制被 `.gitignore` 忽略，通过组内受控共享存储或正式发布附件交付，另行备份。Git 保存小型标签、元数据、评估结论与模型领取位置；未经校验不把模型复制进 Android 的 assets。交接要求见 `docs/model-contract.md`。
