# 腾讯云后端部署

2026-10-08 已在 `49.232.195.47` 部署 Flask、Gunicorn、MySQL 和 Nginx；2026-10-22 ICP 备案完成后启用正式域名 `fieldnotes.bigdogaaa.cn`（当前正式入口，旧 IP 入口保留兼容），域名与审核入口配置见 [FieldNotes 域名说明](fieldnotes-domain/README.md)。服务器内及公网 HTTPS 验收通过，HTTP 自动跳转 HTTPS；真实入库、去重、冲突处理及服务重启验证完成。

## 2026-10-14 审核站独立更新

审核站职责拆分已完成部署。本地与 Linux 隔离环境各 148 项测试通过，可信 HTTPS 验收通过；切换前保存私有 SQLite 备份及旧发布，切换后核对持久表内容、结构、照片/冻结批次和配置身份。通用维护说明见 [审核站运维](../review/README.md#2026-10-14-职责拆分发布)，结果见 [验收摘要](../tests/evidence/review-refactor-deployment-20261014.json)；具体发布和备份位置保留在私有交付记录。

## 2026-10-12 后端与统计页

当时模型为campus-evolve-v2，类别campus-10-v4；health返回实际模型和当次后端提交版本。已增加修订号纠错、分页记录、统计和类别接口，Flask与Nginx均校验非空API_TOKEN。根路径提供Web统计页，页面输入现有口令后每5秒刷新，口令只在页面内存。443与8443现共用已签发、自动续期的可信IP证书；原自签证书保留为回退资料。

2026-10-13 已上线可选择 v2/v3 的云端推理，2026-10-14 实读后端健康状态为 `campus-evolve-v3` / `ready`。v3 的范围判断、人工确认和交接记录见 [open-set-recognition.md](../docs/open-set-recognition.md)。审核站与后端分别发布；代码拆分不意味着两处服务自动升级。

本次不新增依赖或改变数据库结构。用固定提交生成发布归档，通过SHA-256核对后，按以下流程部署；staging.json记录旧发布、待激活发布和Nginx哈希，激活时使用这些值。

```bash
# 将归档与deploy_dashboard.py上传到shared后，以gongyi执行。
python3 /实际工具路径/deploy_dashboard.py stage \
  --archive /home/gongyi/apps/mobile-cloud-backend/shared/实际归档.tar \
  --sha256 <归档SHA256> --revision <完整Git提交>
# 暂存先运行隔离MySQL/SQLite回归及模型就绪检查。
sudo -n python3 /暂存发布/deploy/scripts/deploy_dashboard.py activate \
  --release /暂存发布 --expected-current /staging.json中的旧发布 \
  --expected-nginx-sha256 <staging.json中的Nginx哈希>
```

只切换后端发布和增加根路径/静态资源代理，不执行db-init，不更换模型/凭据/证书，不改审核站点。共享ACME续期锁保证80验证期间不改Nginx；配置与暂存时不同则拒绝覆盖。失败恢复旧发布及原Nginx配置；成功回退信息在shared/dashboard-rollback-*，验收在shared/dashboard-<提交前缀>。不要用provision.py inference重新启用旧模型。

手动回退时，管理员使用本次rollback目录中的previous-release.txt和nginx.conf，在相同ACME锁保护下恢复current链接及Nginx，检查nginx -t，重启后端并reload Nginx。保留数据库和当前模型配置，再核对health、记录及审核站点。

## 首次实例配置（2026-10-08历史记录）

| 项目 | 实际配置 |
| --- | --- |
| 系统、Python | Ubuntu 26.04 LTS x86_64，Python 3.14.4 |
| 组件 | Flask 3.1.3、Gunicorn 25.3.0、MySQL 8.4.11、Nginx 1.28.3 |
| 应用源码 | `9eb92b9f385a25c0e4cbce6e737fed9bf8f085c2` |
| 归档 SHA-256 | `307c4ce6bcd50fb435f0e195a11224cb82c7e2034d839765b88fdec171339a5e` |
| 当前发布 | `/home/gongyi/apps/mobile-cloud-backend/releases/9eb92b9-307c4ce6` |
| 稳定入口 | `/home/gongyi/apps/mobile-cloud-backend/current`，指向当前发布 |
| 真实配置 | `/home/gongyi/.config/mobile-cloud-backend/backend.env`，0600；发布根目录 `.env` 链接到它 |
| 数据库 | `object_recognition`；四张表、10 个类别及 `expanded-cpu-v1` 元数据已初始化 |
| Gunicorn | 单 worker、2 threads，只监听 `127.0.0.1:8080` |
| MySQL | 只监听回环地址；128MiB buffer pool、40 个连接、关闭 Performance Schema |
| 公网入口 | `https://fieldnotes.bigdogaaa.cn`（2026-10-22 起；旧 `https://49.232.195.47` 保留兼容）；80 跳转到 443 |
| 模型 | 初始记录发布未加载；新增CPU推理服务的安装和启用见 INFERENCE.md |

原 `/home/gongyi/projects/mobile-cloud-object-recognition` 的 ML 工作区保留。此次发布使用固定提交归档，部署脚本、配置模板和证据在本 PR 后续提交维护。

## HTTPS 与认证

2026-10-12 起，现有443服务使用 `/etc/letsencrypt-campus-review/live/campus-review-ip/fullchain.pem`，与8443共用可信IP证书及现有自动续期任务。Android已包含系统CA信任，无需随短期证书续期重发APK。`certs/server.crt`及服务器原自签证书仅用于历史部署回退。首次引导部署仍生成自签证书，已有可信证书后可运行 `sudo python3 deploy/scripts/public_tls.py` 安全切换；脚本持有ACME锁，备份并验证配置，失败恢复。

原自签证书的 SHA-256 指纹（回退资料）：`73:7D:DB:0A:98:47:3E:94:E2:08:B1:D6:C7:5B:A6:5A:6A:9D:D7:0F:CF:6E:B5:42:AD:63:E2:33:B7:68:02:D6`。

`GET /api/health` 不要求令牌。其余 `/api/` 请求由 Nginx 校验 `Authorization: Bearer <API_TOKEN>`，令牌区分大小写；缺失或错误返回 401。真实令牌在服务器配置的 `API_TOKEN` 字段，渲染后的 Nginx map 为 root 所有、0600。当前Flask也执行相同校验，直接访问回环Gunicorn不能绕过非空口令。

从仓库根目录验证（Windows）：

```powershell
curl.exe --noproxy "*" https://fieldnotes.bigdogaaa.cn/api/health
```

初始记录发布结果为 `status=ok`、`version=0.1.0+9eb92b9`、`model_loaded=false`。启用独立推理工作进程后返回新发布版本、model_loaded=true、model_version=campus-gpu-v1及model_status=ready。记录调用需配置令牌及证书信任；不能把忽略证书验证作为正式客户端配置。后续更换受信任证书时，同步更新客户端信任配置和 API 地址。

腾讯云安全组放行 443 后，公网 HTTPS 已验证通过。入站规则为 `TCP:443`、来源 `0.0.0.0/0`、允许，见 [腾讯云安全组操作说明](https://cloud.tencent.com/document/product/213/112614)。不需要开放 MySQL 3306/33060 或 Gunicorn 8080。

## 服务管理

SSH 登录 gongyi 后：

```bash
sudo systemctl status mobile-cloud-backend mysql nginx
sudo journalctl -u mobile-cloud-backend -n 100 --no-pager
sudo systemctl restart mobile-cloud-backend
sudo nginx -t
curl https://fieldnotes.bigdogaaa.cn/api/health
```

服务定义在 `systemd/mobile-cloud-backend.service`，代理配置在 `nginx/mobile-cloud-backend.conf`。服务已设自动启动及故障重启，MemoryHigh/MemoryMax 为 192MiB/384MiB。初始实测 MySQL 约 230MiB、后端约 73MiB，整机仍可用约 526MiB，已有约 1.1GiB 交换空间被使用；尚未完成负载测试。

## 发布与回退

脚本针对该账号和目录。打包只包含指定 Git 提交，不包含未跟踪配置、虚拟环境或私钥：

```powershell
python deploy/scripts/package_release.py --revision backend
```

通过固定主机指纹的 SSH 上传归档，检查 SHA-256 后，解压到新的 `/home/gongyi/apps/mobile-cloud-backend/releases/<提交前缀>-<归档哈希前缀>`。归档自带 `SOURCE_REVISION`；不要覆盖正在使用的发布目录。

新服务器安装前执行 `python3 deploy/scripts/provision.py mysql-config`，再安装 MySQL、Nginx、Python venv 和 OpenSSL。后续发布在新的发布目录执行：

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install --only-binary=:all: -r backend/requirements-dev.txt
backend/.venv/bin/python deploy/scripts/verify_server.py tests
python3 deploy/scripts/provision.py application
python3 deploy/scripts/provision.py nginx
python3 deploy/scripts/provision.py backup
backend/.venv/bin/python deploy/scripts/verify_server.py http
```

初始化期间应用账号临时拥有该库的 DDL 权限，结束后仅保留 SELECT、INSERT、UPDATE。脚本保留已有密码、表和种子，不升级旧表；结构升级需要独立版本化迁移。`application` 生成发布的 `.release.env` 版本信息并原子更新 current；systemd 读取当前发布版本，优先于共享配置的 APP_VERSION。`nginx` 保留已有证书，不自动续期。

后续发布异常时可将 current 原子切回已验证的旧发布并重启后端。已有历史发布可回退；不通过删除数据库回退服务。

## 备份与恢复

`mobile-cloud-backend-backup.timer` 每日备份应用库、保留七天。备份在 `/var/backups/mobile-cloud-backend/`，目录 0700、文件 0600，使用本机 root/socket 认证，不在命令行传密码。实现见 `scripts/backup_database.py`。

```bash
sudo systemctl list-timers mobile-cloud-backend-backup.timer
sudo systemctl start mobile-cloud-backend-backup.service
sudo journalctl -u mobile-cloud-backend-backup.service -n 20 --no-pager
```

已把备份恢复到随机验证库，核对类别和记录后仅删除验证库。正式恢复前需暂停写入、保留当前备份并先做隔离恢复；不能直接清空正式库。2026-10-12已新增本机异机副本，完成四表恢复及哈希核验，见[本次验收](../docs/cloud-records-dashboard-20261012.md)。异机副本需定期更新，服务器七天保留计划不变。

## 验收

证据见 [server-deployment-20261008.json](../tests/evidence/server-deployment-20261008.json)：75 项通过、3 项 SQLite 下的 MySQL 专用用例跳过，真实 MySQL 用例执行；初始 SQL、HTTPS 201/200/409、四个并发首次上传、实际服务重启后去重、令牌保护及备份恢复通过。临时账号、验证库及正式库测试记录已清理。

公网已实测 HTTP 308、HTTPS 健康 200、无令牌 401 及正确令牌的入库 201、重试 200、冲突 409。公开证书通过固定 SSH 主机指纹渠道取得，TLS 验证未跳过。
## 云端推理接入

新增 `POST /api/infer` 使用独立 Python 3.12 CPU 模型进程，保留当前 Flask/MySQL 部署；安装、回传文件与回退说明见 [INFERENCE.md](INFERENCE.md)。

## 2026-10-12 自适应识别网页（/ios）

`https://fieldnotes.bigdogaaa.cn/ios/` 提供手机、平板和PC共用的云端识别页面。页面是纯静态文件，
由 nginx 直接托管（`/var/www/mobile-cloud-ios/`），**不经过** Flask 发布流程，也不改数据库、模型、口令
和审核站。静态更新与证书切换使用独立脚本；实现与验收记录见 [web/ios/README.md](../web/ios/README.md)。

```bash
sudo python3 deploy/scripts/apply_ios_static.py   # 备份 + 写入 location + nginx -t + reload
```

注意两点：

- **nginx 配置哈希会随静态路由和证书配置变化**（当前以服务器实读为准）。`deploy_dashboard.py activate` 会用 staging 时记录的
  `--expected-nginx-sha256` 校验配置，因此下一次发布统计页前必须重新暂存以记录新哈希，否则激活会按设计拒绝覆盖。
  回退配置在 `shared/nginx-mobile-cloud-backend-pre-ios-*.conf`。
- 静态页用 `alias` 直接读取 `/var/www/mobile-cloud-ios/`，与 `current` 发布目录解耦；页面调用的 `/api/*`
  仍是同一个 Flask 发布，两者互不影响。

静态包先由 `python scripts/package-web.py --output <新归档路径>` 生成，再使用 `publish_ios.py <shared目录中的归档> --sha256 <归档哈希>` 更新。打包与发布共用可信的 `web/ios/runtime-files.json`，目前包含 21 个运行文件及嵌套模块；依赖闭包、路径和哈希通过后原子切换目录指针。工具从完整仓库运行，旧版本保存在 `/var/www/mobile-cloud-ios-releases/`；测试和 README 不公开托管。

## 2026-10-22 正式域名与 ICP 备案

- 正式入口 `https://fieldnotes.bigdogaaa.cn`：`/`、`/assets/`、`/ios/`、`/api/*` 与 `/review/` 同域；`opencode.bigdogaaa.cn` 是 OpenCode 客户端 API。旧 `https://49.232.195.47` 入口保留兼容，旧 `:8443` 以 308 跳转到 `/review/`。
- 域名站点配置在服务器 `/etc/nginx/conf.d/fieldnotes.conf`，仓库副本见 [fieldnotes.nginx.conf](fieldnotes-domain/fieldnotes.nginx.conf)。旧 IP 默认站与 8443 跳转仍由 `sites-available/` 原文件承担，未新增公网业务端口。
- 域名为腾讯云免费 DV 证书（TrustAsia），位于服务器 `/etc/fieldnotes-tls/`，北京时间 2027-01-20 12:59:59 到期。控制台已开启自动续费，但自动续费只负责签发新证书，**不会自动替换自建 Nginx 上的文件**；续期后须下载证书并按 [FieldNotes 域名说明](fieldnotes-domain/README.md) 重新部署，否则整站 HTTPS 失效。
- 合规：主页、`/ios/` 与 `/review/` 页脚展示 `京ICP备2026070624号` 并链接工信部备案系统。
- 本轮只改展示层：当前发布内的 `web/index.html`、`web/assets/css/dashboard.css`、`/var/www/mobile-cloud-ios/` 的 `index.html`/`app.css` 与审核模板 `base.html` 就地修补，改前备份并记录哈希；完整改动已提交到 `feat/fieldnotes-icp-20261022` 分支，下次正式打包再走发布流程。详见 [域名说明](fieldnotes-domain/README.md)。
