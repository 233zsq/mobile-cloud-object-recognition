# 项目协作说明

## 分支与提交

`main` 保存已集成的版本，各模块在功能分支开发，通过 Pull Request 说明修改内容与验证结果，再合并到 `main`。

首次参与时克隆完整仓库，每人保留自己的工作副本：

```bash
git clone https://github.com/233zsq/mobile-cloud-object-recognition.git
cd mobile-cloud-object-recognition
git switch -c feat/android-camera
```

每次开始工作前，在没有未提交修改时更新 `main`，再建立对应任务的分支：

```bash
git switch main
git pull --ff-only
git switch -c feat/backend-records
```

分支名也可使用 `feat/ml-baseline`、`feat/web-stats`、`docs/test-plan`；按当前任务选择，不需要预建所有分支。

提交前检查暂存内容。提交说明可用 `feat:`、`fix:`、`docs:`、`chore:`，正文写清一个实际变化。

```bash
git status
git add <本次修改的文件或目录>
git diff --cached
git commit -m "feat: add record upload endpoint"
git push -u origin <当前分支名>
```

当前结构初始化后，各模块负责人补充可执行的构建、启动与测试命令。Pull Request 中如实写明已验证、失败与尚未验证的内容。

## 跨模块交接

- 类别 ID、英文标签键与模型输出顺序由同一份冻结清单生成，变更时同步更新 Android、训练、数据库和 Web。
- 模型必须同时交付 tflite、`labels.txt`、版本、SHA-256、输入输出规格和预处理说明，见 `docs/model-contract.md`。
- 接口字段、UUID 去重、纠错修订号规则以 `docs/api/README.md` 的冻结版本为准，接口变更由前后端一起确认。
- 样本清单必须记录实物 ID、采集场次与划分。同一实物不跨集合；冻结测试集由组长管理。
- 测试与材料记录对应的代码、数据、APK、模型版本；计划目标不能填写为实测结果。

## 文件与配置

- 原始照片、处理图片、模型权重和检查点在本地管理并另行备份，不直接推入普通 Git。
- 样本清单和训练配置可进入 Git，清单路径使用相对仓库根目录的路径，例如 `data/raw/cup/cup-001.jpg`。
- `.env.example` 仅保留变量名称和无敏感信息的示例；真实密码、令牌、签名密钥与数据库备份不提交。
- `docs/planning/` 的已有计划书和完整分工是本地资料副本，不随公开仓库同步。报告、PPT 和演示说明分别放到对应目录，录屏另行存储并记录位置。
- 不提交 IDE 缓存、虚拟环境、依赖目录或构建产物；依赖清单和锁定文件应提交。
