# Flask云端后端

负责人：数据与云端负责人。采用Python Flask、SQLAlchemy、PyMySQL与MySQL，同一应用提供记录管理、统计和单图片推理。云端使用LiteRT Python运行时加载与Android相同的FP32 tflite模型；训练在本地PC完成。

当前已建立可启动的Flask基础工程，包含应用工厂、环境配置、UTC控制台日志、请求编号、统一JSON错误及 `GET /api/health`。服务无需数据库或模型即可启动。记录、统计、纠错、认证及云端推理业务仍待实现，尚未连接MySQL或部署正式模型。

| 目录 | 用途 |
| --- | --- |
| `app/__init__.py` | 应用工厂、配置加载、模块注册 |
| `app/config.py` | 默认值、根目录.env及进程环境配置，启动时检查非法配置 |
| `app/observability.py` | UTC控制台日志、服务端生成的请求编号及响应头 |
| `app/errors.py` | HTTP错误、业务错误和未预期异常的JSON响应 |
| `app/api/` | 已实现health，后续加入records、stats、categories和infer |
| `app/services/` | 预留校验、UUID去重、修订控制、统计与推理调度 |
| `app/models/` | 预留SQLAlchemy实体、数据库事务和数据访问 |
| `app/inference/` | 预留LiteRT模型加载、预处理、标签与版本校验 |
| `tests/` | 应用、配置、错误处理、请求大小和日志验证 |
| `requirements.in`、`requirements.txt` | 运行依赖范围及固定版本清单 |
| `requirements-dev.in`、`requirements-dev.txt` | 测试依赖范围及固定版本清单 |
| `app/__main__.py` | 本地开发启动入口 |
| `wsgi.py` | Linux Gunicorn启动入口 |

原 `src/main/java/` 等Java占位目录保留，Python程序不读取它们。数据库与推理依赖在对应模块接入时再安装。

## 本地启动（Windows PowerShell）

要求Python 3.11+，当前验证使用Python 3.11.4。训练和后端使用独立虚拟环境。从仓库根目录执行：

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
# 保留已有本地配置，只在.env不存在时复制示例。
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
Set-Location backend
.venv/Scripts/python.exe -m app
```

默认监听 `http://127.0.0.1:8080`，开发服务器前台运行，Ctrl+C停止。另一终端检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/api/health
```

已有 `backend/.venv` 时直接使用其中的Python，不必重新创建环境。只安装运行依赖时将安装命令替换为 `-r backend/requirements.txt`。

`python -m app` 按配置使用 `SERVER_HOST`、`SERVER_PORT` 和 `APP_DEBUG`。也可在backend目录运行 `.venv/Scripts/python.exe -m flask --app app:create_app run --host 127.0.0.1 --port 8080`；Flask CLI的监听地址、端口及debug由CLI参数控制，不会自动采用本项目的 `SERVER_*` 设置。

## 配置加载

`app/config.py` 以文件位置定位仓库根目录 `.env`，不依赖当前工作目录。优先级：程序默认值 < 根目录 `.env` < 进程环境变量 < 应用工厂的测试覆盖配置。程序读取.env但不修改进程环境；值不做 `${变量}` 插值，密码中出现该文本时按原样读取。

| 配置 | 默认值 | 当前用途 |
| --- | --- | --- |
| `APP_VERSION` | `0.1.0` | 健康检查返回的服务版本，区别于模型版本 |
| `APP_DEBUG` | `false` | 本地开发入口的debug开关，支持true/false/1/0 |
| `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR/CRITICAL |
| `SERVER_HOST`、`SERVER_PORT` | `127.0.0.1`、`8080` | 本地开发监听设置；真机局域网联调可将HOST设为0.0.0.0 |
| `MAX_CONTENT_LENGTH` | `10485760` | 请求体限制，字节；不是图片解码或像素限制 |
| `DB_HOST/PORT/NAME/USER/PASSWORD` | 见根目录.env.example | 已读取并预留，尚未建立数据库连接 |
| `API_TOKEN` | 空 | 已读取并预留，尚未实现认证 |
| `MODEL_DIR` | 空 | 已读取并预留；相对路径以仓库根目录解析，尚未加载模型 |

`API_BASE_URL` 供客户端配置参考，后端不使用。根目录 `.env.example` 无真实凭据，真实.env受Git忽略。非法端口、debug、日志级别和请求大小在启动时报告错误。

## 健康检查与统一错误

`GET /api/health` 返回200，兼容Android现有 `status`、`version` 和 `model_loaded` 字段；`?client=android` 可传入但当前不参与处理：

```json
{
  "status": "ok",
  "version": "0.1.0",
  "model_loaded": false,
  "model_version": null,
  "model_status": "not_initialized"
}
```

这是服务存活检查，不代表数据库或推理已就绪。当前模型状态始终未初始化，配置MODEL_DIR不会改变该状态。尚未实现的业务路径返回404，不返回伪成功。

所有响应附带服务端生成的 `X-Request-ID`。统一错误示例：

```json
{
  "error": {"code": "NOT_FOUND", "message": "..."},
  "request_id": "服务端生成的UUID"
}
```

404/405/413等HTTP错误保留原状态码与Allow/Retry-After等头。未预期异常返回通用500错误，详情写服务端日志。业务模块可抛出 `ApiError(code, message, status_code)`，message应为可公开文本。控制台请求日志记录编号、方法、路径、状态码和耗时，不记录请求头、请求体或查询字符串；`elapsed_ms` 是本次服务端请求处理耗时，不能作为模型纯推理时间。

## 测试与依赖更新

在backend目录执行：

```powershell
.venv/Scripts/python.exe -m pytest -q
```

依赖固定清单通过uv生成，跨平台保留环境标记；Gunicorn仅在非Windows平台安装。需要更新时，从仓库根目录依次执行：

```powershell
uv pip compile backend/requirements.in --universal --python-version 3.11 --output-file backend/requirements.txt
uv pip compile backend/requirements-dev.in --universal --python-version 3.11 --output-file backend/requirements-dev.txt
```

更新后重新安装并验证，避免手工改固定清单造成依赖不一致。

2026-10-08验证：Windows Python 3.11.4下19项测试通过；实际启动 `python -m app`，通过HTTP检查health=200、未实现业务路径=404、错误方法=405及请求编号；`wsgi:app` 可导入且健康检查通过。验证服务已停止。结果见 `tests/evidence/backend-scaffold-20261008.json`（仓库根目录）。

## Linux WSGI启动入口

在backend目录安装运行依赖后：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/gunicorn --workers 1 --threads 2 --bind 127.0.0.1:8080 wsgi:app
```

Gunicorn监听地址由命令行决定；该命令是服务启动示例，Nginx、HTTPS和systemd尚未配置。当前仅在Windows验证Flask工程，Linux/Gunicorn部署需后续实测。应用工厂和错误处理参考[Flask官方文档](https://flask.palletsprojects.com/en/stable/tutorial/factory/)与[HTTP错误处理说明](https://flask.palletsprojects.com/en/stable/errorhandling/)。

建表与初始化文件统一放在 `database/`；后续若采用迁移工具，在此登记实际迁移入口，避免维护两份不同的数据库结构。

接口以 [API草案](../docs/api/README.md) 为准，模型接入以 [交接约定](../docs/model-contract.md) 为准。后续业务接口仍需与Android冻结；本期已实现范围为工程基础和健康检查。

## 推理与记录分离

- `POST /api/infer`接收单张照片、`request_id`及模型版本，返回预测与阶段耗时，不自动写入采集记录。
- `POST /api/records`保存用户采用的结果，携带UUID和`inference_source`，来源为`device`或`cloud`；重复提交只计一次。
- 同图对比结果单独记录到实验清单，不覆盖原预测，不重复增加采集总数；照片默认处理后释放，样本审核属于后续扩展。

## 运行约束

模型启动时校验并加载，避免每请求重新加载。初始一个Gunicorn worker、受控推理并发，同一运行实例通过互斥或串行调度避免并发调用；配置图片大小、解码检查、请求超时和忙碌状态。健康检查显示模型状态和版本，模型异常应使推理接口明确失败，同时保持记录接口可用。

Linux正式部署采用Gunicorn和Nginx，先测CPU、内存及推理与记录查询并行时的响应，再调整进程、线程和连接池，不直接照搬多worker配置造成模型重复驻留。
