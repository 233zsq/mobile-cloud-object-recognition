# 自适应识别网页（/ios）

手机、平板与 PC 共用的「观察手册」，部署于 https://49.232.195.47/ios/ 。
拍照或选图 → 云端推理 → 本机记录 → 同步与纠错。网页版需要联网，不提供端侧离线推理。

类别与模型契约由 `scripts/sync-configs.py` 按 `shared/config-distribution.json` 的绑定分发；
提交或打包前运行 `python scripts/sync-configs.py check --target web`。策略校验保留原 LF/CRLF 字节，
模型及策略版本导出见[共享配置说明](../../shared/README.md#版本分发与检查)。

2026-10-13：接入与安卓本地 v2 相同的[基础确认规则](../../docs/scope-basic-v1.md)。最高分至少55%、前两名分差至少20个百分点时自动保存，其余先确认、选实际类别或放弃。旧 v1 没有匹配规则，全部转人工确认。高置信范围外误判仍可能通过。

## 代码职责

`app.js` 仅组装依赖与启动页面，使用原生 ES 模块，无构建步骤。`core.js` 保存纯记录、响应校验和范围规则；业务服务通过回调通知视图，不访问 DOM。

| 模块 | 职责 |
| --- | --- |
| `modules/state.js`、`storage.js` | 会话状态及兼容原 localStorage 键的持久化 |
| `modules/api.js`、`images.js` | 请求认证/超时/取消，图片传输副本处理 |
| `modules/models.js` | 类别、契约和模型选择，不静默切换版本 |
| `modules/capture.js`、`records.js` | 识别与待确认流程，单一同步队列及纠错/冲突处理 |
| `modules/events.js` | 用户事件、导航与定时补传触发 |
| `modules/views/` | 页面、识别票据、记录和设置的 DOM 渲染 |

函数通过应用实例共享状态，模块不注册全局业务变量；存储、请求和记录服务可独立测试。样式、页面操作、持久化格式、记录与范围判断口径保留。

## 页面与操作

- 手机使用底部“识别／记录／我的”；平板识别区与结果并排，PC 使用顶部导航和更宽的工作区。
- 图片在本次会话预览，显示处理阶段，可取消和重试；手机成功识别后滚动到结果。
- 记录按模型、修正后的类别、状态及日期筛选，计数与列表使用相同范围；每次渲染24条，按需加载。
- 设置分为云端连接、识别模型、数据与隐私、使用说明。只点“保存口令”才生效，二级页切换保留未保存输入。
- 本机 JSON 备份不含访问口令、设备凭据或照片。云端统计页与本机记录范围不同。

## 数据与同步保证

保留原 localStorage 键 `campus-ios-v1`，升级保留已有记录和设置。
默认保留最近300条；超过时从最旧开始清理已同步、无待传纠错、无冲突的记录。
待同步项不为凑上限而删除，因此总数可以超过300。

所有手动、定时、联网和逐条触发共享同一顺序队列。每次纠错发送不可变快照，
旧响应只确认对应修订，不能确认或覆盖发送期间的新修改。每次响应后及时保存进度。
409保留未同步冲突，暂停自动重试，用户可采用云端修正或以新修订提交本机修正；
404重新上传原记录，不能标记为同步成功。旧版误标“已同步”的冲突在加载时转回待处理。

存储失败显示全局提醒及导出入口，不把仅在内存中的记录显示成可靠保存。
网页关闭后不会继续执行后台补传；再次打开或恢复前台并联网后继续。

## 模型与图片规格

`model-contract.json` 保留默认 v2 的冻结参考。设置口令后，从认证HTTPS接口 `/api/models`
读取已核验的 v2 与 GPU v1，识别页可手动选择；每个版本使用自己的模型SHA-256、标签及阈值。
请求前复查所选规格与就绪状态，请求编号、模型身份、10类Softmax、Top-1、置信度、
阈值标记及耗时有效性通过后才保存结果。不因服务器默认版本或所选版本不可用而静默切换。

图片最长边2048，JPEG质量0.92，透明区域使用128灰底，重编码去除EXIF和位置元数据；
原图最多32MiB，传输副本最多8MiB。实际HEIC解码与相机唤起取决于浏览器，
失败提示转换JPEG／PNG；真实iPhone Safari仍需验收。

## 部署与回退

只公开 `runtime-files.json` 列出的运行文件，包含入口、类别/模型契约和全部原生模块。清单本身、README、测试、package.json/lock、Node 依赖、照片或凭据不进入公开目录。
使用 `python scripts/package-web.py --output tmp/ios-<唯一版本>.tar.gz` 生成完整归档及 SHA-256；打包前检查 HTML/JS 依赖闭包，已有归档拒绝覆盖。
`apply_ios_static.py` 管理Nginx静态路由，`publish_ios.py` 校验归档哈希和成员白名单，
持有ACME共享锁后原子切换 `/var/www/mobile-cloud-ios` 指针。
旧版本保存在 `/var/www/mobile-cloud-ios-releases/`，发布记录位于后端shared目录。

部署工具从完整仓库运行，共用 `deploy/ios_assets.py` 和可信的 `web/ios/runtime-files.json`，不单独复制入口脚本。新页面须整体发布入口及所有模块；发布器创建模块子目录，失败仍回退旧目录指针。

443已切换到8443正在使用的可信IP证书，复用现有自动续期任务，正常访问无需安装自签证书。
`public_tls.py` 只替换已知443证书指令，预检查、备份、Nginx验证、等待就绪；失败恢复旧配置。
Android配置已有system信任，续期不需要更新APK；不关闭证书或主机名校验。

配置变更会影响 `deploy_dashboard.py` 暂存时记录的Nginx哈希，后续激活前重新暂存。
静态页面更新不切换后端、模型、数据库和审核站。

## 本轮验证（2026-10-12）

- 14项网页核心检查通过：记录清理、存储失败、POST／PATCH期间再纠错、共用队列、409／404、
  网络失败重试、筛选以及模型响应与冻结规格。
- 18项部署及ACME检查通过：证书修改边界、Nginx过渡、归档白名单、重复／越界成员、可信连接及续期恢复。
- Chromium检查390×844、820×1180和1440×1000的布局与导航；真实Safari不据此标为通过。
- 公网系统可信HTTPS健康检查成功，campus-evolve-v2就绪；公开交接样例完成真实推理响应检查，
  不调用正式记录写入接口。
- 用户反馈安卓机拍照正常；具体客户端、版本、设备与完整真机链路尚未留证，不替代实拍准确率验收。

纯逻辑复现：`node --test web/ios/tests/core.test.cjs web/ios/tests/services.test.cjs`；模块化后的浏览器检查见 [Web 回归说明](../README.md#回归检查)。
在具备pytest的Python环境运行 `pytest tests/test_ios_deploy.py review/tests/test_acme.py -q`。



## 初版历史验证（2026-10-12，改版前）

静态与部署：
- `/ios` 返回 308 跳到 `/ios/`；`/ios/` 200 且带 CSP、`X-Content-Type-Options`、`Referrer-Policy`、`Cache-Control: no-cache`。
- `app.css` / `app.js` / `categories.json` 的 MIME 正确；`manifest.webmanifest` 由独立 location 声明为
  `application/manifest+json`（nginx 内置 mime.types 不含该后缀）。
- 原有路由未受影响：`/` 统计页 200，未知路径仍 404，`/assets/images/*` 可达；80 端口仍 308 跳 HTTPS。
- 线上文件与仓库逐字节一致（5 个文件 sha256 相同）。

接口（经公网，Linux 侧 `curl --cacert` 校验证书链通过）：
- `GET /api/health` 200，`model_version=campus-evolve-v2`、`model_status=ready`。
- `POST /api/infer`：无口令 401；口令错误 401；`model_version` 不符 409 `MODEL_VERSION_MISMATCH`
  （页面据此刷新版本后重试一次）；`request_id` 非 UUID 400。
- 三张仓库自带样例图（真值 水杯/书本/钥匙）经公网推理的类别与置信度与样例清单一致
  （0.9999 / 1.0000 / 0.9779），响应含页面读取的全部字段，`scores` 10 项且和为 1。
- `POST /api/records` 与 `PATCH /api/records/{id}/label` 的字段集合与页面发送一致：
  用无效模型版本与随机 UUID 触发 `UNKNOWN_MODEL_VERSION`、`RECORD_NOT_FOUND`，未写入任何记录。

浏览器（Chromium，390×844 手机视口）：
- 首屏无横向溢出，类别清单 10 条加载成功，三屏标签切换正常，健康检查失败时按预期显示「无法连接」。
- 传输副本：2400×1600 → 2048×1365 JPEG，符合「最长边 2048、质量 92」规格。
- 识别失败时显示服务端中文错误并给出「再试一次」，不写入记录、不残留忙碌状态。
- 识别成功时依次发出 `POST /api/infer`、`POST /api/records`，票据显示类别/置信度/来源/模型/分阶段耗时/
  总等待/编号，记录标记为已上报；纠错发出 `PATCH /api/records/{id}/label` 并保留原预测。
