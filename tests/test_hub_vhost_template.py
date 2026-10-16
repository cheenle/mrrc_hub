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
            self.assertIn("/etc/nginx/snippets/mrrc-hub-upstream.conf;", body,
                          f"{name} 没有 include 上游片段 —— 逐实例 TLS 校验会在这里缺失")

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


if __name__ == "__main__":
    unittest.main()
