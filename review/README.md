# 照片审核工作台

云端入口：<https://49.232.195.47:8443>。独立使用 `ubuntu`、`campus-review.service` 和回环8081，不改变现有443后端。组员通过一次性邀请建立个人账号；管理员冻结批次、下载训练包并审批候选模型。训练在本机GPU执行，Android后续接入。

8443使用浏览器信任的Let’s Encrypt IP证书，无需安装自签名证书。IP证书约6天有效，独立的 `campus-review-acme.timer` 每6小时检查续期；HTTP-01仅在签发期间临时使用80端口验证路径，结束后逐字节恢复原跳转配置。443的证书与配置保持原样，`deploy/certs/server.crt` 仍属于443后端。[官方IP证书与Certbot说明](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)。

## 使用

首次管理员邀请由服务器生成，24小时有效，一次使用。本地交付文件 `tmp/review-access.txt` 保存链接，不提交Git。管理员设置自己的账号密码后，在首页“邀请组员”生成7天有效的成员邀请。请通过私密渠道分享，服务不发送邮件或消息。

上传单帧JPEG/PNG/WebP，单张≤8MiB、≤1600万像素、短边≥128。填写真实类别、全组统一的实物ID、采集场次；同件实物始终使用同一个ID。预览移除EXIF，训练包保留原始字节和哈希。仅上传训练/开发验证照片；正式独立测试照片由组长另行保管。

列表每页24张，仅使用最长边320像素、≤32KiB的WebP缩略图，启用懒加载及异步解码；详情使用最长边960像素、≤160KiB的预览。浏览网页不传原始照片。图片采用登录鉴权后的 `private, no-cache` 和ETag，重复请求未变化时返回304；HTML、邀请、报告不缓存。[私有缓存与条件请求](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Caching)。

审核图片和训练ZIP共用持久的累计20GiB正文预算，达到上限拒绝新的传输；304和HEAD不收费，Range实际正文也计入。中断的传输可能按完整正文保守预扣。自本次升级起累计，不按月自动重置；该数不含TLS/HTTP开销、HTML以及其他443服务，不能作为腾讯云整机剩余500G的计量。服务器负责人需先核对腾讯云剩余额度，再通过环境变量 `REVIEW_EGRESS_LIMIT_GIB` 调整累计上限并重启此服务；不自动提高或重置预算。

公开候选带 Commons/Open Images 来源标签，可按来源和建议类别筛选。导入后全部待审核，保留作者、许可、来源链接、下载版本和旧审核理由。实物无法确认时网图实物ID可留空，重复组不可空。默认允许直接按住照片拖动框选，松开后保留选框，下一张仍默认开启；未框选时使用整图。清除选框或关闭开关恢复全图；点击或过小的拖动不会覆盖已有选框。选择完整主体和少量背景，原图区域宽高均≥128。保存审核后选框绑定修订，冻结或只读时不能改变。训练包保存原图与EXIF纠正后的像素框，本机导入时生成训练裁剪并保留原图哈希、感知哈希和来源身份；不把裁剪计作新增独立原图。

所有成员可查看照片。管理员在首页“品类分工”给已加入的账号分配品类；每个品类只有一位负责人，一人可负责多个品类。成员默认进入自己的品类，其他已分配品类只读；管理员可复核，但也不能覆盖别人正在编辑的照片。未分配品类允许任一成员领取，适合先审后分工。改派会撤销该品类的编辑占用，旧页面不能继续提交，操作保留日志。

首页支持品类快捷入口及任务范围、类别、来源筛选。“开始连续审核”领取当前筛选内可编辑的照片；“保存并审核下一个”保存后继续，“跳过，下一张”不保存草稿并释放占用。下一张与返回列表保留筛选，即使本张被改为其他真实类别也不会切换队列。没有可领取照片时返回列表提示，已完成、别人占用和别人负责的照片不会混作可审核任务。

逐张审核的操作集中在照片上方，桌面滚动时保持可见。待审核照片默认选择“通过”，只在点击保存后生效；已拒绝照片复审时保留原选择和说明。直接选择“被遮挡”或“此物品不是对应物品”会记录拒绝及原因；“其他”必须填写原因，也可选“暂不判断”。真实类别可在顶部纠正，框选入口紧邻大图；实物分组、来源、相关照片和历史记录默认收起。快捷原因和补充说明仍写入现有状态/原因字段，批次格式不变，升级前页面也可按旧字段提交。

同一照片同时只允许一个账号编辑，数据库事务保证同时领取不会撞到同一张。同账号重新打开或刷新同张照片会领取新凭据，旧页面不能提交或释放新页面的占用；服务端也检查修订号。占用默认15分钟，本页可见时每90秒自动续期。保存、跳过和退出立即释放；关闭或离开页面尝试释放，传输失败或浏览器异常退出时由超时兜底。占用失效后保留表单内容但禁用提交，先复制内容再刷新重新领取。服务升级前打开的旧页面需刷新。

审核可改类别与分组，拒绝必须说明原因。页面提示相同实物、重复组或感知近重复，需人工确认。过期页面提交返回409。照片冻结后不能改标签，完整事件日志保留在数据库。管理员将所有新通过照片冻结为新批次，下载含 `batch.json`、`samples.csv` 和原照片的ZIP。批次的归档、清单和照片均记录SHA-256。

审核与新批次使用类别 `campus-10-v4`：“伞”包括雨伞、手持遮阳伞及庭院或沙滩遮阳伞，不包含帐篷、遮阳棚和降落伞；标签键 `umbrella`、ID=1不变。键盘继承v3，包含独立外接和笔记本内置。目标须清楚可辨、是拍摄重点，或能通过选框裁出完整主体；仅作背景或严重遮挡时拒绝。历史基准仍保留v2，v3类别文件及旧批次也保持原字节。此前仅因内置键盘或遮阳伞被拒的未冻结照片，可筛选对应品类和“已拒绝”后人工复审；不自动批准或重写旧决定。

新模型比较报告从训练PC经SSH导入，网页展示原公开验证与实拍开发验证两个子集。管理员批准/拒绝并记录理由；批准后领取 `/candidates/<模型版本>/approval.json`。批准不替换443服务模型或Android模型。完整训练命令见 [ml-evolution.md](../docs/ml-evolution.md)。

## 开发与验证

### 百炼视觉初审

初审支持白名单固定快照 `qwen3-vl-flash-2026-01-22`（默认）及 `qwen3-vl-plus-2025-12-19`，使用非思考模式及JSON输出。以 `REVIEW_AI_MODEL` 选择模型，`REVIEW_AI_PROMPT_VERSION` 选择 `campus-ai-review-v3`（默认）或更严格的 `campus-ai-review-v4`；修改后重启服务生效。仅处理Commons/Open Images网图，成员实拍不外发。向百炼发送最长边512像素的JPEG预览，移除EXIF；已有人工裁剪时只审该区域，建议框再换算回原图。v3提示先独立判断实际主要主体，只发送图像和完整类别口径，不向模型透露抓取类别或人工通过/拒绝答案，也不发送账号、实物ID或分组信息；返回类别不匹配当前标签时转为人工确认。API密钥保存在Git外的0600文件，以 `REVIEW_AI_KEY_FILE` 指向；也支持 `DASHSCOPE_API_KEY`。请求仅发送至百炼北京官方HTTPS端点，不跟随重定向，不输出密钥或供应商错误正文。[官方调用说明](https://help.aliyun.com/zh/model-studio/vision)、[JSON输出说明](https://help.aliyun.com/zh/model-studio/qwen-structured-output)。

```bash
# 在服务器的current/review目录执行，先加载已有服务环境；不要打印环境内容
set -a
. /home/ubuntu/.config/campus-review/review.env
set +a
/home/ubuntu/apps/campus-review/venv/bin/flask --app wsgi ai-review --mode pilot --limit 50 \
  --report /home/ubuntu/apps/campus-review/shared/ai-pilot.json
# 试运行后可为尚未审核的网图生成建议；单次最多100张
/home/ubuntu/apps/campus-review/venv/bin/flask --app wsgi ai-review --mode pending --limit 50
```

`pilot`按类别及人工通过/拒绝分层抽取（种子42），报告建议通过样本与人工结果的一致率、分歧ID、覆盖数量和真实Token用量；它衡量的是初审效果，不是识别模型独立测试成绩。首页展示最近任务及当前提示版本的最近人工对照，详情展示建议及原因，可由人工点击“采用建议选框”并保存；此建议入口不会更改照片状态、类别、修订或冻结批次。严格自动分流由下述独立策略控制；模型自报置信度不作为自动批准依据。

缓存绑定原图SHA-256、现有选框、类别版本、完整提示词及固定模型版本。待审模式自动跳过当前输入已有建议的照片，可分批继续；重复调用不重复收费；改标签、选框或类别口径后旧建议失效。累计预算持久化在同一个SQLite数据库，按2026-10-09北京≤32K档标价估算：Flash输入/输出每百万Token为0.15/1.5元，Plus为1/10元；预算预留及结算自动匹配模型，安装默认累计1元、500次请求，当前云端授权30元、5000次请求，单次运行最多50张；免费额度和活动优惠未计入。调用前原子预留32K输入及500输出Token的费用；网络错误、进程中断等未知用量保留预留，不自动重试或重置。供应商、鉴权或预算错误停止任务；单图格式错误保留安全错误代码并继续，图片仍交人工审核。修复错误后可显式加 `--retry-errors` 重试已失败记录，历次已知用量和未知预留仍累计保留；正在处理或中断后停留在reserved的记录不会被自动接管。该预算仅约束这份服务密钥在此程序中的调用，账户实际费用以百炼账单为准。[官方价格](https://help.aliyun.com/zh/model-studio/model-pricing)。

Python≥3.12，已在Windows3.13及Ubuntu3.14验证；本模块不安装TensorFlow、NumPy或LiteRT。

```powershell
python -m venv review/.venv
review/.venv/Scripts/python.exe -m pip install -r review/requirements-dev.txt
New-Item -ItemType Directory tmp -Force
review/.venv/Scripts/python.exe -m pytest -q review/tests --basetemp=tmp/review-tests-new
```

`create_app()`要求至少32字符的 `REVIEW_SECRET_KEY`。默认Secure/HttpOnly/SameSite=Lax会话、POST CSRF、密码scrypt、邀请摘要、登录节流、受信任Host、图片解码预算及单进程串行图片解码。生产运行Gunicorn，不使用Flask开发服务器。[Flask部署说明](https://flask.palletsprojects.com/en/stable/deploying/)、[安全配置说明](https://flask.palletsprojects.com/en/stable/web-security/)。

## 运维

源码：`/home/ubuntu/apps/campus-review/releases/<归档摘要>/`；`current`原子指向当前版本。数据：`/home/ubuntu/apps/campus-review/shared/`（0700）；配置：`/home/ubuntu/.config/campus-review/review.env`（0600）。SQLite WAL适合当前小组规模。照片、数据库、邀请及配置都不进入Git。

本地 `python review/deploy/package.py` 只打包审核源代码、测试、类别和基准公开元数据，保存逐文件源码哈希及Git提交/工作区状态。上传归档并校验哈希后解压到新目录，在服务器执行 `python3 <发布目录>/review/deploy/install.py`。安装会运行网页测试、校验Nginx、仅重启自己的服务，并检查原后端配置哈希及健康；更新失败可恢复上一版本指针。安装需要 `ubuntu` 免密sudo；脚本不配置云防火墙。

证书工具独立安装在 `/opt/campus-review-acme`（Certbot5.8.0），不进入网页依赖环境。生产证书及私钥仅存服务器 `/etc/letsencrypt-campus-review/`；测试签发使用独立的同名 `-staging` 目录。`/etc/campus-review/tls.json` 是root管理的证书路径配置，后续网页部署会保留该选择。ACME账号、私钥、验证日志及配置备份均不进入Git。已由服务器所有者同意2026-07-06版Let’s Encrypt订户协议。

初次安装需由服务器所有者接受当期订户协议后执行；已有站点不要重复申请证书。以下在本仓库源码根目录执行，80端口须保持公网可达：

```bash
sudo python3 -m venv /opt/campus-review-acme
sudo /opt/campus-review-acme/bin/pip install -r review/deploy/requirements-acme.txt
sudo install -D -o root -g root -m 0755 review/deploy/acme.py /usr/local/libexec/campus-review-acme.py
sudo python3 /usr/local/libexec/campus-review-acme.py issue-staging
sudo python3 /usr/local/libexec/campus-review-acme.py issue
sudo python3 /usr/local/libexec/campus-review-acme.py dry-run
sudo install -m 0644 review/deploy/campus-review-acme.service review/deploy/campus-review-acme.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now campus-review-acme.timer
```

日常检查 `systemctl list-timers campus-review-acme.timer` 和 `journalctl -u campus-review-acme`；续期失败需在到期前修复。手动续期必须使用上述脚本的 `renew` 操作，以便建立及恢复HTTP验证路径。脚本遇到其他人并发修改共享Nginx配置时拒绝覆盖，原始备份保存在root可读的 `/var/lib/campus-review-acme/`；此时由运维核对变更后修复。服务被中断时 `ExecStopPost` 尝试恢复80配置，重启后下次操作也会先恢复。验证公网可信证书可在本地执行：

```powershell
review/.venv/Scripts/python.exe review/deploy/check.py --output tmp/review-https-check.json
```

默认使用系统信任库；`--ca` 只供明确需要私有CA的独立环境，禁止关闭TLS校验。

```bash
sudo systemctl status campus-review
sudo journalctl -u campus-review -n 50 --no-pager
sudo nginx -t
sudo systemctl restart campus-review
python3 /home/ubuntu/apps/campus-review/current/review/deploy/manage.py register-candidate /path/to/comparison.json
python3 /home/ubuntu/apps/campus-review/current/review/deploy/manage.py import-public /path/to/public-review.zip --report /home/ubuntu/apps/campus-review/shared/public-import-report.json
```

公开候选在训练PC采集，默认每类240张；第二轮经批准可显式提高至750张，本轮最多新增2000张，照片合计仍限3GiB，Open Images索引仍限1.2GiB。先用 `python review/deploy/prepare_public.py --root <训练数据仓库> --output <候选ZIP>` 打包已有候选，自动排除已冻结训练/验证/测试清单中的样本ID和照片哈希；核验包哈希再经SSH上传。服务器导入命令不抓取任意URL，重复照片跳过，单张损坏记录原因，未审核照片不会进入训练包。照片和候选ZIP不进入Git。

手工备份先停止 `campus-review` 写入，打包 `shared` 与配置，再启动；归档需保存到受控的组内备份位置。恢复先在独立目录验证数据库、照片和批次哈希，再切换服务目录。管理员邀请过期且尚无管理员时，可通过上述manage入口重新执行 `bootstrap`。现有管理员恢复由服务器负责人处理，不开放公网重置接口。

### 固定样本比较Plus与提示词

`--cohort`只用于pilot，读取既有试运行报告的照片ID、类别、人工状态和修订，保持相同顺序。参考发生变化时，在任何调用前停止；不向模型发送参考答案。报告补充照片哈希、选框、参考文件哈希、模型费率、当前样本累计用量及本轮增量用量。缓存包含模型和完整提示词，各模型及各版提示不会相互覆盖，所有配置共享原有总预算。

```bash
REVIEW_AI_MODEL=qwen3-vl-plus-2025-12-19 REVIEW_AI_PROMPT_VERSION=campus-ai-review-v3 \
  /home/ubuntu/apps/campus-review/venv/bin/flask --app wsgi ai-review --mode pilot --limit 20 \
  --cohort /home/ubuntu/apps/campus-review/shared/ai-pilot-v2-20261009.json \
  --report /home/ubuntu/apps/campus-review/shared/ai-plus-v3-first20.json
# 保持相同cohort，改为campus-ai-review-v4比较更严格的主体规则。
```

`campus-ai-review-v5`按物品构造而非临时用途判断类别，明确裁剪不能恢复遮挡、改变类别或消除模糊；避免把“更严格”等同于排除正常背景。合法选框在原图不足128像素时，降为不确定且不提供可采用选框，仍需人工确认。

人工记录不是标准答案。报告的 `pass_reference_agreement` 表示通过建议与现有人工记录的一致率，`pass_reference_disagreements`、`reject_reference_disagreements` 分别保留两个方向的分歧，`approved_needing_crop_recheck` 标出已通过但建议裁剪的照片。旧字段 `pass_precision`、`false_passes` 仅为兼容历史消费者的同义字段，不能当作准确率或已确认错误。复核时先按类别规则独立看图，再查看双方理由；分歧需第二位审核人或管理员裁决，一致项仍抽检。当前未增加独立双人盲审或自动裁决功能。

单次建议与严格分流是两个入口。建议接口不改状态；严格分流经管理员开启后，只处理未经人工修改、没有正在编辑占用的待审网图。历史人工通过/拒绝、实拍和冻结照片都跳过。

### 默认：Flash优先，Max复核

`REVIEW_TRIAGE_POLICY=flash-max-cascade-v1` 是默认自动审核策略，主模型为 `REVIEW_TRIAGE_PRIMARY_MODEL=qwen3.8-flash`。Flash明确通过或拒绝时直接处理，不调用Max；不确定或理由含疑问时交 `qwen3.8-max-0902` 复核。裁剪、其他类别标签和Max仍不确定的结果留人工；格式/API错误不触发Max兜底，预算或供应商故障停止当前批次。

两级都使用 `campus-ai-review-v6` 的同一图片与类别口径。Flash关闭思考，输出上限500 Token；Max保留1024思考/1524总输出上限，各自费用及缓存独立核算。最多50张、累计30元/5000次授权上限、每种结果至少10%且至少1张抽检、自动通过抽检完成后才能冻结的规则保持不变。未获得独立准确率结论，不把模型的明确判断当作质量保证。

任务创建时冻结策略和两级配置，实际依据只记录用到的一级或两级；写入前重新校验账本和分流路径。进行中的历史Max或严格任务不会因默认设置变化而改变；切换部署等待当前批次完成，历史决定、抽检、撤回与累计用量保留。最近任务区标明该批采用的策略及Flash明确/Max复核数量。

### Max直接审核（保留选项）

设置 `REVIEW_TRIAGE_POLICY=max-direct-v1` 和 `REVIEW_TRIAGE_PRIMARY_MODEL=qwen3.8-max-0902` 可选择Max直接审核。Max/v6单独判断，明确通过或拒绝可自动处理；质量原因的明确拒绝也可处理，裁剪、标签冲突、不确定或接口异常留给人工，不再要求旧模型同意。仅处理未被人工修改、未冻结且未被领取的待审公开照片。此前云端选择过 Max/v6；开发对照、已知误判与有界试运行见 [Max记录](experiments/2026-10-10-qwen38-max.md)。

Max使用固定快照，v6开启思考并限制思考1024 Token、总输出1524 Token，推理Token一并计费及预留。北京输入/输出每百万Token标价12/36元。[模型说明](https://help.aliyun.com/zh/model-studio/qwen3-8-max)、[思考配置](https://help.aliyun.com/zh/model-studio/deep-thinking)。输入、输出及未知用量都纳入原有累计30元/5000次上限；不会因更换模型重置历史。

每批每种自动结果随机抽检至少10%、至少1张，不按类别要求全部重审。未完成自动通过抽检时不能冻结；异常中断的已自动决定照片全部待抽检。开发试运行以明显误判约5%以内为目标，小样本不能证明长期错误率。抽检发现集中错误时，应暂停、撤回并复核同批。历史严格任务保留自己的策略、配置、证据与抽检要求，切换模型不会重新解释旧记录。

2026-10-09早期云端曾选择 `qwen3-vl-plus-2025-12-19` / `campus-ai-review-v3` 作为辅助建议配置；v4、v5试验与局限见 [Plus对照记录](experiments/2026-10-09-bailian-plus.md)。代码默认值仍为Flash，可通过服务环境变量选择固定模型/提示，历史缓存及累计用量保留。

### Qwen3.8与严格分流

同一策略、照片修订和模型/提示输入已分流的人工待审项，下批自动跳过，保持人工队列不变；策略或缓存代次变化后可重新检查。预演不写入此进度，预算/供应商中断的当前样本也不会记为已完成。

新增 `qwen3.8-flash`：支持图片和JSON输出，北京输入/输出每百万Token标价0.8/2.7元，非思考模式。[官方说明](https://help.aliyun.com/zh/model-studio/qwen3-8-flash)。当前官方只公布别名，本项目记录内部缓存代次 `review-evaluation-20261009-r1`，不能据此声称供应商权重已固定；供应商升级后应重新抽样评测并更换代次。模型与提示词通过不可变 `Profile` 独立传递，不改变其他任务的全局模型或价格。

同图实测、适用范围与局限见 [Qwen3.8对照和分流记录](experiments/2026-10-09-qwen38-triage.md)。2026-10-09云端曾选择3.8/v4作为辅助建议与第一步分流；此配置及历史Plus结果保留。报告的 `run_usage` 为所选输入缓存键在执行前后的账本增量，`ledger_window_usage` 单独记录全库窗口增量；有并行任务时二者可能不同，同一输入键的并发开销也不能当作独占归属。

严格策略可显式设置 `REVIEW_TRIAGE_POLICY=strict-crosscheck-v2`，依次核验：`REVIEW_TRIAGE_PRIMARY_MODEL`（Qwen3.8）/v4、VL-Plus/v3、VL-Plus/v5。前一步不满足候选条件或出现分歧立即交人工，节省后续调用。只有三项均为同类、无问题、无需裁剪的通过，才自动通过；只有三项均明确为表外物或图解，才自动拒绝。遮挡、模糊、目标太小、其他十类标签、选框及不确定均留给人工。理由出现人物场景、局部或不确定等描述时也会拦截。交叉核验用于保守筛选，不把Plus或人工历史当标准答案；同一供应商模型可能产生共同偏差，无法保证零错误。

首页“AI严格分流”可开启/暂停、启动1–50张任务、进入抽检或查看自动决定。一次只允许一个分流任务；网页单批最多50张。经批准的扩容流程可串行执行多批，每次仍检查累计预算和调用上限。任务不在HTTP请求中等待API，刷新首页查看进度；暂停在当前调用结束后阻止后续自动写入。管理员在详情页可撤回未冻结的AI决定；人工也可领取后保存新的判断。并发占用和修订冲突仍受原有规则保护。模型建议、照片哈希、策略、任务、自动状态事件及撤回事件保存在SQLite中；训练包收据包含仍由AI决定的照片的依据哈希。

历史任务保留10%的原抽检比例；新任务在创建时固定抽检比例，默认每种结果约5%且至少1张。任务异常中断来不及抽样时，已决定照片默认全部待抽检。充电器和钥匙尚无对照样本，这两类自动通过全部设为待抽检。密集大量物品、用途泛称电子设备的照片也拦截为人工。人工保存即结束该张抽检，自动通过抽检未完成时冻结返回409。发现错误应先暂停、撤回并复核同批，调整策略后另做评测。

预算使用服务环境 `REVIEW_AI_BUDGET_NANO`（十亿为1元）和 `REVIEW_AI_MAX_CALLS`。安装默认仍是1元/500次；2026-10-10所有者批准本轮新增50元；起点账面估算14.6814493元，因此本轮累计上限64.6814493元，仍限5000次调用、单批50张。全部模型、对照试验和分流共享原有账本，不重置历史；费用为标价估算，实际扣费和免费额度以百炼账单为准。

```bash
# 服务器：使用已有私密配置运行，actor为现有管理员ID。
python3 review/deploy/manage.py ai-triage-policy --actor <管理员ID> --enabled true
python3 review/deploy/manage.py ai-triage --actor <管理员ID> --limit 20
# 上一条是只读预演；添加--apply才会应用，且策略须开启。
python3 review/deploy/manage.py ai-triage --actor <管理员ID> --limit 50 --apply
python3 review/deploy/manage.py ai-triage-policy --actor <管理员ID> --enabled false
```


2026-10-10扩容：网页默认进入“人工疑难”，另列“等待AI”“AI处理失败”和“AI待抽检”；新照片不再直接混入人工任务。疑难/失败记录绑定照片哈希、修订、类别、提示词、模型缓存代次和推理设置，配置或照片变化后失效。自动决定及冻结历史仍可查看。人工领取、改标签、撤回、冻结规则继续有效。

增量采集使用 `scripts/collect-evolution-candidates.py --root <数据根目录> --state <本轮JSON> --stop-after 500`；检查首批后用同一state续至2000。可选 `--remote-fetch tencent` 仅从已有SSH服务器获取白名单官方API/图片，不开放代理端口。若来源不足、预算或调用上限触发，保留具体缺口，不以重复照片补数。打包时传入 `prepare_public.py --manifest <本轮CSV> --exclude <网站已审核身份CSV>`，避免已拒绝照片再次送审。独立实拍测试不进入此流程。
