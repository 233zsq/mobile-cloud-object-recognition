# FieldNotes 域名与照片审核入口

2026-10-22 已部署并验收。

| 用途 | 正式地址 |
| --- | --- |
| 物品识别主页 | https://fieldnotes.bigdogaaa.cn |
| iPhone 网页客户端 | https://fieldnotes.bigdogaaa.cn/ios/ |
| 照片审核 | https://fieldnotes.bigdogaaa.cn/review/ |
| OpenCode 客户端 API | https://opencode.bigdogaaa.cn |

两个域名的 HTTP 80 都仅跳转到各自 HTTPS 443，路径和查询参数保留。内部业务服务仍分别监听127.0.0.1:8080与127.0.0.1:8081，没有对公网增加业务端口。旧照片审核8443地址通过308跳转到新域名的 `/review/`。旧物品识别IP入口暂时保留兼容，未更改其数据服务和现有认证。

## 认证与数据

物品识别 `/api/health` 继续允许只读健康检查，其余API沿用原 Bearer 密钥及限流；没有更换API密钥。照片审核沿用原账号、密码、角色、CSRF和数据目录，新增域名白名单、可信代理前缀与 `/review` 范围的 Secure/HttpOnly/SameSite Cookie。切换域名后浏览器需要重新登录，iPhone网页客户端需在新域名下重新填写原有API口令；旧域名的本机浏览器数据未被删除或自动跨站复制。

OpenCode HTTPS 域名的根路径、API、SSE与渠道配置统一要求Basic身份验证，用户名和API密码沿用原值。前端密码哈希文件为 `/etc/nginx/opencode-harmony.htpasswd`，root:www-data 0640；与专用9443代理原密码文件保持一致。更换密码时须同步现有后端、专用代理、此新增前端文件及客户端保存值。80只做HTTPS跳转，不在明文HTTP上提供登录。

OpenCode客户端继续直接填写域名、不增加子路径；浏览器验证身份后根路径404属于预期，因为它是API入口而非OpenCode Web UI。

## 维护材料

- `fieldnotes.nginx.conf`：已部署域名配置，依赖原部署中的 `$mobile_cloud_authorized` Bearer认证映射。配置不包含API密钥或证书私钥，不能在缺少原认证映射的新服务器上单独使用。
- `review-prefix.patch`：服务器审核版本 `bf38f76caf70` 的最小前缀补丁及3项回归测试。当前本地源码树不包含该线上审核模块，补丁只应用于相同基线的审核源码；以后合并或重新发布审核源码时应同步，避免覆盖子路径支持。
- 当前审核版本：`/home/ubuntu/apps/campus-review/releases/bf38f76caf70-fieldnotes-20261022`，`current`软链指向该版本。
- 模型与类别资源复用原审核版本的不可变目录；生产照片、SQLite数据、账号和原有密钥仍位于原数据/配置目录。
- systemd仅新增 `/etc/systemd/system/campus-review.service.d/fieldnotes-prefix.conf`，设置 `REVIEW_URL_PREFIX=/review`。

代理使用末尾带 `/` 的 `proxy_pass` 去除挂载前缀，并明确覆盖X-Forwarded-Prefix；Flask只信任一个前置代理的前缀。依据：[Nginx proxy_pass](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass)、[Flask ProxyFix](https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/)、[Flask应用根路径与Cookie](https://flask.palletsprojects.com/en/stable/config/#APPLICATION_ROOT)。

## 验证范围

- 审核应用151项隔离回归通过，包括新增的真实登录、Cookie范围、CSRF、上传/缩略图权限、邀请链接与退出测试。测试数据库与图片均为临时夹具，已清理。
- 公网Windows/Node系统信任与SAN验证通过；主页、健康检查、API未认证401、审核登录跳转、Cookie、静态资源、CSRF、图片保护、iPhone网页资源、80跳转和旧8443跳转通过。
- 服务器内部使用既有Bearer凭据验证新旧物品识别入口的模型/记录读取；凭据未输出或传出服务器。
- 服务器内部运维会话验证原审核管理员页面与受保护缩略图；不代表已经用人的实际密码完成浏览器登录验收，真实密码流程已由隔离回归覆盖。
- 审核用户、照片和批次行数保留；数据目录不变，模型/类别资源仍指向原文件。
- OpenCode新增域名认证后，原账号的项目/模型/历史读取、脱敏配置和SSE，以及旧9443/IP信任继续通过。
- 没有提交生产审核决定、真实推理、训练或外部AI调用。本轮未重新构建Android客户端或完成手机端验收。

## 证书与回滚

FieldNotes与OpenCode本次证书均为腾讯云免费 DV 证书（TrustAsia），北京时间2027-01-20 12:59:59到期。控制台已开启自动续费，但按腾讯云文档自动续费只负责**重新签发**新证书，不会部署到自建 Nginx（结论与出处见 [证书续期说明](cert-renewal.md)）。2026-12-21 起进入到期前 30 天窗口：在控制台续期并下载新证书，替换 `/etc/fieldnotes-tls/fullchain.pem` 与 `privkey.pem`（目录0700、文件0600，只有root可读），核对证书链与私钥匹配后 `nginx -t` 再平滑 `systemctl reload nginx`；OpenCode 证书还需按其独立9443服务的步骤同步更新。要在窗口内完全免人工，可改用服务器端 certbot 自动续期（需80端口对 Let's Encrypt 可达）。

本次配置、原审核版本信息和SQLite一致性备份位于服务器 `/var/backups/fieldnotes-domain-20261022`（root权限）。回滚前先核对线上是否出现后续修改；恢复本次备份的OpenCode与旧审核Nginx文件，移除新增FieldNotes配置、恢复原 `current` 软链并移除本次前缀drop-in，daemon-reload后只重启审核服务，检查Nginx并平滑HUP。不要自动覆盖生产SQLite备份，以免丢失迁移后新增的照片和审核结果。保留所有业务数据与原代码版本。

原有物品识别后端、OpenCode后端及设置/TLS主进程保持原PID；仅审核服务为加载前缀重启，共享Nginx执行平滑加载。正式证书和密码材料不进入Git，临时上传私钥与候选文件已经清除。

## 2026-10-22 备案完成后的收尾

`bigdogaaa.cn` 已完成 ICP 备案，备案号 `京ICP备2026070624号`。本轮补齐页面与仓库文档：

- 主页侧栏「照片审核」由旧 `https://49.232.195.47:8443/` 改为 `https://fieldnotes.bigdogaaa.cn/review/`；旧 8443 入口仍为 308 跳转，旧 IP 入口保留兼容。
- 主页、`/ios/`、`/review/` 页脚加入备案号并链接 `https://beian.miit.gov.cn/`。`/ios/` 是单页应用，备案号位于「我的」页脚；审核站由 `base.html` 输出到全部页面。
- 展示层按当前发布就地修补，未重新打包、未改 Nginx、未改证书与凭据。改前文件备份在 `/var/backups/fieldnotes-domain-20261022/icp-footer-20261022/`（root，0700）。

| 文件 | 修改前 SHA-256 | 修改后 SHA-256 |
| --- | --- | --- |
| `web/index.html`（当前发布） | `62af010810…` | `e867791628…` |
| `web/assets/css/dashboard.css` | `3c9969bbe8…` | `7a903a8a53…` |
| `/var/www/mobile-cloud-ios/index.html` | `0a4b052f4d…` | `44503debf6…` |
| `/var/www/mobile-cloud-ios/app.css` | `7417685261…` | `4b0c531c5e…` |
| 审核 `templates/base.html` | `6004f1d719…` | `610ccbe0d4…` |

回滚：从备份目录恢复对应文件；审核站恢复后执行 `sudo systemctl restart campus-review`，其余静态文件无需重启。恢复旧侧栏链接时同时还原 `dashboard-index.html`。

验证：域名入口与旧 IP 入口主页 200（无 8443 残留链接、备案号与工信部链接存在）、`/ios/` 200（CSP 不变、资源 200）、`/review/login` 200、`/review/health` 200、`/api/health` 200、80→443 308、8443→`/review/` 308 且最终 200；`nginx -t` 通过，Nginx 配置哈希未变。仓库 `dashboard.css`、`app.css` 与审核 `base.html` 的规范化哈希与线上修补后一致。

仍未做：

- 域名证书续期仍需人工或另配自动化：自动续费只覆盖签发，见 [证书续期说明](cert-renewal.md)。若采用 certbot（80端口 HTTP-01），可让两个域名一次配置后自动 renew+reload。
- Android 1.2 已重新打包并归档到 `ml-deliveries/android-1.2-20261022/`（debug 签名，内置 v2/v3 双模型与20张一致性样例，默认服务地址已改为域名）；未在真机或模拟器上安装验证。
- 仓库改动已 rebase 到 PR #18 之后的 `origin/main` 并合并推送；线上展示层仍是就地修补（早于本次合并），下一次正式打包部署后两者一致。

## 2026-10-22 首页顶部入口调整

按用户要求调整统计页页头：删除「工作空间 / 云端观察档案」文案，改为「用户网页端」按钮，指向 <https://fieldnotes.bigdogaaa.cn/ios/>；侧栏 `<nav>` 的 `aria-label` 同时由「工作空间」改为「页面导航」，页面内不再出现「工作空间」字样。

- 展示层就地修补（未重新打包、未改 Nginx/证书/凭据）：`web/index.html` `e867791628…` → `86832563b7…`；`web/assets/css/dashboard.css` `7a903a8a53…` → `36550fe4d3…`。按钮使用 `.topbar-link`，复用站点强调色，hover 轻微压暗。
- 备份：`/var/backups/fieldnotes-domain-20261022/topbar-20261022/`（首次改页头）与 `/var/backups/fieldnotes-domain-20261022/topbar2-20261022/`（改 aria-label）。
- 回滚：从备份目录恢复 `dashboard-index.html` 与 `dashboard.css` 即回到上一版页头；静态文件由 Flask 直接读取，无需重启服务。
- 验证：主页 200，「工作空间」「云端观察档案」出现 0 次，按钮与 `/ios/` 链接存在，`/review/` 入口与备案号仍在；`/assets/css/dashboard.css` 200 且含 `.topbar-link`；`/api/health` 200。用 CDP 在 360/390/414/430/700/768/1024 宽度实测 `scrollWidth == innerWidth`（无横向溢出），桌面 1440 与手机 390 截图确认按钮、状态徽标与导航换行正常。
- 仓库已同步 `web/index.html` 与 `web/assets/css/dashboard.css`，推送后下一次正式打包即与线上一致。
