# 照片审核工作台

云端入口：<https://49.232.195.47:8443>。独立使用 `ubuntu`、`campus-review.service` 和回环8081，不改变现有443后端。组员通过一次性邀请建立个人账号；管理员冻结批次、下载训练包并审批候选模型。训练在本机GPU执行，Android后续接入。

8443使用浏览器信任的Let’s Encrypt IP证书，无需安装自签名证书。IP证书约6天有效，独立的 `campus-review-acme.timer` 每6小时检查续期；HTTP-01仅在签发期间临时使用80端口验证路径，结束后逐字节恢复原跳转配置。443的证书与配置保持原样，`deploy/certs/server.crt` 仍属于443后端。[官方IP证书与Certbot说明](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)。

## 使用

首次管理员邀请由服务器生成，24小时有效，一次使用。本地交付文件 `tmp/review-access.txt` 保存链接，不提交Git。管理员设置自己的账号密码后，在首页“邀请组员”生成7天有效的成员邀请。请通过私密渠道分享，服务不发送邮件或消息。

上传单帧JPEG/PNG/WebP，单张≤8MiB、≤1600万像素、短边≥128。填写真实类别、全组统一的实物ID、采集场次；同件实物始终使用同一个ID。预览移除EXIF，训练包保留原始字节和哈希。仅上传训练/开发验证照片；正式独立测试照片由组长另行保管。

列表每页24张，仅使用最长边320像素、≤32KiB的WebP缩略图，启用懒加载及异步解码；详情使用最长边960像素、≤160KiB的预览。浏览网页不传原始照片。图片采用登录鉴权后的 `private, no-cache` 和ETag，重复请求未变化时返回304；HTML、邀请、报告不缓存。[私有缓存与条件请求](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Caching)。

审核图片和训练ZIP共用持久的累计20GiB正文预算，达到上限拒绝新的传输；304和HEAD不收费，Range实际正文也计入。中断的传输可能按完整正文保守预扣。自本次升级起累计，不按月自动重置；该数不含TLS/HTTP开销、HTML以及其他443服务，不能作为腾讯云整机剩余500G的计量。服务器负责人需先核对腾讯云剩余额度，再通过环境变量 `REVIEW_EGRESS_LIMIT_GIB` 调整累计上限并重启此服务；不自动提高或重置预算。

公开候选带 Commons/Open Images 来源标签，可按来源和建议类别筛选。导入后全部待审核，保留作者、许可、来源链接、下载版本和旧审核理由。实物无法确认时网图实物ID可留空，重复组不可空。成员可勾选“只使用我框选的主体区域”，在预览上拖动选择完整主体和少量背景；原图区域宽高均≥128。保存审核后选框绑定修订，冻结后不能改变。训练包保存原图与EXIF纠正后的像素框，本机导入时生成训练裁剪并保留原图哈希、感知哈希和来源身份；不把裁剪计作新增独立原图。

所有成员可查看照片。管理员在首页“品类分工”给已加入的账号分配品类；每个品类只有一位负责人，一人可负责多个品类。成员默认进入自己的品类，其他已分配品类只读；管理员可复核，但也不能覆盖别人正在编辑的照片。未分配品类允许任一成员领取，适合先审后分工。改派会撤销该品类的编辑占用，旧页面不能继续提交，操作保留日志。

首页支持品类快捷入口及任务范围、类别、来源筛选。“开始连续审核”领取当前筛选内可编辑的照片；“保存并审核下一个”保存后继续，“跳过，下一张”不保存草稿并释放占用。下一张与返回列表保留筛选，即使本张被改为其他真实类别也不会切换队列。没有可领取照片时返回列表提示，已完成、别人占用和别人负责的照片不会混作可审核任务。

逐张审核的操作集中在照片上方，桌面滚动时保持可见。待审核照片默认选择“通过”，只在点击保存后生效；已拒绝照片复审时保留原选择和说明。直接选择“被遮挡”或“此物品不是对应物品”会记录拒绝及原因；“其他”必须填写原因，也可选“暂不判断”。真实类别可在顶部纠正，框选入口紧邻大图；实物分组、来源、相关照片和历史记录默认收起。快捷原因和补充说明仍写入现有状态/原因字段，批次格式不变，升级前页面也可按旧字段提交。

同一照片同时只允许一个账号编辑，数据库事务保证同时领取不会撞到同一张。同账号重新打开或刷新同张照片会领取新凭据，旧页面不能提交或释放新页面的占用；服务端也检查修订号。占用默认15分钟，本页可见时每90秒自动续期。保存、跳过和退出立即释放；关闭或离开页面尝试释放，传输失败或浏览器异常退出时由超时兜底。占用失效后保留表单内容但禁用提交，先复制内容再刷新重新领取。服务升级前打开的旧页面需刷新。

审核可改类别与分组，拒绝必须说明原因。页面提示相同实物、重复组或感知近重复，需人工确认。过期页面提交返回409。照片冻结后不能改标签，完整事件日志保留在数据库。管理员将所有新通过照片冻结为新批次，下载含 `batch.json`、`samples.csv` 和原照片的ZIP。批次的归档、清单和照片均记录SHA-256。

审核与新批次使用类别 `campus-10-v4`：“伞”包括雨伞、手持遮阳伞及庭院或沙滩遮阳伞，不包含帐篷、遮阳棚和降落伞；标签键 `umbrella`、ID=1不变。键盘继承v3，包含独立外接和笔记本内置。目标须清楚可辨、是拍摄重点，或能通过选框裁出完整主体；仅作背景或严重遮挡时拒绝。历史基准仍保留v2，v3类别文件及旧批次也保持原字节。此前仅因内置键盘或遮阳伞被拒的未冻结照片，可筛选对应品类和“已拒绝”后人工复审；不自动批准或重写旧决定。

新模型比较报告从训练PC经SSH导入，网页展示原公开验证与实拍开发验证两个子集。管理员批准/拒绝并记录理由；批准后领取 `/candidates/<模型版本>/approval.json`。批准不替换443服务模型或Android模型。完整训练命令见 [ml-evolution.md](../docs/ml-evolution.md)。

## 开发与验证

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

公开候选在训练PC采集，继续遵守每类240张、照片合计3GiB及来源索引限额。先用 `python review/deploy/prepare_public.py --root <训练数据仓库> --output <候选ZIP>` 打包已有候选，自动排除已冻结训练/验证/测试清单中的样本ID和照片哈希；核验包哈希再经SSH上传。服务器导入命令不抓取任意URL，重复照片跳过，单张损坏记录原因，未审核照片不会进入训练包。照片和候选ZIP不进入Git。

手工备份先停止 `campus-review` 写入，打包 `shared` 与配置，再启动；归档需保存到受控的组内备份位置。恢复先在独立目录验证数据库、照片和批次哈希，再切换服务目录。管理员邀请过期且尚无管理员时，可通过上述manage入口重新执行 `bootstrap`。现有管理员恢复由服务器负责人处理，不开放公网重置接口。
