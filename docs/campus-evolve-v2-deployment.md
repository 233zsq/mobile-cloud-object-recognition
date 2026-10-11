# campus-evolve-v2 接入记录

2026-10-11，用户明确选择“先保留v2吧，然后上云和安卓”。部署该冻结模型；v3 的数据、训练结果及对照记录保留。管理员审批记录注明由 Codex 根据用户聊天指令代为登记，并绑定模型、主实验检查点及比较报告哈希；没有记作用户在网站点击批准。含账号信息的原审批附录仅保存在本地/服务器交付包。

## 模型与实验

| 项目 | 记录 |
| --- | --- |
| 模型 | campus-evolve-v2，FP32 MobileNetV2，8,939,040 字节 |
| 类别 / 数据 | campus-10-v4 / campus-evolve-data-v2 |
| 样本 | 1,807 训练，609 验证；验证不等于独立实拍测试 |
| 主实验 | campus-evolve-v2-seed42，验证准确率 0.91461412，宏 F1 0.91259696 |
| 种子43复核 | 准确率 0.91297209，宏 F1 0.91414233，F1 差 0.00154537 |
| 低置信阈值 | 0.50，仅用验证集选择，仍输出 Top-1 |
| 模型 SHA-256 | 7e2387600303333f714533aac1a0c1e4260425b06154dd7fa4ed920d01bef691 |
| 标签 SHA-256 | 3148fcb53e5859041bf7f6af5acbfb952a9d3fbd52a4fd334525b7d3af6a1064 |

原训练结果的代码提交记为 `unavailable`，原因是 WSL Git 无法读取 Windows 工作树指针。原文件未改写；两次训练保存的源码逐字节匹配提交 `135b0eb9f701fcece2075e2a7920d6090cc118ce`，据此生成单独的导出输入。核验方法、原结果哈希、源码逐文件哈希见发布包 `source-provenance.json`。发布元数据记录已核实提交。

完整609张验证图的 Keras / TFLite Top-1 无差异，最大分数差 `0.00000911951`。Windows 独立 LiteRT 环境的20张参考张量及图片链路通过。比较报告分别保存对固定 `campus-gpu-v1` 基准、对父模型 v1，以及 v3 对 v2 的开发比较；各报告集合口径按文件解释，不能直接混比不同验证集成绩。

## 云端

现有 `mobile-cloud-backend`、`mobile-cloud-inference` 和审核站点继续运行。模型包为
`/home/gongyi/apps/mobile-cloud-backend/models/campus-evolve-v2-backend`。
CPU 运行环境继续使用旧包 `.venv/bin/python`（Python 3.12.15、LiteRT 2.2.0、NumPy 2.1.3、Pillow 12.3.0），两个包的锁文件字节一致；**不能删除旧包环境**。后端代码仍是现有发布目录，通过 Unix socket 调用 CPU 解释器。

在服务器以 `gongyi` 身份执行切换：

```bash
python3 deploy/scripts/activate_model.py \
  --package /home/gongyi/apps/mobile-cloud-backend/models/campus-evolve-v2-backend \
  --model-sha256 7e2387600303333f714533aac1a0c1e4260425b06154dd7fa4ed920d01bef691
```

脚本拒绝重复激活同一版本；已有版本用健康接口核对。部署保存数据库原记录，追加登记模型及 v4 类别；未修改凭据、Nginx、TLS或端口。当前健康接口 `https://49.232.195.47/api/health` 返回 v2 / ready。

真实云端 CPU 对20张样例的参考张量、图片链路和输入像素均一致，已回传并通过训练端校验器。预热20次、单线程测100次：纯推理 P95 **15.06ms**，预处理加推理 P95 **50.21ms**，不含 HTTP / 网络。HTTPS 接口20张样例 Top-1及分数一致，并检查409模型版本冲突、401未授权；没有写入识别记录。证书校验与主机名校验开启。证据见 `experiments/reports/deployment/campus-evolve-v2/`，原始输入张量留在本地交付目录。

需要回退时，管理员从服务器私有目录
`shared/model-rollbacks/20261011T143013Z-campus-evolve-v2/` 恢复 `backend.env` 和 `inference.service`，保留原所有者/权限，再执行 `systemctl daemon-reload` 并重启两个服务，核对旧模型健康状态。该目录包含凭据，不得复制到 Git。已登记模型和评估记录继续保留。

## Android 与交付

本地交付目录 `ml-deliveries/campus-evolve-v2/` 包含后端包、完整交接归档、Android debug APK 及 `android-build.json`（含APK哈希）。模型二进制、样例、私有审批与环境不入 Git。Android 直接打包相同模型/标签/元数据，类别资产同步为 v4；输入沿用 `rgb-letterbox-v1`，不重复归一化。

应用包已构建并安装到用户的 MuMu 模拟器（Android 12 / SDK32，模拟器上报型号 ALN-AL00，不能视为华为真机）。91项 JVM 单元检查通过。中文工作区的测试类加载问题用临时 `subst` 英文盘符解决，详见 Android README。20张参考张量、20张图片链路均通过训练端独立校验；最大分数差约 `0.00000996`，最大输入像素差 `0.00003052`。预热20次、测100次，4线程纯推理 P95 10ms，解码加预处理和推理 P95 28.53ms；只作为模拟器记录。

用户另外明确授权将现有 API 令牌仅写入这台 MuMu 的 App 私有设置。令牌经SSH内存直接传入应用私有目录，验证后删除临时文件；没有保存在PC文件、APK、Git或聊天。模拟器上的真实 HTTPS 健康检查、认证和20张 `/api/infer` 同图核验通过，分数与参考一致，未写入识别记录。`CloudHandoverTest` 在无HTTPS配置/令牌时跳过，不能把跳过算作云端通过。

App 正式演示主链路为本机识别、记录上传与网页统计。当前云端推理由独立接口和交接测试验证，Android 界面的主动云端识别入口仍由对应成员接入。接下来用真实拍照记录验证上传和统计；真机 P95、约200张独立测试图的准确率/F1，以及实际网络等待仍待对应成员完成，不能从公开验证成绩或模拟器耗时推定达标。
