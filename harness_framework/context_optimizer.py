"""
上下文架构控制器 - 防止模型注意力衰退
当传给 LLM 的文档内容超过约 100 行时，提取摘要目录后再注入
"""
from typing import Dict, Optional


class ContextOptimizer:
    """上下文压缩优化器"""

    def __init__(self, max_lines: int = 100):
        self.max_lines = max_lines
        self._doc_cache: Dict[str, str] = {}  # doc_id -> original content

    def compress_to_directory(
        self,
        document: str,
        doc_id: str,
        max_lines: int = None,
    ) -> str:
        """
        将超长文档压缩为摘要目录。
        若文档行数未超过阈值，直接返回原文。
        """
        max_lines = max_lines or self.max_lines
        lines = document.split("\n")

        if len(lines) <= max_lines:
            return document

        # 存储原文供按需加载
        self._doc_cache[doc_id] = document

        # 生成简单目录摘要（取前 max_lines 行 + 截断提示）
        directory_lines = []
        directory_lines.append(f"[文档目录摘要 - doc_id: {doc_id}]")
        directory_lines.append(f"原文共 {len(lines)} 行，以下为摘要：")
        directory_lines.append("")

        # 提取标题行（以 # 开头的行）
        headers = [(i, line) for i, line in enumerate(lines) if line.startswith("#")]
        if headers:
            directory_lines.append("章节结构：")
            for i, (line_no, header) in enumerate(headers[:20]):
                directory_lines.append(f"  第 {line_no + 1} 行: {header}")
            directory_lines.append("")

        # 截取前 50 行作为预览
        preview_lines = min(50, max_lines // 2)
        directory_lines.append("文档预览（前 50 行）：")
        directory_lines.extend(lines[:preview_lines])
        directory_lines.append("")
        directory_lines.append(
            f"[内容已截断，共 {len(lines)} 行，当前显示前 {preview_lines} 行]"
        )
        directory_lines.append(
            f"如需查看完整内容，请调用 fetch_section(doc_id='{doc_id}', section_id='full')"
        )

        return "\n".join(directory_lines)

    def fetch_section(self, doc_id: str, section_id: str = "full") -> str:
        """
        按需加载文档原文（不通过 LLM Function Calling 触发，仅内部使用）
        """
        original = self._doc_cache.get(doc_id, "")
        if not original:
            return f"[未找到文档 {doc_id}]"

        if section_id == "full":
            return original

        # 按章节切割（简单实现）
        lines = original.split("\n")
        try:
            section_line = int(section_id)
            return "\n".join(lines[section_line:section_line + 50])
        except ValueError:
            return original

    def compress_mailbox(self, messages: list) -> str:
        """压缩 mailbox 消息列表为摘要（供 team_network 使用）"""
        if not messages:
            return ""
        content_parts = []
        for msg in messages:
            role = getattr(msg, "type", "message")
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            content_parts.append(f"[{role}]: {content[:200]}")
        return "\n".join(content_parts)
