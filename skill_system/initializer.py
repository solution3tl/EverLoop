"""
Skill Agent 装配流水线 - 被 main_skill_agent.py 在首次调用时触发
严格按顺序执行五个装配步骤
"""
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from skill_system.main_skill_agent import SkillAgent


async def init_skill_agent(skill_agent: "SkillAgent"):
    """五步装配主入口"""
    await load_skill_folder(skill_agent)
    await setup_language_model(skill_agent)
    await setup_skill_agent_tools(skill_agent)
    await setup_react_agent(skill_agent)


async def load_skill_folder(skill_agent: "SkillAgent"):
    """
    Step 1: 加载技能包文件系统。
    从 skill_agent.skill_package_json 递归还原目录结构到内存。
    建立 file_cache 字典（路径 -> 内容），供 get_file_content 工具秒查。
    """
    package_json = skill_agent.skill_package_json or {}
    skill_agent.virtual_fs = {}
    skill_agent.file_cache = {}

    def _traverse(node: Dict, current_path: str = "/"):
        if isinstance(node, dict):
            for key, value in node.items():
                path = current_path.rstrip("/") + "/" + key
                if isinstance(value, str):
                    # 叶子节点：文件内容
                    skill_agent.virtual_fs[path] = value
                    skill_agent.file_cache[path] = value
                elif isinstance(value, dict):
                    # 目录节点
                    _traverse(value, path)

    _traverse(package_json)


async def setup_language_model(skill_agent: "SkillAgent"):
    """Step 2: 获取推理模型实例"""
    from llm.llm_factory import create_llm
    skill_agent.llm = create_llm()


async def setup_skill_agent_tools(skill_agent: "SkillAgent"):
    """
    Step 3: 动态生成两个工具：
    - list_skill_files: 列出虚拟文件系统中的文件
    - get_file_content: 读取文件内容（超 100 行自动截断）
    """
    from langchain_core.tools import StructuredTool

    def list_skill_files(path: str = "/") -> str:
        """列出技能包中指定路径下的文件列表"""
        path = path.rstrip("/")
        results = []
        for file_path in skill_agent.virtual_fs.keys():
            # 找到当前路径下直接子节点
            if file_path.startswith(path + "/"):
                remainder = file_path[len(path) + 1:]
                if "/" not in remainder:  # 直接子节点（非深层嵌套）
                    results.append(file_path)
        if not results:
            return f"路径 {path} 下没有文件"
        return "\n".join(sorted(results))

    def get_file_content(file_path: str) -> str:
        """
        读取技能包中的文件内容。
        若文件超过 100 行，自动截断并附加提示。
        """
        content = skill_agent.file_cache.get(file_path, "")
        if not content:
            # 尝试模糊匹配
            for path in skill_agent.file_cache:
                if path.endswith(file_path) or file_path in path:
                    content = skill_agent.file_cache[path]
                    break
        if not content:
            return f"文件 {file_path} 不存在"

        lines = content.split("\n")
        if len(lines) <= 100:
            return content
        else:
            truncated = "\n".join(lines[:100])
            return f"{truncated}\n\n[内容已截断，共 {len(lines)} 行，当前显示前 100 行]"

    skill_agent.tools = [
        StructuredTool.from_function(
            func=list_skill_files,
            name="list_skill_files",
            description="列出技能包虚拟文件系统中指定路径下的文件列表",
        ),
        StructuredTool.from_function(
            func=get_file_content,
            name="get_file_content",
            description="读取技能包中的文件内容，超过100行自动截断",
        ),
    ]


async def setup_react_agent(skill_agent: "SkillAgent"):
    """
    Step 4+5: 构建系统提示词 + 创建 ReAct Agent
    """
    system_prompt = await _build_system_prompt(skill_agent)
    skill_agent.system_prompt = system_prompt

    from core.react_agent import create_react_agent
    skill_agent.react_agent = create_react_agent(
        llm=skill_agent.llm,
        tools=skill_agent.tools,
        system_prompt=system_prompt,
    )


async def _build_system_prompt(skill_agent: "SkillAgent") -> str:
    """从 virtual_fs 找 SKILL.md，生成专属人设提示词"""
    skill_md_content = ""
    for path, content in skill_agent.virtual_fs.items():
        if path.endswith("SKILL.md"):
            skill_md_content = content
            break

    if not skill_md_content:
        skill_md_content = f"你是 {skill_agent.skill_name} 专家助手，请根据技能包提供专业帮助。"

    try:
        from prompt.prompt_builder import build_skill_system_prompt
        msg = build_skill_system_prompt(skill_md_content=skill_md_content)
        return msg.content if isinstance(msg.content, str) else str(msg.content)
    except Exception:
        return skill_md_content
