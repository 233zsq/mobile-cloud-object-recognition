# 数据库结构与初始化

负责人：数据与云端负责人。已实现MySQL首版四张核心表和记录写入。最低要求MySQL 8.0.16，使用InnoDB、utf8mb4及CHECK约束；云端部署版本还需在实际服务器验证。

- `schema/001_initial.sql`：可在空应用数据库执行的初始建表SQL。
- `seeds/categories.campus-10-v2.json`：模型分支已冻结的类别清单快照。
- `seeds/expanded-cpu-v1.metadata.json`：模型分支现有试验模型元数据快照，供登记和联调使用。

## 表结构

| 表 | 已实现内容 |
| --- | --- |
| `category` | 类别版本与ID组成主键；保存标签键、中文名和类别定义，支持多个映射版本 |
| `model_version` | 版本名、模型/标签SHA-256、类别版本、发布状态、低置信阈值与登记时间 |
| `inference_record` | UUID主键；客户端、来源、模型、原预测、置信度、耗时、UTC采集时间和内容指纹；预留人工标签、纠错时间和修订号 |
| `sample` | 样本路径、哈希、类别、实物/场次、采集信息、划分、审核状态与数据版本；本期只建表，尚无样本导入接口 |

记录通过复合外键确保预测类别与模型类别版本一致；人工标签使用同版本类别。字符串标识区分大小写，上传UUID统一为小写。置信度用DOUBLE保存，采集时间为UTC `DATETIME(3)`，耗时为非负BIGINT。记录只按UUID去重，不把不同UUID的相同照片或内容强行合并。

原预测与人工标签分别保存；上传重试不清空已有纠错。修订号初始为0，纠错字段和数据库约束已预留，PATCH纠错接口尚未实现。

## 初始化顺序

1. 在目标MySQL中创建应用数据库，示例名称为 `object_recognition`：

   ```sql
   CREATE DATABASE IF NOT EXISTS object_recognition
     CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
   ```

2. 在仓库根目录.env填写 `DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER`、`DB_PASSWORD`。初始化账号需要建表权限，程序不会自动创建数据库、账号或重设密码。

3. 安装更新后的后端依赖，在backend目录执行：

   ```powershell
   .venv/Scripts/python.exe -m pip install -r requirements-dev.txt
   .venv/Scripts/python.exe -m flask --app app:create_app db-init
   .venv/Scripts/python.exe -m flask --app app:create_app db-seed
   .venv/Scripts/python.exe -m flask --app app:create_app register-model --metadata ../database/seeds/expanded-cpu-v1.metadata.json
   ```

4. 启动服务并按 [API说明](../docs/api/README.md) 提交记录。

`db-init` 只创建缺失表，保留已有表与数据，不承担旧结构升级。也可在已选定的空数据库内执行 `schema/001_initial.sql`，随后运行类别和模型登记命令；初始SQL只执行一次，不能用重复执行来升级已有数据库。

类别和模型登记可重复执行：内容一致时不新增，已有版本内容不同则报错，不覆盖旧数据。未登记模型的上传返回400。登记试验模型元数据不代表模型文件已领取、推理已启用或正式验收通过；换用正式模型时登记它自己的metadata。

## 结构维护

初始结构定义在 `backend/app/models/__init__.py`，首版SQL由同一SQLAlchemy metadata生成，测试会检查快照一致。当前首版尚未正式部署，更新后可重新生成：

```powershell
# backend目录
.venv/Scripts/python.exe -m flask --app app:create_app db-schema --output ../database/schema/001_initial.sql
```

正式部署后保留001快照，结构变化通过新的版本化升级SQL或统一迁移工具管理；不能依靠create_all修改已有表。

## 验证与资料来源

`backend/scripts/verify_mysql.py` 可使用已有mysqld二进制，在项目tmp目录创建隔离数据目录，仅监听127.0.0.1，执行MySQL及SQLite测试、初始SQL、CLI登记、HTTP入库和重启检查，结束后停止实例并清理临时目录。脚本不读取现有MySQL配置，不安装Windows服务，也不修改现有数据库：

```powershell
# backend目录；根据本机安装位置替换mysqld路径
.venv/Scripts/python.exe scripts/verify_mysql.py --mysqld F:/PROGRAM/mysql-8.0.25-winx64/bin/mysqld.exe --evidence ../tests/evidence/backend-records-mysql-20261008.json
```

普通测试命令为 `.venv/Scripts/python.exe -m pytest -q`；没有 `TEST_MYSQL_ADMIN_URL` 时真实MySQL用例跳过，不能据此宣称MySQL验收完成。隔离验证脚本自动配置该变量。测试只创建并删除自己生成的 `test_recognition_<UUID>` 数据库。

2026-10-08实际结果：MySQL 8.0.25下初始SQL和CLI建表/登记执行通过，合计75项测试通过，3项仅适用MySQL的SQLite参数用例跳过。验证包含四个并发首次提交、HTTP的201/200/409和Flask重启后重复提交只保留一条记录。结果见 `tests/evidence/backend-records-mysql-20261008.json`（仓库根目录）。

种子快照来自本地 `origin/feat/ml-baseline` 的 `78300e4`：类别来源 `shared/categories.json`，模型来源 `models/releases/expanded-cpu-v1/metadata.json`。它们保留原始字节，未将模型分支整体合并。正式类别映射后续变更时需发布新版本并同步各模块。

连接URL通过SQLAlchemy `URL.create` 构造，密码中的特殊字符不用手工转义；连接使用UTC会话，数据库异常返回统一503，健康检查仍可独立使用。相关机制参见[SQLAlchemy连接配置](https://docs.sqlalchemy.org/en/20/core/engines.html#database-urls)和[MySQL约束说明](https://dev.mysql.com/doc/refman/8.0/en/constraint-invalid-data.html)。

数据库只保存元数据、路径和哈希，照片文件另行管理。目标云端的备份、恢复和账号权限配置仍待实施，结果记录在 `deploy/README.md`；真实配置和数据库备份不提交到Git。
