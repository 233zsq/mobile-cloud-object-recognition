# 样本采集分配表（10月8日下发，10月9日晚汇总）

目标：约 1000 张原始照片，10 类 × 约 100 张，每人约 250 张。
类别 ID 与 `shared/categories.example.json` 一致，冻结前不得改动编号。

## 分配表

| 采集者 | 负责类别（每类 50 张） | 合计 |
| --- | --- | --- |
| 鲁涵宇 | 水杯、雨伞、书本、笔袋、鼠标 | 250 |
| 刘亮 | 书本、笔袋、键盘、耳机、充电器 | 250 |
| 张弓羿 | 鼠标、键盘、耳机、钥匙、背包 | 250 |
| 赵高剑 | 水杯、雨伞、充电器、钥匙、背包 | 250 |

每类恰好 100 张且由两名采集者分担（水杯/雨伞：鲁+赵，书本/笔袋：鲁+刘，鼠标/键盘/耳机：刘+张，充电器：刘+赵，钥匙/背包：张+赵），避免同一类照片来自同一个人、同一台手机。

## 采集规则

1. 每类至少覆盖 **5 件不同实物**（如水杯 5 个不同的杯子），尽量两名采集者各拍不同实物；每件实物给一个稳定 `object_id`（格式：`类别英文短名-01`、`类别英文短名-02`……）。
2. 每次拍摄记一个 `session_id`（格式：`日期-采集者-序号`，如 `1008-zgj-01`），同一场次背景、光线相近。
3. 一张照片一个主要主体；变换背景、角度、照明；避免人脸、证件、屏幕内容入镜。
4. 不要连拍大量近似照片凑数；同一实物的相似连拍在划分时不会分散到不同集合。
5. 照片按 `data/raw/<类别英文短名>/<session_id>/` 存放，原图保留，不要裁剪压缩；EXIF 方向信息保留。
6. 每拍完一个场次，立刻在 `data/manifests/sample-manifest.csv`（由模板复制）追加行：`sample_id,image_path,image_sha256,category_id,object_id,session_id,collector,captured_at,split_name,review_status,data_version`。`split_name` 留空，由组长统一划分；`review_status` 先填 `pending`；`image_sha256` 可留空，由 `scripts/check_manifest.py` 统一补算。

## 10月9日晚汇总流程（组长执行）

1. 收齐四人清单，合并为一份 manifest。
2. 运行 `python scripts/check_manifest.py data/manifests/sample-manifest.csv --check-files`：查损坏、重复（哈希）、模糊、标签越界、缺字段。
3. 互查标签：模型负责人审核训练标签，发现错标退回重拍或修正。
4. 审核通过后运行 `python scripts/split_dataset.py` 按实物分组 60/20/20 划分，冻结测试清单到 `data/splits/`。
