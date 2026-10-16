# 2026-10-16 站点现网复核读数（只读）

出处：站点六页双轨重排的取证前置
（规格 `docs/superpowers/specs/2026-10-16-hub-site-ia-refresh-design.md` §4）。
执行：2026-10-16 13:0x CST，本机（macOS）→ `hub.vlsc.net`（203.25.119.168，与 www 同机）。
约束：全部只读（`cat`/`grep`/`openssl x509`/`systemctl`/`curl`），未改动现网任何文件。

| 项 | 手段 | 读数（2026-10-16） | 页面落点 |
| --- | --- | --- | --- |
| 实例入口 | `nginx -T` | 通配 vhost `~^(?<mrrc_instance>[a-z0-9-]+)\.mrrc\.vlsc\.net$` @ 443/443v6；`proxy_ssl_name $mrrc_tls_name`（逐实例校验名）；`proxy_ssl_verify` 常开 | use / design |
| 门户入口 | `nginx -T` | `portal.mrrc.vlsc.net` @ 443 → `127.0.0.1:8890` | start / maintain |
| 站点入口 | `nginx -T` | `www.vlsc.net` / `vlsc.net` @ 443（+ 443/quic）+ 80；`location ^~ /mrrc_hub/` 已存在 | 全站 |
| 入口证书 | `openssl x509` | `CN=*.mrrc.vlsc.net`，SAN `*.mrrc.vlsc.net`、`mrrc.vlsc.net`；有效期 2026-09-30 → **2026-12-29** | use / trouble |
| 注册表 | `cat /etc/mrrc-hub/instances.tsv` | **14 行**：bg7zhs 18805 / ba4eg 18807 / bg6lh-legacy 18802 / bg1sb 18804 / bg7ifp 18803 / ba4slm 18806 / bg7kxr 18808 / bh2xjd 18809 / bh7hcu 18810 / bi6okx 18811 / bg7zsb-legacy 18812 / bh4gdy 18813 / bg7bvp 18814 / bh4lzh 18815。**当前行只有两列**（标签、端口）；第三列 `tls_name` 可选，缺省 = 自己的入口名 `<标签>.mrrc.vlsc.net`（`gen_hub_routes.py` L129-148） | design |
| 路由自动化 | `systemctl list-timers` | `mrrc-hub-routes.timer` 活，周期 30 s | design / maintain |
| 门户服务 | `systemctl is-active` | `mrrc-portal` active；公开页标题「MRRC Cloud Hub — 呼号自助注册」 | start / maintain |
| frps | `frps --version` | 0.71.0（安装器 pin 对齐值不变） | start / design |
| 信任包 | `grep -c BEGIN` | **134** 个证书块（2026-10-01 旧机为 121） | maintain / design |
| 站点 docroot | `ls /var/www/vlsc.net/mrrc_hub/` | 五页 + css/js；文件日期 2026-10-01 —— **线上确实还是旧版** | 发布验证 |
| 入口延迟（本机 → www/hub） | `curl -6/-4 -w`，各 5 次取中位 | v6：TCP 连接 ~85 ms / TLS 完成 ~165 ms / 全页 ~0.33 s；v4：~89 ms / ~189 ms / ~0.36 s。**v6 与 v4 已接近**（机器在香港，两条路都不再绕远），旧的 118–168 ms 与「v6 快 4 倍」都是迁港前读数 | index 统计带 |
| WS 端点 | `rg server.py` | `/WSradio` `/WSspectrum` `/WSaudioRX` `/WSaudioTX` 固定四路 + `/WSatr1000` 可选 = **4 + 1** | index / design |
| PTT 防线 | `SDD/15` | **Layer 0（未验证机型发射闸门）+ Layer 1–8**（7 条防线 + 4b 仲裁 + 8 CQ 播发） | index |
| 实例侧已发布版本 | `CHANGELOG.md` | **v1.27.0**（2026-10-13）；`feat/ft8` 未发布，写站点时不引用 | maintain / design |

## 与 SDD/12 §12.8 的差异（本次据现场回改页面的点）

1. **注册表第三列**：SDD §12.8 写「三列：`<标签> <回环端口> <上游 TLS 名>`」并记录 `bg1sb` 用
   `radio.vlsc.net`。现场已无第三列 → 语义为「可选、缺省按自己的入口名校验」，`bg1sb` 也不例外。
2. **信任包规模**：121 → 134（实例从 5 个增到 14 个）。
3. **双栈延迟对比**：V0.19/§12.8 的「v6 快约 4×」已不成立（现况近似持平）。

以上三点属「现场优先」；发布完成后回改 `SDD/12 §12.8` 并注明复核日期（计划任务 11 步骤 3）。
