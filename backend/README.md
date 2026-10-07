# 云端后端

负责人：数据与云端负责人。采用计划书中的 Spring Boot 与 MySQL，单服务实例部署。

当前只有 Maven 风格的源码目录，尚无 `pom.xml`、启动类或接口实现。生成 Spring Boot 工程时以本目录为根，先统一 JDK 和 Spring Boot 版本。建议初始包名为 `com.mobilecloud.recognition`。

| 目录 | 用途 |
| --- | --- |
| `src/main/java/com/mobilecloud/recognition/controller/` | 结果接收、标签修正、分页、统计、类别、健康检查 |
| `src/main/java/com/mobilecloud/recognition/service/` | 校验、UUID 去重、修订控制与统计逻辑 |
| `src/main/java/com/mobilecloud/recognition/repository/` | 数据访问 |
| `src/main/java/com/mobilecloud/recognition/domain/` | 核心实体与领域对象 |
| `src/main/java/com/mobilecloud/recognition/config/` | 数据库、认证与应用配置 |
| `src/main/resources/` | 公开配置与静态资源配置 |
| `src/test/java/com/mobilecloud/recognition/` | 后续必要的后端自动化测试 |

建表与初始化文件统一放在 `database/`；后续若采用迁移工具，在此登记实际迁移入口，避免维护两份不同的数据库结构。

接口草案见 `docs/api/README.md`。数据库密码与 API 令牌通过最终选定的本地配置或环境变量提供，不能写入公开配置。根目录 `.env.example` 目前只用于讨论变量名称，Spring Boot 尚未配置读取它。工程生成后补充启动与验证命令。
