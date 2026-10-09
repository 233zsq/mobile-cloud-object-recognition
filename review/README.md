# 照片审核工作台

云端入口：<https://49.232.195.47:8443>。独立使用 `ubuntu`、`campus-review.service` 和回环8081，不改变现有443后端。组员通过一次性邀请建立个人账号；管理员冻结批次、下载训练包并审批候选模型。训练在本机GPU执行，Android后续接入。

当前证书沿用已部署的自签名IP证书；公开证书在 `deploy/certs/server.crt`。浏览器首次使用需由用户核对并安装证书信任，不能关闭客户端证书校验。SHA-256指纹为 `73:7D:DB:0A:98:47:3E:94:E2:08:B1:D6:C7:5B:A6:5A:6A:9D:D7:0F:CF:6E:B5:42:AD:63:E2:33:B7:68:02:D6`，到期北京时间2027-01-06 19:58:23。公网只新增TCP8443入站。

## 使用

首次管理员邀请由服务器生成，24小时有效，一次使用。本地交付文件 `tmp/review-access.txt` 保存链接，不提交Git。管理员设置自己的账号密码后，在首页“邀请组员”生成7天有效的成员邀请。请通过私密渠道分享，服务不发送邮件或消息。

上传单帧JPEG/PNG/WebP，单张≤8MiB、≤1600万像素、短边≥128。填写真实类别、全组统一的实物ID、采集场次；同件实物始终使用同一个ID。预览移除EXIF，训练包保留原始字节和哈希。仅上传训练/开发验证照片；正式独立测试照片由组长另行保管。

所有成员可审核、改类别和分组；拒绝必须说明原因。页面提示相同实物、重复组或感知近重复，需人工确认。过期页面提交返回409。照片冻结后不能改标签，完整事件日志保留在数据库。管理员将所有新通过照片冻结为新批次，下载含 `batch.json`、`samples.csv` 和原照片的ZIP。批次的归档、清单和照片均记录SHA-256。

新模型比较报告从训练PC经SSH导入，网页展示原公开验证与实拍开发验证两个子集。管理员批准/拒绝并记录理由；批准后领取 `/candidates/<模型版本>/approval.json`。批准不替换443服务模型或Android模型。完整训练命令见 [ml-evolution.md](../docs/ml-evolution.md)。

## 开发与验证

Python≥3.12，已在Windows3.13及Ubuntu3.14验证；本模块不安装TensorFlow、NumPy或LiteRT。

```powershell
python -m venv review/.venv
review/.venv/Scripts/python.exe -m pip install -r review/requirements-dev.txt
New-Item -ItemType Directory tmp -Force
review/.venv/Scripts/python.exe -m pytest -q review/tests --basetemp=tmp/review-tests-new
```

`create_app()`要求至少32字符的 `REVIEW_SECRET_KEY`。默认Secure/HttpOnly/SameSite=Lax会话、POST CSRF、密码scrypt、邀请摘要、登录节流、受信任Host、图片解码预算及单进程串行图片解码。生产运行Gunicorn，不使用Flask开发服务器。[Flask部署说明](https://flask.palletsprojects.com/en/stable/deploying/)、[安全配置说明](https://flask.palletsprojects.com/en/stable/web-security/)。

## 运维

源码：`/home/ubuntu/apps/campus-review/releases/<归档摘要>/`；`current`原子指向当前版本。数据：`/home/ubuntu/apps/campus-review/shared/`（0700）；配置：`/home/ubuntu/.config/campus-review/review.env`（0600）。SQLite WAL适合当前小组规模。照片、数据库、邀请及配置都不进入Git。

本地 `python review/deploy/package.py` 只打包审核源代码、测试、类别和基准公开元数据，保存逐文件源码哈希及Git提交/工作区状态。上传归档并校验哈希后解压到新目录，在服务器执行 `python3 <发布目录>/review/deploy/install.py`。安装会运行网页测试、校验Nginx、仅重启自己的服务，并检查原后端配置哈希及健康；更新失败可恢复上一版本指针。安装需要 `ubuntu` 免密sudo；脚本不配置云防火墙。

```bash
sudo systemctl status campus-review
sudo journalctl -u campus-review -n 50 --no-pager
sudo nginx -t
sudo systemctl restart campus-review
python3 /home/ubuntu/apps/campus-review/current/review/deploy/manage.py register-candidate /path/to/comparison.json
```

手工备份先停止 `campus-review` 写入，打包 `shared` 与配置，再启动；归档需保存到受控的组内备份位置。恢复先在独立目录验证数据库、照片和批次哈希，再切换服务目录。管理员邀请过期且尚无管理员时，可通过上述manage入口重新执行 `bootstrap`。现有管理员恢复由服务器负责人处理，不开放公网重置接口。
