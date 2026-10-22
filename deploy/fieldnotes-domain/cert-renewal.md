# 腾讯云免费 DV 证书「自动续费」自动化到哪一步

> 2026-10-22 调研。控制台事实：自动续费=开、托管=未托管、已签发。标「文档未明确」者为推断。

## 1. 自动续费对免费 DV 做什么

腾讯云没有「延长同一张证书」的机制，续期一律**重新签发一张新证书**，旧证书不延时（[免费证书续期流程](https://cloud.tencent.com/document/product/400/61353)）。自动续费流程：扣款后**自动生成一张新的「待验证证书（未签发）」**→ 域名验证（DNSPod 托管则自动加 DNS，否则人工，超 3 天审核失败）→ 签发后**仍需手动部署**（[自动续费指引](https://cloud.tencent.com/document/product/400/84479)）。交付是新记录、新 CertificateId（`ApplyCertificate` 的 `OldCertificateId` 仅「建立续费关系」，[API](https://cloud.tencent.com/document/product/400/41678)）。
**文档未明确**：免费证书开自动续费后是否真会自动重申请——国际站同文写「仅限付费证书」，[免费证书概述](https://cloud.tencent.com/document/product/400/89868) 又写「免费证书不支持续费」，口径打架；免费证书确定的手动通道是到期前 30 天的「快速续期」。

## 2. 证书托管管不到自建 Nginx

[托管指引](https://cloud.tencent.com/document/product/400/55818)：托管＝把新证书自动部署到「旧证书关联的**腾讯云产品**」，并明确「用在**非腾讯云云资源**，即使已开启托管，仍需手动安装到您的 Web 服务」。[支持列表](https://cloud.tencent.com/document/product/400/83538) 14 种（CLB、CDN、WAF、COS、Lighthouse 等）**不含 CVM 上的自建 Nginx**。收费：两份文档与[价格总览](https://cloud.tencent.com/document/product/400/7994)均未列该项，**文档未明确**。

## 3. 不托管时的必做项与自动化

下载新证书 ZIP → 替换 `/etc/fieldnotes-tls/fullchain.pem`、`privkey.pem` → `nginx -t && systemctl reload nginx`。官方无面向自建 Nginx 的一键部署；可自动化的官方件只有 API：`ApplyCertificate` + `DownloadCertificate`（[返回 ZIP base64](https://cloud.tencent.com/document/product/400/41670)），再配 cron / systemd timer。腾讯云助手、Terraform 无此能力（文档未提供）。

## 4. 验证方式、续费窗口与额度

[方式对比](https://cloud.tencent.com/document/product/400/4142)：自动 DNS 需域名**托管在 DNSPod 且同账号**；手动 DNS 适用任意服务商；[文件验证](https://cloud.tencent.com/document/product/400/54501) 需已备案、根目录放 `/.well-known/pki-validation/`、**只走标准 80/443**、不跳转、海外 CA 可达。窗口：续费须「有效期 30 天内且未过期」（API 说明），快速续期同为到期前 30 天；自动续费开关文档写「过期前 14 天（含）内无法开启」，两处口径不一致。额度：50 张/账号，到期或吊销后 24h 释放（[FAQ](https://cloud.tencent.com/document/product/400/46849)）；续费次数无单独限制（**文档未明确**）。

## 5. 方案对比（一台 CVM、两站点、已备案）

| | A 现状：腾讯云免费 DV | B：Let's Encrypt + certbot |
| --- | --- | --- |
| 成本 | 0 元 | 0 元 |
| 续期 | 90 天、30 天窗口重签，**部署靠人** | timer 自动 renew 并 reload（[官方指引](https://certbot.eff.org/instructions?ws=nginx&os=snap)） |
| 风险 | 忘部署＝到期即挂；免费证书无工单支持 | 需 80 端口对 LE 可达；限流：同注册域 7 天 50 张、同标识集合 7 天 5 张（[LE 限流](https://letsencrypt.org/docs/rate-limits/)） |
| 多域名 | **不支持多域名** → 两证两人工 | 一证多 SAN 或两证，`certbot --nginx` 自动改配置 |

**所以运维需要做什么**
1. 自动续费只保证新证书被签发，不保证被部署到 CVM——pem 替换与 reload 得有人或脚本负责。
2. 2026-12-21 起进入 30 天窗口：手工走「续期→验证→下载→替换→reload」，或改用 certbot 断掉这个循环。
3. 维持 A 就把「到期前 30 天」写进日历告警，别等 2027-01-20。