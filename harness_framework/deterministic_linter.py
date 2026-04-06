"""
架构约束执行器 - 用确定性测试工具代替软性 Prompt 规则
对 Agent 输出的结构化内容进行格式和安全性校验
"""
import ast
import json
import re
from typing import List, Optional, Tuple


class DeterministicLinter:
    """确定性格式校验器"""

    # 危险的 Python 调用模式
    DANGEROUS_PATTERNS = [
        r"\bos\.system\s*\(",
        r"\bsubprocess\.",
        r"\beval\s*\(",
        r"\bexec\s*\(",
        r"\b__import__\s*\(",
        r"\bopen\s*\(.*['\"]w['\"]",  # 写文件
    ]

    def validate_output(
        self,
        output: str,
        output_type: str = "plain_text",
        rules: List[str] = None,
    ) -> Tuple[bool, str]:
        """
        校验 Agent 输出。
        返回 (是否合格, 不合格原因)。
        """
        if not output:
            return True, ""

        rules = rules or []

        # 按 output_type 选择校验器
        if output_type == "json":
            ok, reason = self._validate_json(output)
        elif output_type == "python_code":
            ok, reason = self._validate_python(output)
        elif output_type == "markdown":
            ok, reason = self._validate_markdown(output)
        else:
            ok, reason = True, ""  # plain_text 无需格式校验

        if not ok:
            return False, reason

        # 业务规则校验
        for rule in rules:
            ok, reason = self._apply_rule(output, rule)
            if not ok:
                return False, reason

        return True, ""

    def _validate_json(self, text: str) -> Tuple[bool, str]:
        """校验 JSON 格式"""
        # 尝试从 markdown 代码块中提取 JSON
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        json_str = json_match.group(1).strip() if json_match else text.strip()

        try:
            json.loads(json_str)
            return True, ""
        except json.JSONDecodeError as e:
            return False, f"JSON 格式错误：{str(e)}"

    def _validate_python(self, text: str) -> Tuple[bool, str]:
        """校验 Python 代码语法和安全性"""
        # 提取代码块
        code_match = re.search(r"```(?:python)?\s*([\s\S]*?)```", text)
        code = code_match.group(1).strip() if code_match else text.strip()

        # 语法检查
        try:
            ast.parse(code)
        except SyntaxError as e:
            return False, f"Python 语法错误：{str(e)}"

        # 安全扫描
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, code):
                return False, f"代码包含不安全的调用模式：{pattern}"

        return True, ""

    def _validate_markdown(self, text: str) -> Tuple[bool, str]:
        """校验 Markdown 格式"""
        # 检查代码块是否成对闭合
        code_blocks = re.findall(r"```", text)
        if len(code_blocks) % 2 != 0:
            return False, "Markdown 代码块未正确闭合"

        # 检查标题层级（不允许直接从 # 跳到 ###）
        headers = re.findall(r"^(#{1,6})\s", text, re.MULTILINE)
        if headers:
            for i in range(1, len(headers)):
                prev_level = len(headers[i - 1])
                curr_level = len(headers[i])
                if curr_level > prev_level + 1:
                    return False, f"Markdown 标题层级跳跃：{prev_level} -> {curr_level}"

        return True, ""

    def _apply_rule(self, text: str, rule: str) -> Tuple[bool, str]:
        """应用业务规则"""
        if rule == "no_external_urls":
            urls = re.findall(r"https?://(?!localhost|127\.0\.0\.1)[^\s]+", text)
            if urls:
                return False, f"输出包含外部 URL：{urls[:3]}"

        elif rule == "max_length_500":
            if len(text) > 500:
                return False, f"输出长度超过 500 字符（当前 {len(text)}）"

        elif rule == "no_empty_output":
            if not text.strip():
                return False, "输出为空"

        return True, ""

    def auto_disable_if_needed(self, error_rate: float):
        """当校验错误率过高时，自动降级禁用（由外部监控调用）"""
        if error_rate > 0.8:  # 80% 以上都报错说明配置有问题
            try:
                from harness_framework.middleware_plugin_hub import disable_plugin
                disable_plugin("deterministic_linter")
                print("[WARN] DeterministicLinter 错误率过高，已自动禁用")
            except Exception:
                pass
