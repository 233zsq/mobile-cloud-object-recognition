# 腾讯云后端部署

2026-10-08 已在 `49.232.195.47` 部署 Flask、Gunicorn、MySQL 和 Nginx。服务器内及公网 HTTPS 验收通过，HTTP 自动跳转 HTTPS；真实入库、去重、冲突处理及服务重启验证完成。

## 当前实例

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
| 公网入口 | `https://49.232.195.47`；80 跳转到 443 |
| 模型 | 未加载，云端推理接口尚未实现 |

原 `/home/gongyi/projects/mobile-cloud-object-recognition` 的 ML 工作区保留。此次发布使用固定提交归档，部署脚本、配置模板和证据在本 PR 后续提交维护。

## HTTPS 与认证

按 IP 测试部署方案使用自签名证书。公开证书见 [certs/server.crt](certs/server.crt)，私钥仅在服务器 `/etc/mobile-cloud-backend/tls/server.key`，权限 0600。证书有效期至北京时间 **2027-01-06 19:58:23**，到期前需更换并更新客户端信任。

SHA-256 指纹：`73:7D:DB:0A:98:47:3E:94:E2:08:B1:D6:C7:5B:A6:5A:6A:9D:D7:0F:CF:6E:B5:42:AD:63:E2:33:B7:68:02:D6`。

`GET /api/health` 不要求令牌。其余 `/api/` 请求由 Nginx 校验 `Authorization: Bearer <API_TOKEN>`，令牌区分大小写；缺失或错误返回 401。真实令牌在服务器配置的 `API_TOKEN` 字段，渲染后的 Nginx map 为 root 所有、0600。应用自身鉴权仍未实现，直接访问回环 Gunicorn 时没有代理层校验。

从仓库根目录验证（Windows）：

```powershell
curl.exe --noproxy "*" --cacert deploy/certs/server.crt https://49.232.195.47/api/health
```

结果应为 `status=ok`、`version=0.1.0+9eb92b9`、`model_loaded=false`。记录调用需配置令牌及证书信任；不能把忽略证书验证作为正式客户端配置。后续绑定域名及受信任证书时，同步更新客户端 API 地址。

腾讯云安全组放行 443 后，公网 HTTPS 已验证通过。入站规则为 `TCP:443`、来源 `0.0.0.0/0`、允许，见 [腾讯云安全组操作说明](https://cloud.tencent.com/document/product/213/112614)。不需要开放 MySQL 3306/33060 或 Gunicorn 8080。

## 服务管理

SSH 登录 gongyi 后：

```bash
sudo systemctl status mobile-cloud-backend mysql nginx
sudo journalctl -u mobile-cloud-backend -n 100 --no-pager
sudo systemctl restart mobile-cloud-backend
sudo nginx -t
curl --cacert /home/gongyi/apps/mobile-cloud-backend/shared/server.crt https://127.0.0.1/api/health
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

后续发布异常时可将 current 原子切回已验证的旧发布并重启后端。本次为首次发布，尚无更早版本可回退；不通过删除数据库回退服务。

## 备份与恢复

`mobile-cloud-backend-backup.timer` 每日备份应用库、保留七天。备份在 `/var/backups/mobile-cloud-backend/`，目录 0700、文件 0600，使用本机 root/socket 认证，不在命令行传密码。实现见 `scripts/backup_database.py`。

```bash
sudo systemctl list-timers mobile-cloud-backend-backup.timer
sudo systemctl start mobile-cloud-backend-backup.service
sudo journalctl -u mobile-cloud-backend-backup.service -n 20 --no-pager
```

已把备份恢复到随机验证库，核对类别和记录后仅删除验证库。正式恢复前需暂停写入、保留当前备份并先做隔离恢复；不能直接清空正式库。备份当前保存在同一服务器，后续需补异机副本。

## 验收

证据见 [server-deployment-20261008.json](../tests/evidence/server-deployment-20261008.json)：75 项通过、3 项 SQLite 下的 MySQL 专用用例跳过，真实 MySQL 用例执行；初始 SQL、HTTPS 201/200/409、四个并发首次上传、实际服务重启后去重、令牌保护及备份恢复通过。临时账号、验证库及正式库测试记录已清理。

公网已实测 HTTP 308、HTTPS 健康 200、无令牌 401 及正确令牌的入库 201、重试 200、冲突 409。公开证书通过固定 SSH 主机指纹渠道取得，TLS 验证未跳过。
