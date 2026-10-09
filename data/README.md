# 样本与固定划分

样本清单由数据负责人维护，模型训练负责人审核标签，组长冻结最终测试划分。

| 目录 | 内容 | Git 规则 |
| --- | --- | --- |
| `raw/` | 原始采集照片，按类别或采集场次组织 | 本地保存，另行备份，默认忽略 |
| `processed/` | 预处理与增强产物 | 本地保存，默认忽略 |
| `manifests/` | 样本元数据清单 | 跟踪 CSV 和必要说明 |
| `splits/` | 冻结的训练、验证、测试清单及数据版本 | 跟踪，变更需记录原因 |

`manifests/sample-manifest.template.csv` 只有列名，复制后填写真实样本。路径相对仓库根目录，使用 `/` 分隔；`split_name` 使用 `train`、`validation`、`test`，未划分时留空；`review_status` 建议使用 `pending`、`approved`、`rejected`。

同一实物统一使用稳定的 `object_id`，同一采集场次使用 `session_id`。先审核照片，再按实物分组划分，计划约 60%/20%/20%，实际数量以清单为准。不能为凑比例把同一实物分散到不同集合。原始照片约 1000 张，增强产物不计入采集数量。

冻结时在 `splits/<数据版本>/` 保存三份清单与分组规则、随机种子、清单哈希和实际数量。组长保管最终测试清单；训练增强、选参、阈值选择与量化校准不能使用测试集。新增纠错样本先复核，再以新数据版本纳入训练。

## 已确认的数据策略调整（2026-10-07）

正式目标改为约600张公开训练照片、200张公开验证照片及200张手机实拍独立测试。
公开照片不足时补拍训练/验证照片，实物与测试集隔离。实际数量按审核及分组结果记录，
公开照片不能写成团队自采数量。类别以 `shared/categories.json` 的campus-10-v2为准；键盘仅独立外接计算机键盘。

清单新增来源、作者、许可、下载版本URL、group_id、审核原因、感知哈希和尺寸字段。
公开照片不伪造object_id，按来源/近重复组隔离；不能保证未知照片的实物身份完全互斥。
同件实物及同一产品拍摄系列经视觉检查后合并group_id。

Commons候选为 `manifests/public-candidates.csv`；Open Images回退候选为
`manifests/openimages-candidates.csv`。运行中的采集清单不能用于冻结，先生成审核快照：

```bash
python -m recognition audit --manifest data/manifests/public-reviewed.csv \
  --merge-manifests data/manifests/public-candidates.csv data/manifests/openimages-candidates.csv \
  --decisions data/manifests/public-review-decisions.csv
```

核对缺口、组与标签后，split读取public-reviewed.csv。未经视觉审核的pending样本不参与划分。
后续独立实拍测试用 `split --test-only` 新建版本，不改变训练/验证清单。
具体命令和采集规范见 `ml/README.md` 与 `docs/ml-handover.md`。
