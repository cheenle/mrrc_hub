"""通配 vhost 模板的守卫（2026-10-17）。

`deploy/nginx/` 下的三份配置是现网的唯一真相源：脚本只做安装，不再用 heredoc 在
shell 里拼 nginx 配置（X1 漂移就是那么来的 —— 模板藏在转义过的 heredoc 里，
现网改了没人发现，重跑脚本就把逐实例校验名压平）。这些断言挡住三类回归：

① 逐实例 TLS 校验被压平或关掉（NFR-H021 / 约束 hub-tls-verify-off）；
② 新增的 location 漏抄上游片段 —— 那等于把校验悄悄关掉，而 nginx -t 与页面都正常；
③ 缓存语义被放宽成「什么状态都缓存」或「缓存到永久」——
   一个被缓存的 307 会让已登录用户在一小时内反复被打回登录页。
"""
import re
import unittest
from pathlib import Path

NGINX = Path(__file__).resolve().parent.parent / "deploy" / "nginx"
VHOST = (NGINX / "mrrc-instances.vhost").read_text(encoding="utf-8")
UPSTREAM = (NGINX / "mrrc-hub-upstream.conf").read_text(encoding="utf-8")
CACHE = (NGINX / "mrrc-hub-cache.conf").read_text(encoding="utf-8")
LOGFMT = (NGINX / "mrrc-hub-log.conf").read_text(encoding="utf-8")
DEPLOY = (NGINX.parent / "deploy_hub_routes.sh").read_text(encoding="utf-8")


def _locations() -> dict:
    """location 头 -> 该块正文（花括号配平，模板只有一层嵌套）。"""
    out = {}
    for match in re.finditer(r"^\s*(location [^\n{]+)\{", VHOST, re.M):
        depth, i = 0, match.end() - 1          # 指向 '{'
        while i < len(VHOST):
            if VHOST[i] == "{":
                depth += 1
            elif VHOST[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        out[match.group(1).strip()] = VHOST[match.end() - 1:i + 1]
    return out


class VhostTemplateTests(unittest.TestCase):
    def test_the_template_is_not_empty(self):
        self.assertTrue(_locations(), "解析不出 location —— 模板结构变了，下面的断言会空跑")

    def test_every_location_verifies_the_instance_certificate(self):
        for name, body in _locations().items():
            if name.startswith("location @"):
                continue          # 命名 location 不经上游（实例离线页），另有一条断言盯着它
            self.assertIn("/etc/nginx/snippets/mrrc-hub-upstream.conf;", body,
                          f"{name} 没有 include 上游片段 —— 逐实例 TLS 校验会在这里缺失")

    def test_the_offline_location_is_the_only_named_location(self):
        """除了离线页，不许再出现不经上游片段的 location —— 那等于绕过逐实例校验。

        `location @…` 是唯一合法的例外：它不 proxy_pass，只回一个静态 503。
        """
        named = [n for n in _locations() if n.startswith("location @")]
        self.assertEqual(named, ["location @mrrc_offline"], f"多出来的命名 location：{named}")

    def test_verification_is_never_disabled(self):
        for text, label in ((VHOST, "vhost"), (UPSTREAM, "upstream")):
            self.assertNotIn("proxy_ssl_verify off", text, f"{label} 关掉了证书校验（NFR-H021）")
        self.assertIn("proxy_ssl_name $mrrc_tls_name;", UPSTREAM,
                      "上游校验名必须是逐实例的 $mrrc_tls_name（X1 漂移）")

    def test_only_200_is_stored(self):
        body = [b for name, b in _locations().items() if name.startswith("location ~*")][0]
        self.assertIn("proxy_cache_valid 200 1h;", body,
                      "只允许缓存 200：302/307/401 落盘会把登录页固化")

    def test_cache_headers_are_only_issued_for_200_and_304(self):
        block = re.search(r"map \$status \$mrrc_asset_cc \{(.*?)\n\}", CACHE, re.S)
        self.assertIsNotNone(block, "找不到 map $status $mrrc_asset_cc")
        assert block is not None
        codes = re.findall(r"^\s*(\d{3})\s", block.group(1), re.M)
        self.assertEqual(sorted(codes), ["200", "304"])

    def test_a_hard_refresh_still_reaches_the_instance(self):
        body = [b for name, b in _locations().items() if name.startswith("location ~*")]
        self.assertEqual(len(body), 1, "静态资源 location 应当只有一个")
        self.assertIn("proxy_cache_bypass $mrrc_client_nocache;", body[0])
        self.assertNotIn("immutable", body[0],
                         "?v= 是手工 bump 的：immutable 会把漏 bump 的代价放成一年")

    def test_gzip_covers_javascript_and_css(self):
        self.assertRegex(VHOST, r"gzip_types[^;]*application/javascript[^;]*;")
        self.assertRegex(VHOST, r"gzip_types[^;]*text/css[^;]*;")


class OfflinePageTests(unittest.TestCase):
    """实例离线时访客拿到什么（2026-10-25）。

    原先没有 error_page：隧道一断，访客看到 nginx 的默认 502。而「这台实例离线」
    与「实例自己回了 502」是两件事 —— 后者必须原样透传，前者才该由我们解释。
    实测代价：2026-10-18 单日 10,621 条 502，全部来自一两个挂着死实例的标签页。
    """

    def test_nginx_generated_failures_land_on_the_offline_page(self):
        self.assertIn("error_page 502 504 = @mrrc_offline;", VHOST,
                      "nginx 自己生成的 502/504 必须落到离线页")

    def test_an_instance_own_502_is_not_rewritten(self):
        """`proxy_intercept_errors` 一旦开着，实例返回的 502/504 也会被换掉 —— 那是替实例撒谎。"""
        self.assertNotIn("proxy_intercept_errors on", VHOST)
        self.assertNotIn("proxy_intercept_errors on", UPSTREAM)

    def test_the_offline_page_is_503_with_retry_after_and_not_cached(self):
        body = _locations()["location @mrrc_offline"]
        self.assertIn("internal;", body, "离线页不能被直接访问（只在 error_page 里用）")
        self.assertIn("return 503 ", body, "离线是「临时不可用」，不是「坏网关」")
        self.assertIn("add_header Retry-After 30 always;", body)
        self.assertIn('add_header Cache-Control "no-store" always;', body,
                      "离线页不许被缓存：实例回来后访客不该还看到它")
        self.assertIn("add_header X-MRRC-Instance $host always;", body,
                      "截图里要能看出是哪台实例")

    def test_the_offline_page_never_auto_refreshes(self):
        """自动刷新正是那条风暴的成因（5 路 WebSocket 各自 30 s 一轮）。"""
        body = _locations()["location @mrrc_offline"]
        self.assertNotIn("http-equiv", body.lower())
        self.assertNotIn("setTimeout", body)
        self.assertNotIn("location.reload", body)


class AccessLogFormatTests(unittest.TestCase):
    """hub 的 access log 必须能按实例归属（2026-10-25）。

    一个文件同时装着门户与全部实例。原先没有 `$host`，于是每一条 502 都无法归到
    某个实例上 —— 2026-10-22 那次「入口 502 四天」只能靠 error.log 末段的 `host:`
    反推，而 error.log 只记出错的那部分，正常请求的分布根本无从统计。
    """

    def test_the_log_line_carries_the_host(self):
        line = " ".join(LOGFMT.split())
        self.assertIn("$host", line, "少了 $host，502 就无法归到某个实例")
        self.assertIn("$uri", line)
        self.assertIn("$status", line)

    def test_query_strings_still_never_reach_the_log(self):
        """AD-H07 / NFR-H014：令牌不许进日志。只加 host，不加 args/request_uri。"""
        # 只看**指令本身**：注释里解释「为什么不加 $args」，那是文档不是配置。
        code = "\n".join(line.split("#", 1)[0] if line.lstrip().startswith("#") else line
                          for line in LOGFMT.splitlines())
        self.assertIn("log_format hub_safe", code)
        self.assertNotIn("$args", code)
        self.assertNotIn("$query_string", code)
        self.assertNotIn("$request_uri", code)

    def test_the_deploy_script_installs_the_log_format(self):
        """它原先只活在现网机器的 conf.d 里 —— 又一处「现网有、仓库没有」的漂移。"""
        self.assertIn("nginx/mrrc-hub-log.conf", DEPLOY)
        self.assertIn("/etc/nginx/conf.d/mrrc-hub-log.conf", DEPLOY)


class RouteGeneratorTests(unittest.TestCase):
    """注册表第三列：不写就按**自己的入口名**校验（V0.40）。

    这条守卫来自 2026-10-25 的一次真实部署输出：同一个标签被打了两行**互相矛盾**的提示
    （「按自己的入口名」+「按 radio.vlsc.net」）。第二行是换默认值之前的残留，而照它排查
    会直接走错方向 —— 这正是 X1 漂移（同一件事写两处、漏改一处）的形态。
    """

    def _load(self):
        import importlib.util

        path = NGINX.parent / "gen_hub_routes.py"
        spec = importlib.util.spec_from_file_location("gen_hub_routes_probe", path)
        self.assertIsNotNone(spec, f"加载不了 {path}")
        mod = importlib.util.module_from_spec(spec)   # type: ignore[arg-type]
        spec.loader.exec_module(mod)                  # type: ignore[union-attr,attr-defined]
        return mod

    def test_a_missing_third_column_means_the_instances_own_name(self):
        import tempfile

        mod = self._load()
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "instances.tsv"
            reg.write_text("bg1sb\t18804\nba4eg\t18807\tradio.vlsc.net\n", encoding="utf-8")
            names, notes = mod.load_tls_names(reg)
        self.assertEqual(names["bg1sb"], "bg1sb.mrrc.vlsc.net")
        self.assertEqual(names["ba4eg"], "radio.vlsc.net", "写了第三列就照它校验")
        self.assertTrue(any("按自己的入口名" in n for n in notes), notes)
        for n in notes:
            self.assertNotIn("按 radio.vlsc.net 校验", n,
                            f"自相矛盾的旧提示又回来了：{n}")

    def test_the_default_is_only_used_for_unknown_names(self):
        """`default radio.vlsc.net` 只处理未登记的名字（它们已被 `$mrrc_port = 0` 挡成 404）。"""
        import tempfile

        mod = self._load()
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "instances.tsv"
            reg.write_text("bg1sb\t18804\n", encoding="utf-8")
            names, _notes = mod.load_tls_names(reg)
        self.assertNotIn("radio.vlsc.net", set(names.values()))


if __name__ == "__main__":
    unittest.main()
