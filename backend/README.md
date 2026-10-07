# Flask云端后端

负责人：数据与云端负责人。采用Python Flask、SQLAlchemy、PyMySQL与MySQL，同一应用提供记录管理、统计和单图片推理。云端使用LiteRT Python运行时加载与Android相同的FP32 tflite模型；训练在本地PC完成。

当前只有原初始化留下的Java占位目录，尚无Python应用、依赖清单、接口实现或已部署模型。后续以本目录为根建立Flask工程，以下为建议布局，尚未创建：

| 目录 | 用途 |
| --- | --- |
| `app/__init__.py` | 应用工厂、配置加载、模块注册 |
| `app/api/` | records、labels、stats、categories、infer与health路由 |
| `app/services/` | 校验、UUID去重、修订控制、统计与推理调度 |
| `app/models/` | SQLAlchemy实体、数据库事务和数据访问 |
| `app/inference/` | LiteRT模型加载、预处理、标签与版本校验 |
| `tests/` | 后续接口、事务与模型错误处理测试 |
| `requirements.txt` | 验证后固定的后端运行依赖 |
| `wsgi.py` | 后续Gunicorn启动入口 |

建表与初始化文件统一放在 `database/`；后续若采用迁移工具，在此登记实际迁移入口，避免维护两份不同的数据库结构。

接口以 [API草案](../docs/api/README.md) 为准，模型接入以 [交接约定](../docs/model-contract.md) 为准。数据库密码、API令牌和模型路径由环境配置提供。根目录`.env.example`目前只是草案，尚无程序读取；实现后登记最终加载方式与启动、测试命令。

## 推理与记录分离

- `POST /api/infer`接收单张照片、`request_id`及模型版本，返回预测与阶段耗时，不自动写入采集记录。
- `POST /api/records`保存用户采用的结果，携带UUID和`inference_source`，来源为`device`或`cloud`；重复提交只计一次。
- 同图对比结果单独记录到实验清单，不覆盖原预测，不重复增加采集总数；照片默认处理后释放，样本审核属于后续扩展。

## 运行约束

模型启动时校验并加载，避免每请求重新加载。初始一个Gunicorn worker、受控推理并发，同一运行实例通过互斥或串行调度避免并发调用；配置图片大小、解码检查、请求超时和忙碌状态。健康检查显示模型状态和版本，模型异常应使推理接口明确失败，同时保持记录接口可用。

Linux正式部署采用Gunicorn和Nginx，先测CPU、内存及推理与记录查询并行时的响应，再调整进程、线程和连接池，不直接照搬多worker配置造成模型重复驻留。
