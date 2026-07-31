"""Write stage – generates article content from research material."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.config import get_client_for_model
from core.model_config import resolve_models_config_path, select_model_for_role
from services.openai_adapter import generate_text

from ap_utils import (
    MAX_SEARCH_CONTEXT_CHARS,
    article_plain_text,
    build_news_rejection_message,
    detect_forced_news_fillers,
    derive_topic_requirements,
    normalize_article_data,
    parse_article_json,
    read_local_material_context,
    topic_slug,
)
from ap_utils.history import load_office_practice_records
from ap_stages import StageResult

logger = logging.getLogger(__name__)


async def write_stage(
    *,
    topic: str,
    source_path: str | None = None,
    research_data: dict[str, Any] | None = None,
    output_dir: str,
    word_count: int = 1000,
    current_date: str = "",
) -> StageResult:
    """Run the write stage.

    Accepts EITHER:
    - ``research_data`` dict (from search stage output), OR
    - ``source_path`` pointing to a ``.json`` / ``.md`` / ``.txt`` file.

    Returns a ``StageResult`` with the generated ``article.json``.
    """
    search_context = ""

    # -- resolve source --------------------------------------------------------
    if source_path and not research_data:
        src = Path(source_path)
        if not src.exists():
            return StageResult.fail(f"Source file not found: {source_path}")

        if src.suffix.lower() == ".json":
            try:
                research_data = json.loads(src.read_text(encoding="utf-8"))
            except Exception as exc:
                return StageResult.fail(f"Invalid research JSON: {exc}")
        else:
            # .md / .txt – treat as raw material
            try:
                search_context = read_local_material_context([src])
            except Exception as exc:
                return StageResult.fail(f"素材读取失败: {exc}")

    if research_data:
        search_context = str(research_data.get("context") or "").strip()
        if not search_context:
            # reconstruct from sources
            parts = []
            for src in list(research_data.get("sources") or []):
                content = str(src.get("content") or "").strip()
                if content:
                    parts.append(content)
            search_context = "\n---\n".join(parts)
        if not topic:
            topic = str(research_data.get("topic") or "").strip()
        if not current_date:
            current_date = str(research_data.get("current_date") or "").strip()

    if not topic:
        topic = "未命名主题"
    requirements = derive_topic_requirements(topic, current_date=current_date)

    if (
        research_data
        and str(research_data.get("source_type") or "").strip().lower() == "web"
    ):
        news_validation = research_data.get("news_validation")
        if isinstance(news_validation, dict) and news_validation.get("recommend_reject"):
            reject_message = str(news_validation.get("reject_message") or "").strip()
            if not reject_message:
                reject_message = build_news_rejection_message(
                    str(research_data.get("subject") or requirements["subject"] or topic),
                    same_day_only=bool(
                        news_validation.get("same_day_only") or requirements["same_day_only"]
                    ),
                )
            return StageResult.fail(reject_message)

    if not search_context:
        return StageResult.fail("无写作素材输入")

    # -- generate article ------------------------------------------------------
    try:
        article_data = await _generate_article_json(
            topic,
            search_context,
            word_count,
            current_date=current_date,
            office_history_context=_load_office_practice_history_context(current_date=current_date),
        )
    except Exception as exc:
        logger.error("Article generation failed: %s", exc, exc_info=True)
        return StageResult.fail(f"创作失败: {exc}")

    # -- validate --------------------------------------------------------------
    title = str(article_data.get("title") or "").strip()
    sections = list(article_data.get("sections") or [])
    total_chars = sum(
        len(str(s.get("content") or "")) for s in sections
    )
    if not title:
        return StageResult.fail("文章标题为空，生成失败")
    if not sections:
        return StageResult.fail("文章无正文段落，生成失败")
    if total_chars < 1:
        return StageResult.fail(f"文章正文过短 ({total_chars} 字)，生成质量不足")

    if requirements["prefer_news"]:
        combined_text = "\n".join(
            [
                str(article_data.get("title") or ""),
                str(article_data.get("digest") or ""),
                article_plain_text(article_data),
            ]
        )
        filler_hits = detect_forced_news_fillers(combined_text)
        if filler_hits:
            return StageResult.fail(
                "写作结果包含不允许的新闻硬凑表述："
                + "、".join(filler_hits)
                + "。请补充有效新闻素材后再试。"
            )

    # -- save ------------------------------------------------------------------
    effective_topic = str(derive_topic_requirements(topic, current_date=current_date)["subject"] or topic).strip() or topic
    slug = topic_slug(effective_topic)
    out_dir = Path(output_dir) / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "article.json"
    out_path.write_text(
        json.dumps(article_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return StageResult.success(article_data, output_path=str(out_path))


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _load_office_practice_history_context(*, current_date: str = "") -> str:
    """Load recent office-practice column history for topic de-duplication."""
    try:
        records = load_office_practice_records(
            limit=20,
            current_date=current_date,
            days=30,
        )
    except Exception:
        return "最近30天历史留档：读取失败，仍需主动避免与常见办公选题重复。"

    if not records:
        return "最近30天历史留档：暂无。"

    lines = ["最近30天历史留档（写作时必须避开标题、场景、案例、结论和配图主题重复）："]
    for item in records[-20:]:
        parts = [
            f"日期：{item.get('published_date') or item.get('date') or ''}",
            f"标题：{item.get('title') or ''}",
            f"核心工具：{item.get('core_tool') or ''}",
            f"场景：{item.get('office_scenario') or ''}",
            f"读者：{item.get('target_reader') or ''}",
            f"关键词：{item.get('keywords') or ''}",
            f"摘要：{item.get('summary') or ''}",
            f"配图：{item.get('image_theme') or ''}",
        ]
        lines.append("；".join(str(part) for part in parts if str(part).strip()))
    return "\n".join(lines)


async def _generate_article_json(
    topic: str,
    search_context: str,
    word_count: int = 1000,
    *,
    current_date: str = "",
    office_history_context: str = "",
) -> dict[str, Any]:
    requirements = derive_topic_requirements(topic, current_date=current_date)
    subject = str(requirements["subject"] or topic).strip()

    brief_lines = [
        f"- 主题：{subject}",
        "- 面向公众号读者，语言自然、清楚、可直接发布。",
        "- 目标是让读者愿意停留、转发，并在微信信息流里有足够清晰的点击理由。",
        "- 如果用户给了固定标题或标题格式，必须遵守；如果需要自行拟题，标题不要像内部归档名，要有具体对象、数字、动作或冲突。",
    ]
    if requirements["prefer_news"]:
        brief_lines.append("- 按新闻综述写作，先交代事实，再说明背后的变化脉络。")
        brief_lines.append(
            "- 新闻快讯标题优先使用“大数字 + 冲突/反常识/悬念”的短钩子，例如“300亿还不够AI烧”；避免“AI进入收入表”“算力账本重写”这类抽象同质化标题。"
        )
        brief_lines.append(
            "- 严禁出现“没有新官宣但… / 虽然没有官宣… / 值得关注的是行业信号…”这类硬凑表述。"
        )
    if requirements["same_day_only"] and requirements["current_date"]:
        brief_lines.append(
            f"- 只使用 {requirements['current_date']} 当天的信息；素材不足时必须克制，不得硬凑。"
        )
    if requirements["body_only"] or requirements["public_readers"]:
        brief_lines.append(
            "- 只输出正文，不要写导语说明、免责声明、END、图片来源、责编、关注提示等非正文内容。"
        )
    if requirements["forbidden_terms"]:
        brief_lines.append(
            "- 不要出现以下对象或相关内容："
            + "、".join(requirements["forbidden_terms"])
            + "。"
        )

    is_practical_office = bool(requirements.get("practical_office"))
    if is_practical_office:
        brief_lines.extend([
            "- 本文必须是办公实操经验分享，不要写成概念分析、行业评论、新闻解读或工具清单合集。",
            "- 只聚焦一个具体办公场景，并写出可复制的输入材料、提示词、输出格式、复核点和修正步骤。",
            "- 用户没有提供素材时，可以基于公开资料和常见办公流程构造脱敏模拟案例，但不得编造具体工具不存在的功能。",
        ])
    persona = "你是一名长期做办公效率实操经验分享的中文公众号作者，熟悉普通职场人的会议、邮件、表格、PPT、客服和电商运营工作流。"
    office_extra_prompt = ""
    if is_practical_office:
        office_extra_prompt = (
            "\n\n**办公实操栏目硬性要求**：\n"
            "- 这不是行业评论、新闻解读或概念科普；必须写成一篇可长期连载的办公实操经验分享。\n"
            "- 写作前先在脑中完成选题收窄：从素材和历史留档中选择一个具体办公任务，只写一个主场景，不要写成AI办公能力合集。\n"
            "- 如果主题范围很宽，优先从邮件回复效率、客服话术整理、Excel数据说明、会议录音转待办、商品文案批量改写、跨境电商标题优化、PPT汇报结构整理、周报素材归纳、文档摘要与风险点提取、多语言办公翻译与润色中自动选择一个不重复角度。\n"
            "- 必须包含一个完整但脱敏的模拟办公案例：原始材料片段、第一次让AI处理的任务、AI应输出的格式、人工复核点、二次修改方向、最后可用结果。\n"
            "- 案例里的原始材料要具体到可读：例如3-6条会议记录、5行表格数据、3封邮件要点、6条客服问答或一段商品卖点；不得只写‘把资料给AI’。\n"
            "- 必须给出可复制的提示词或任务说明，使用普通人能照着改的中文表达。\n"
            "- 每个关键步骤都要写清楚输入是什么、输出是什么、人要检查什么；不要只写原则。\n"
            "- 文章标题不要带日期、快讯、日报、最新、重磅、炸裂、颠覆、风口、财富密码、躺赚、不学就晚了；标题必须像正常实用文，突出具体办公场景或具体收益。\n"
            "- 语言要像有实际办公经验的人复盘方法，少写‘提升效率、释放生产力、重塑流程’等抽象词。\n"
            "- 结尾强调AI只是先做初稿、整理和改写，人负责确认、选择和沟通。\n"
            "- 配图至少覆盖：办公痛点、AI工作流、案例结果整理；现代、干净、专业，不要科幻机器人、金融暴涨、K线或虚拟货币元素。\n"
            f"\n{office_history_context}\n"
        )

    structure_prompt = (
        persona
        + f"请基于以下素材，围绕主题「{subject}」完成写作。\n\n"
        "写作要求：\n"
        + "\n".join(brief_lines)
        + "\n\n"
        f"素材内容：\n{search_context[:MAX_SEARCH_CONTEXT_CHARS]}\n"
        + office_extra_prompt
        + "\n如通用写作要求与办公实操栏目硬性要求冲突，以办公实操栏目硬性要求为准。\n\n"
        + "**风格要求**：\n"
        + "- 用中文写作，语气清楚、自然、克制，同时要有轻松幽默的故事感，避免生硬报告腔。\n"
        + ("- 不使用营销号式表达，不追求强刺激标题；用具体办公问题、具体材料和具体输出建立阅读价值。\n" if is_practical_office else "- 可以借用国内营销号的注意力机制：大数字、强反差、反常识、悬念问题、具体公司或具体动作；但正文必须用真实事实和经济逻辑兑现，禁止空心标题党。\n")
        + "- 从读者的痛点、好奇心和实际需求切入，用具体场景让读者觉得“这和我有关”。\n"
        + "- 每一段都要传达一个清楚信息点，少写空泛形容，多写事实、判断、案例和影响。\n"
        + "- 可以使用高级中文词汇和生动比喻，但逻辑必须清晰，不要为了煽情牺牲准确性。\n"
        + "- 观点可以有，但必须建立在素材事实之上，不要脱离素材做空泛延展。\n"
        + ("- 标题必须像正常实用文章，直接说明办公场景和收益，例如‘把客服聊天记录整理成一套标准回复’；不得使用日期、快讯、日报、最新、重磅、炸裂、颠覆等词。\n" if is_practical_office else "- 标题必须优先使用素材里的大金额、大数字、强冲突或明确公司动作；当有募资额、订单数、合作意向、增长率等数字时，不要用“进账本 / 排队 / 上桌”等抽象词替代标题钩子。\n")
        + ("- 开头第一屏直接进入真实办公痛点：谁在什么场景卡住、原来怎么做、为什么耗时间；不要写宏观背景。\n" if is_practical_office else "- 开头第一屏要先兑现标题承诺：用 3-5 个短段落写出“为什么这个数字/冲突值得点开”，不要用“过去三天的主线是...”这类报告腔开场。\n")
        + ("- 小标题要像操作步骤或经验节点，例如‘先别让AI直接写结论，先让它拆字段’；不要使用 emoji 堆砌。\n" if is_practical_office else "- 小标题要像信息流里的二级钩子，优先用具体冲突或动作，例如“机器人还没进家门，先冲进交易所”；不要使用 emoji 堆砌。\n")
        + "- 结尾必须是非对话式分析收束，不要向读者提问，不要写“你觉得 / 你所在 / 不妨问一句 / 欢迎留言”。\n\n"
        + "**篇幅要求**：\n"
        f"- 正文总字数要求约 {word_count} 字；不要在正文里暴露字数要求。\n"
        "- 拆分为 4 到 6 个 section，每个 section 有独立小标题。\n"
        "- 每段控制在 2-3 句话（约 80-120 字），然后换段，保持阅读节奏。\n"
        + ("- 结尾收束到方法价值：AI先承担归纳、改写和整理，人负责确认、选择和沟通；不要写趋势预测。\n\n" if is_practical_office else "- 结尾要收束全文，点明这些新闻反映出的变化、影响或趋势，不要写空泛口号。\n\n")
        + "**正文结构建议**：\n"
        + "- 引言：用问题、反差或痛点场景开场，引发读者继续读下去。\n"
        "- 可信依据：如素材中有权威人物、机构、公司或数据，可引用其观点或事实增强可信度；没有依据时不要编造。\n"
        "- 案例支撑：用具体案例说明主题，不要只讲抽象趋势。\n"
        "- 理论解释：用简明语言解释背后的技术、商业或产业逻辑。\n"
        "- 特点总结：总结相关工具、产品、公司或现象的关键特点和差异。\n"
        "- 生产力关系：说明这些变化如何影响效率、成本、组织方式或个人工作流。\n"
        "- 结尾总结：强调全文核心观点，留下清晰印象。\n"
        "- 结尾不要互动提问，不要留言引导；只做克制的分析性收束。\n\n"
        "**排版要求**：\n"
        "- 正文使用 HTML 标签排版，不要用 Markdown。\n"
        "- 面向微信公众号，必须使用内联 style 写出排版，而不是裸 HTML；样式要能通过微信 draft/get 回读保留。\n"
        "- 开头可使用一块导语卡片，例如 <section style=\"margin:4px 0 20px;padding:16px 15px;background:#fff7ed;border-left:4px solid #ff7a1a;border-radius:8px;\">...</section>。\n"
        "- 每个 section 的小标题优先使用带底色和左侧强调线的 <section style=\"margin:30px 0 14px;padding:10px 12px;border-left:4px solid #ff7a1a;background:#fff7ed;border-radius:6px;font-size:17px;line-height:1.55;color:#171717;font-weight:700;letter-spacing:0;\">标题</section>，不要只用裸 <h2>。\n"
        "- 正文段落使用 <p style=\"font-size:15px;line-height:1.9;color:#2f3437;margin:0 0 12px;letter-spacing:0;\">...</p>，短段落优先，不要让公众号里出现大段文字墙。\n"
        "- 关键数字、公司对比、四点清单要做成 callout，例如 <section style=\"margin:18px 0;padding:14px 14px;background:#f8fafc;border:1px solid #e5edf5;border-radius:8px;\">...</section>。\n"
        "- 关键反问或收束句可使用浅橙色强调块，但不要每段都加，避免花。\n"
        '- 在每个 section 末尾加一行 <p style="margin:0 0 18px;"></p> 作为段间留白。\n\n'
        "**配图要求**：\n"
        "- 必须设计 1 张封面图 PROMPT（cover_prompt），用于生成公众号封面：少字、强视觉钩子、手绘插画感。\n"
        "- 在 1-3 个 section 中设计 image_prompt（正文插图），其余为 null；如果用户明确要求更多或至少几张配图，按用户要求补足正文 image_prompt。\n"
        "- cover_prompt 和 image_prompt 只描述给内部 illustrate 阶段的 generate_image 图像意图；禁止要求、暗示或输出 SVG、HTML/CSS、Canvas、矢量图、代码绘图、手工制图方案。\n"
        "- 配图产物必须由 article_publisher 的 illustrate 阶段生成栅格图片，不得绕过内部画图流程使用 SVG 或外部兜底图。\n"
        "- 每个正文 image_prompt 必须服务对应 section 的事实内容，禁止为了凑图生成无关泛图。\n"
        "- 正文插图最终会生成中文信息图，而不是普通插画；image_prompt 只需说明这张图应突出哪些事实、分组、元素或关系。\n"
        "- 不要把 image_prompt 写成 generic illustration、abstract background、people looking at screen 这类无信息描述。\n"
        "- cover_prompt 和 image_prompt 都可以使用中文，优先保留可直接排进图片的关键词和事实。\n\n"
        "**输出格式**：\n"
        "- 返回严格 JSON 格式，仅返回 JSON 对象本身。\n"
        "- 不要 ```json 包裹，不要解释性文字。\n"
        "- JSON 必须使用双引号，结构如下：\n"
        "{\n"
        '  "title": "信息明确、适合公众号且优先使用大金额/大数字/具体公司动作钩子的标题",\n'
        '  "author": "笔名",\n'
        '  "digest": "100-150字摘要，概括今天这篇文章告诉读者什么",\n'
        '  "cover_prompt": "公众号封面应突出的短标题钩子、主视觉元素和高对比色彩方向",\n'
        '  "sections": [\n'
        '    { "content": "<section style=\\"margin:30px 0 14px;padding:10px 12px;border-left:4px solid #ff7a1a;background:#fff7ed;border-radius:6px;font-size:17px;line-height:1.55;color:#171717;font-weight:700;letter-spacing:0;\\">第一部分标题</section><p style=\\"font-size:15px;line-height:1.9;color:#2f3437;margin:0 0 12px;letter-spacing:0;\\">段落一正文...</p>'
        '<p style=\\"margin:0 0 18px;\\"></p>", '
        '"image_prompt": "这一节信息图应突出的事实、节点和关系；不需要时为 null" },\n'
        '    { "content": "<section style=\\"margin:30px 0 14px;padding:10px 12px;border-left:4px solid #ff7a1a;background:#fff7ed;border-radius:6px;font-size:17px;line-height:1.55;color:#171717;font-weight:700;letter-spacing:0;\\">第二部分标题</section><p style=\\"font-size:15px;line-height:1.9;color:#2f3437;margin:0 0 12px;letter-spacing:0;\\">段落一正文...</p>'
        '<p style=\\"margin:0 0 18px;\\"></p>", "image_prompt": null }\n'
        "  ]\n"
        "}"
    )

    model_to_use = select_model_for_role("primary")
    if not model_to_use:
        raise RuntimeError(
            f"No text model configured in {resolve_models_config_path()}"
        )
    async_client = get_client_for_model(model_to_use, is_async=True)
    if async_client is None:
        raise RuntimeError("OpenAI async client is not initialized")

    response_text = await generate_text(
        async_client=async_client,
        model=model_to_use,
        contents=structure_prompt,
        # Some routed openai-chat models reject response_format / json mime type.
        # Ask for JSON in the prompt and parse free-form model text instead.
        config={},
    )
    return normalize_article_data(
        parse_article_json(str(response_text or "")),
        topic,
    )
