# Web 统计页

负责人：数据与云端负责人。首版采用 HTML、CSS 与 JavaScript。

已实现index.html、assets/css/dashboard.css、assets/js/dashboard.js，无前端构建依赖。Flask提供`/`及`/assets/`，Nginx同域转发；不要双击HTML或另开静态服务。

`dashboard.js` 仅组装入口，使用原生 ES 模块。`assets/js/dashboard/` 的 `state.js`、`api.js`、`filters.js`、`view.js` 和 `controller.js` 分别负责页面状态、认证请求、筛选口径、DOM 渲染和刷新/连接编排。口令只在状态对象的内存中，网络层通过回调读取；视图不发送请求，筛选函数不依赖 DOM。新版部署须同时包含该目录中的所有模块。

基础页面展示类别分布、数量趋势、耗时、低置信数量和最近识别记录，每 5 秒请求后端统计及记录接口，并显示刷新时间和失败状态。原预测与人工纠正的统计口径分别标明；日常纠错比例不能充当独立模型准确率。

本地初始化数据库及模型后按backend/README.md启动Flask，浏览器访问http://127.0.0.1:8080/；服务器入口为https://49.232.195.47/。HTTPS 证书与历史验证见 [识别页说明](ios/README.md#部署与回退)，8443 是独立照片审核站点。

输入组内提供的现有访问口令，点击连接。本地API_TOKEN为空时可直接连接；生产使用非空口令。口令只保存在当前页面内存，不进入源码、URL、Cookie或浏览器存储，断开或刷新后清除。页面和静态资源公开，记录及统计通过API认证；通过textContent输出，CSP限制脚本来源。

支持时间、模型、类别、来源筛选及原预测/修正后口径切换，20条一页（API页码从0开始）。时间输入按浏览器本地时区转UTC，结束时间不包含在范围内；日期趋势按UTC分组。耗时不含网络，低置信使用各模型的登记阈值，不混并不同类别版本。

每5秒自动刷新，可暂停或立即刷新；12秒超时，不重复并发刷新。失败保留上次成功数据并显示原因；断开后清除口令和页面数据。API契约见docs/api/README.md，运维见deploy/README.md；真实手机上传到网页统计的系统验收需单独补证据。

## 回归检查

`python scripts/check-project.py --group core` 覆盖不依赖浏览器的记录、请求、存储、筛选和归档检查。页面检查使用开发依赖，不改变生产静态运行方式：

```bash
npm ci --prefix web --ignore-scripts
cd web
npx playwright install chromium
cd ..
python scripts/check-project.py --group web-browser
```

Windows 已有 Edge 时可设置 `$env:PLAYWRIGHT_CHANNEL='msedge'` 后执行浏览器检查，无需另装 Chromium。Node 20+ 用于浏览器测试，可用检查入口的 `--node <解释器路径>` 指定版本。全部页面在回环地址上运行，API 使用模拟数据；覆盖手机、平板、桌面，以及请求中纠错、取消、冲突、备份、分页与断开后的过期响应。真实 iPhone Safari 和服务器验收另行留证。
