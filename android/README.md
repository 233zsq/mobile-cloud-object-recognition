# Android 客户端

负责人：Android 开发负责人。采用计划书中的 Java、CameraX、tflite/LiteRT 与 Room。

当前只有目录骨架，尚无 Gradle 配置、Manifest、Activity 或可运行 App。在 Android Studio 中把 Java Android 工程生成到本目录，再保留或调整预留的源码目录；建议初始包名为 `com.mobilecloud.recognition`，如修改需同步移动包目录。

| 目录 | 用途 |
| --- | --- |
| `app/src/main/java/com/mobilecloud/recognition/camera/` | 权限、拍照、图片方向 |
| `app/src/main/java/com/mobilecloud/recognition/inference/` | 预处理、模型加载与后台推理 |
| `app/src/main/java/com/mobilecloud/recognition/data/` | Room 实体、本地记录、同步状态 |
| `app/src/main/java/com/mobilecloud/recognition/sync/` | 接口访问、补传、纠错修订号 |
| `app/src/main/java/com/mobilecloud/recognition/ui/` | 拍照、识别结果、记录与纠错界面 |
| `app/src/main/res/` | 布局、字符串与图片资源 |
| `app/src/main/assets/models/` | 正式模型、标签与元数据的打包位置 |

依赖版本在真机验证后登记到 `docs/environment.md`，提交 Gradle Wrapper 与工程配置。开发机路径写入被忽略的 `local.properties`。

手机离线完成识别并保存稳定 UUID，联网后异步上传；纠错保留原预测。模型文件受 `.gitignore` 忽略，领取模型包后复制到 assets，并核对 `docs/model-contract.md` 中的版本、哈希与标签顺序。实际构建和安装命令在工程生成后补充。
