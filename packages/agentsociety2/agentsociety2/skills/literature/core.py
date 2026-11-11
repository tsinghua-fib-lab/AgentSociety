"""文献检索核心模块。

通过 MCP 网关检索学术文献，支持可选的中文翻译与多查询拆分。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Literal

from litellm import AllMessageValues
from litellm.router import Router

from agentsociety2.config import Config, build_client_for_role, get_model_name
from agentsociety2.logger import get_logger
from agentsociety2.skills.literature.mcp_client import call_literature_search_mcp

logger = get_logger()

LiteratureSource = Literal["local", "arxiv", "crossref", "openalex"]


def is_chinese_text(text: str) -> bool:
    """
    检测文本是否包含中文字符

    :param text: 待检测的文本

    :returns: 如果包含中文字符返回True，否则返回False
    """
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            return True
    return False


async def _default_acompletion(messages: list[AllMessageValues]):
    dispatcher = build_client_for_role("default")
    return await dispatcher.call(
        model=get_model_name("default"),
        messages=messages,
        stream=False,
    )


async def translate_to_english(text: str, router: Router | None = None) -> str:
    """
    使用LLM将中文文本翻译成英文

    :param text: 待翻译的中文文本
    :param router: 可选 LLM router；为空时使用统一 dispatcher。

    :returns: 翻译后的英文文本
    """
    try:
        prompt = f"""Translate the following Chinese text directly to English. Only output the English translation with shortest words and no additional text.

Chinese text:
{text}

English translation:"""

        messages: list[AllMessageValues] = [{"role": "user", "content": prompt}]

        if router is None:
            response = await _default_acompletion(messages)
        else:
            model_name = router.model_list[0]["model_name"]
            response = await router.acompletion(
                model=model_name,
                messages=messages,
                stream=False,
            )

        translated = response.choices[0].message.content or text
        # 清理可能的额外格式
        translated = translated.strip()
        # 如果LLM返回了markdown格式，尝试提取纯文本
        if translated.startswith("```"):
            lines = translated.split("\n")
            translated = "\n".join(
                [line for line in lines if not line.strip().startswith("```")]
            )

        logger.info(f"翻译完成: '{text}' -> '{translated}'")
        return translated.strip()
    except Exception as e:
        logger.warning(f"翻译失败: {e}，将使用原文进行搜索")
        return text


def _split_query_by_keywords(query: str) -> list[str]:
    """
    基于关键词和连接词进行简单的查询拆分（备用方法）
    尽量保持原查询的短语结构

    :param query: 原始查询文本

    :returns: 拆分后的子主题列表
    """
    # 常见的连接词，按优先级排序
    # " and " 是最常见的，优先处理
    split_keywords = [" and ", " or ", " with ", " versus ", " vs ", " & "]

    # 尝试按连接词拆分
    for keyword in split_keywords:
        if keyword.lower() in query.lower():
            # 使用正则表达式进行不区分大小写的拆分
            pattern = re.compile(re.escape(keyword), re.IGNORECASE)
            parts = pattern.split(query)
            # 清理每个部分
            parts = [p.strip() for p in parts if p.strip()]

            if len(parts) >= 2:
                # 验证每个部分至少 2 个单词
                valid_parts = []
                for part in parts:
                    word_count = len(part.split())
                    if word_count >= 2:
                        valid_parts.append(part)
                    else:
                        logger.debug(
                            f"关键词拆分：部分 '{part}' 太短（只有 {word_count} 个词），跳过"
                        )

                # 如果有效部分少于 2 个，返回原查询
                if len(valid_parts) < 2:
                    logger.info(f"关键词拆分后有效部分少于 2 个，使用原查询: '{query}'")
                    return [query]

                # 对于 "A and B" 模式，直接拆分为 ["A", "B"]
                # 例如："Complexity of social norms and cooperation mechanisms"
                # 拆分为：["Complexity of social norms", "cooperation mechanisms"]
                return valid_parts

    # 如果没有找到连接词，返回原查询
    return [query]


async def split_query_into_subtopics(
    query: str, router: Router | None = None
) -> list[str]:
    """
    使用LLM将复杂查询拆分为多个子主题，尽量按照查询的字面意思拆分，不扩展原意

    :param query: 原始查询文本
    :param router: 可选 LLM router；为空时使用统一 dispatcher。

    :returns: 子主题列表，如果拆分失败或只有一个主题，返回包含原查询的列表
    """
    # 首先尝试基于关键词的简单拆分（快速方法）
    keyword_split = _split_query_by_keywords(query)
    if len(keyword_split) >= 2:
        logger.info(f"使用关键词拆分: '{query}' -> {keyword_split}")
        return keyword_split

    # 检查查询是否太简单（单词数少于5个，可能无法拆分）
    word_count = len(query.split())
    if word_count < 5:
        logger.info(
            f"查询 '{query}' 太简单（{word_count} 个词），跳过拆分，使用单一查询"
        )
        return [query]

    # 如果简单拆分失败，使用LLM拆分
    try:
        prompt = f"""Split the following research query into 2-4 subtopics by directly extracting key phrases from the original query. DO NOT expand or rephrase the meaning. Use the exact words and phrases from the query.

Query: {query}

Rules:
1. Extract key phrases directly from the query, keeping the original wording
2. Split by conjunctions (and, or, with, etc.) or natural phrase boundaries
3. DO NOT add new concepts or expand the meaning
4. Each subtopic MUST be a meaningful phrase with at least 2 words (e.g., "social norms", "cooperation mechanisms")
5. DO NOT create subtopics with only a single word (e.g., "complexity", "mechanisms" alone are NOT valid)
6. If the query is too simple and cannot be split into at least 2 meaningful multi-word phrases, return the original query as a single-item array

Please output ONLY a JSON array of subtopics, with no additional text.

Subtopic array:"""

        messages: list[AllMessageValues] = [{"role": "user", "content": prompt}]

        if router is None:
            response = await _default_acompletion(messages)
        else:
            model_name = router.model_list[0]["model_name"]
            response = await router.acompletion(
                model=model_name,
                messages=messages,
                stream=False,
            )

        result = response.choices[0].message.content or ""
        result = result.strip()

        # 尝试提取JSON数组
        # 移除可能的markdown代码块标记
        if result.startswith("```"):
            lines = result.split("\n")
            result = "\n".join(
                [line for line in lines if not line.strip().startswith("```")]
            )

        # 尝试解析JSON
        try:
            # 如果结果包含JSON，尝试提取
            json_match = re.search(r"\[.*?\]", result, re.DOTALL)
            if json_match:
                subtopics = json.loads(json_match.group())
            else:
                subtopics = json.loads(result)

            # 验证结果
            if isinstance(subtopics, list) and len(subtopics) >= 2:
                # 过滤空字符串和过短的主题
                # 每个子主题必须至少 2 个单词，且至少 3 个字符
                valid_subtopics = []
                for s in subtopics:
                    s = s.strip()
                    if not s:
                        continue
                    # 检查字符数
                    if len(s) < 3:
                        continue
                    # 检查单词数（至少 2 个单词）
                    word_count = len(s.split())
                    if word_count < 2:
                        logger.debug(
                            f"子主题 '{s}' 太短（只有 {word_count} 个词），跳过"
                        )
                        continue
                    valid_subtopics.append(s)

                # 如果有效子主题少于 2 个，说明拆分不合理，返回原查询
                if len(valid_subtopics) < 2:
                    logger.info(f"拆分后的有效子主题少于 2 个，使用原查询: '{query}'")
                    return [query]

                logger.info(f"查询拆分成功: '{query}' -> {valid_subtopics}")
                return valid_subtopics
        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning(f"解析子主题失败: {e}，将使用原查询")

        # 如果拆分失败，返回原查询
        logger.info(f"查询拆分失败或只有一个主题，使用原查询: '{query}'")
        return [query]
    except Exception as e:
        logger.warning(f"拆分查询失败: {e}，将使用原查询进行搜索")
        return [query]


def merge_literature_results(
    results: list[dict[str, Any]], query: str
) -> dict[str, Any] | None:
    """
    合并多个文献搜索结果，去重并合并

    :param results: 多个搜索结果列表
    :param query: 原始查询

    :returns: 合并后的文献搜索结果字典
    """
    if not results:
        return None

    # 使用标题和DOI作为唯一标识符进行去重
    seen_articles: dict[str, dict[str, Any]] = {}
    all_articles = []

    for result in results:
        if not result or "articles" not in result:
            continue

        articles = result.get("articles", [])
        for article in articles:
            # 使用标题作为主要标识符
            title = article.get("title", "").strip().lower()
            doi = article.get("doi", "").strip().lower()

            # 创建唯一键
            if title:
                key = title
            elif doi:
                key = doi
            else:
                # 如果没有标题和DOI，使用其他字段
                key = str(hash(str(article)))

            # 如果文章已存在，合并chunks（保留相似度更高的）
            if key in seen_articles:
                existing_article = seen_articles[key]
                existing_chunks = existing_article.get("chunks", [])
                new_chunks = article.get("chunks", [])

                # 合并chunks，去重并保留相似度更高的
                chunk_map = {}
                for chunk in existing_chunks:
                    chunk_key = chunk.get("content", "")[
                        :100
                    ]  # 使用内容前100字符作为key
                    if chunk_key:
                        chunk_map[chunk_key] = chunk

                for chunk in new_chunks:
                    chunk_key = chunk.get("content", "")[:100]
                    if chunk_key:
                        if chunk_key not in chunk_map:
                            chunk_map[chunk_key] = chunk
                        else:
                            # 保留相似度更高的chunk
                            existing_sim = chunk_map[chunk_key].get("similarity") or 0
                            new_sim = chunk.get("similarity") or 0
                            if new_sim > existing_sim:
                                chunk_map[chunk_key] = chunk

                existing_article["chunks"] = list(chunk_map.values())
                # 更新平均相似度
                if existing_article["chunks"]:
                    avg_sim = sum(
                        c.get("similarity") or 0 for c in existing_article["chunks"]
                    ) / len(existing_article["chunks"])
                    existing_article["avg_similarity"] = avg_sim
            else:
                seen_articles[key] = article.copy()
                all_articles.append(seen_articles[key])

    if not all_articles:
        return None

    # 按平均相似度排序
    all_articles.sort(key=lambda x: x.get("avg_similarity") or 0, reverse=True)

    logger.info(
        f"合并搜索结果：从 {len(results)} 个查询结果中合并得到 {len(all_articles)} 篇唯一文献"
    )

    return {"articles": all_articles, "total": len(all_articles), "query": query}


async def search_literature(
    query: str,
    limit: int = 10,
    router: Router | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    sources: list[LiteratureSource] | None = None,
    similarity_threshold: float | None = None,
    vector_similarity_weight: float | None = None,
    chunk_content_limit: int | None = None,
    relevant_content_limit: int | None = None,
    max_chunks_per_article: int | None = None,
    return_chunks: bool = True,
    enable_multi_query: bool = False,
    mcp_url: str | None = None,
    api_key: str | None = None,
    timeout: int = 120,
) -> dict[str, Any] | None:
    """通过 MCP 网关检索学术文献。

    :param query: 检索词；检测到中文时会先翻译成英文。
    :param limit: 每个子查询返回的文章数上限（默认 10）。
    :param router: 用于翻译与查询拆分的 LLM router。
    :param year_from: 可选的起始发表年份过滤。
    :param year_to: 可选的结束发表年份过滤。
    :param sources: 可选数据源列表（``local`` 、``arxiv`` 、``crossref`` 、``openalex`` ）；默认全部。
    :param similarity_threshold: 本地索引相似度阈值（0.0–1.0）。
    :param vector_similarity_weight: 本地混合检索的向量权重（0.0–1.0）。
    :param chunk_content_limit: 响应中每个 chunk 的最大字符数。
    :param relevant_content_limit: 每篇文章相关内容的最大字符数。
    :param max_chunks_per_article: 每篇文章返回的 chunk 数上限。
    :param return_chunks: 结果中是否包含 chunk 文本。
    :param enable_multi_query: 是否将复杂查询拆分为子主题并合并结果。
    :param mcp_url: MCP 网关 URL；省略时使用 ``Config.get_literature_search_mcp_url()`` 。
    :param api_key: Bearer API key；省略时使用 ``Config.get_literature_search_api_key()`` 。
    :param timeout: MCP 请求超时时间（秒）。
    :returns: 含 ``articles`` 、``total`` 、``query`` 及可选 ``sources`` 的字典；失败时返回 ``None`` 。
    """
    if not mcp_url:
        mcp_url = Config.get_literature_search_mcp_url()
    if not api_key:
        api_key = Config.get_literature_search_api_key()

    # 检测是否为中文，如果是则翻译成英文
    search_query = query
    if is_chinese_text(query):
        logger.info(f"检测到中文输入，正在翻译为英文: '{query}'")
        try:
            search_query = await translate_to_english(query, router)
            logger.info(f"翻译后的查询词: '{search_query}'")
        except Exception as e:
            logger.warning(f"翻译失败，将使用原文进行搜索: {e}")
            search_query = query

    # 多查询模式：将复杂查询拆分为多个子主题
    subtopics = [search_query]  # 默认使用原查询
    if enable_multi_query:
        logger.info(f"启用多查询模式，正在拆分查询: '{search_query}'")
        try:
            subtopics = await split_query_into_subtopics(search_query, router)
            if len(subtopics) > 1:
                logger.info(f"查询已拆分为 {len(subtopics)} 个子主题: {subtopics}")
            else:
                logger.info("查询无需拆分，使用单一查询")
        except Exception as e:
            logger.warning(f"拆分查询失败: {e}，将使用单一查询")
            subtopics = [search_query]

    # 如果只有一个子主题，使用单次查询
    if len(subtopics) == 1:
        return await _search_literature_single(
            query=subtopics[0],
            limit=limit,
            year_from=year_from,
            year_to=year_to,
            sources=sources,
            similarity_threshold=similarity_threshold,
            vector_similarity_weight=vector_similarity_weight,
            chunk_content_limit=chunk_content_limit,
            relevant_content_limit=relevant_content_limit,
            max_chunks_per_article=max_chunks_per_article,
            return_chunks=return_chunks,
            mcp_url=mcp_url,
            api_key=api_key,
            timeout=timeout,
        )

    # 多个子主题：并行搜索并合并结果
    logger.info(f"开始对 {len(subtopics)} 个子主题进行并行搜索...")
    search_tasks = [
        _search_literature_single(
            query=subtopic,
            limit=limit,
            year_from=year_from,
            year_to=year_to,
            sources=sources,
            similarity_threshold=similarity_threshold,
            vector_similarity_weight=vector_similarity_weight,
            chunk_content_limit=chunk_content_limit,
            relevant_content_limit=relevant_content_limit,
            max_chunks_per_article=max_chunks_per_article,
            return_chunks=return_chunks,
            mcp_url=mcp_url,
            api_key=api_key,
            timeout=timeout,
        )
        for subtopic in subtopics
    ]

    results = await asyncio.gather(*search_tasks, return_exceptions=True)

    # 过滤掉异常结果
    valid_results: list[dict[str, Any]] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(f"子主题 '{subtopics[i]}' 搜索失败: {result}")
        elif isinstance(result, dict):
            valid_results.append(result)

    if not valid_results:
        logger.warning("所有子主题搜索都失败")
        return None

    # 合并结果
    return merge_literature_results(valid_results, search_query)


async def _search_literature_single(
    query: str,
    limit: int,
    year_from: int | None,
    year_to: int | None,
    sources: list[LiteratureSource] | None,
    similarity_threshold: float | None,
    vector_similarity_weight: float | None,
    chunk_content_limit: int | None,
    relevant_content_limit: int | None,
    max_chunks_per_article: int | None,
    return_chunks: bool,
    mcp_url: str,
    api_key: str,
    timeout: int,
) -> dict[str, Any] | None:
    """执行单次 MCP 文献检索请求。

    :param query: 发送给网关的英文检索词。
    :param limit: 返回的文章数上限。
    :param year_from: 可选的起始发表年份。
    :param year_to: 可选的结束发表年份。
    :param sources: 可选的数据源名称列表。
    :param similarity_threshold: 本地索引相似度阈值。
    :param vector_similarity_weight: 本地混合检索的向量权重。
    :param chunk_content_limit: 每个 chunk 的最大字符数。
    :param relevant_content_limit: 每篇文章相关内容的最大长度。
    :param max_chunks_per_article: 每篇文章的 chunk 数上限（``return_chunks`` 为假时取 0）。
    :param return_chunks: 是否请求 chunk 数据。
    :param mcp_url: MCP 网关 URL。
    :param api_key: Bearer API key。
    :param timeout: 请求超时时间（秒）。
    :returns: 规范化后的结果字典；超时或出错时返回 ``None`` 。
    """
    payload: dict[str, Any] = {
        "query": query,
        "limit": limit,
    }
    if year_from is not None:
        payload["year_from"] = year_from
    if year_to is not None:
        payload["year_to"] = year_to
    if sources is not None:
        payload["sources"] = sources
    if similarity_threshold is not None:
        payload["similarity_threshold"] = similarity_threshold
    if vector_similarity_weight is not None:
        payload["vector_similarity_weight"] = vector_similarity_weight
    if chunk_content_limit is not None:
        payload["chunk_content_limit"] = chunk_content_limit
    if relevant_content_limit is not None:
        payload["relevant_content_limit"] = relevant_content_limit
    if max_chunks_per_article is not None:
        payload["max_chunks_per_article"] = max_chunks_per_article
    if not return_chunks:
        payload["max_chunks_per_article"] = 0

    logger.debug(f"MCP 搜索参数: {payload}")

    try:
        result = await call_literature_search_mcp(
            mcp_url=mcp_url,
            api_key=api_key,
            arguments=payload,
            timeout=timeout,
        )
        converted_result = _convert_api_response(result, query)
        total_articles = converted_result.get("total", 0)
        logger.info(f"MCP 搜索成功，找到 {total_articles} 篇相关文献")
        return converted_result
    except TimeoutError:
        logger.warning("MCP 文献搜索请求超时")
        return None
    except Exception as e:
        message = str(e).lower()
        if "401" in message or "auth" in message:
            logger.error("MCP 认证失败，请检查 LITERATURE_SEARCH_API_KEY 配置")
        else:
            logger.warning(f"MCP 搜索失败: {e}")
        return None


def _convert_api_response(response: dict[str, Any], query: str) -> dict[str, Any]:
    """将 MCP 检索 JSON（``results`` ）映射为内部的 ``articles`` 结构。

    :param response: 原始 MCP 检索响应。
    :param query: 用户的原始查询字符串。
    :returns: 含 ``articles`` 、``total`` 、``query`` 及可选 ``sources`` 的字典。
    """
    results = response.get("results", [])
    articles = []

    for item in results:
        article = {
            "title": item.get("title", "Unknown Title"),
            "abstract": item.get("abstract", ""),
            "journal": item.get("journal", ""),
            "doi": item.get("doi", ""),
            "url": item.get("url", ""),
            "year": item.get("year"),
            "authors": item.get("authors", []),
            "avg_similarity": item.get("score", 0) or item.get("avg_similarity", 0),
            "source": item.get("source", ""),
            "source_name": item.get("source_name", ""),
        }

        # Preserve common open-access/full-text metadata so the higher-level
        # saving layer can attempt a best-effort PDF download.
        for field in (
            "pdf_url",
            "pdf",
            "full_text_url",
            "fulltext_url",
            "download_url",
            "open_access",
            "best_oa_location",
            "primary_location",
        ):
            if item.get(field) is not None:
                article[field] = item[field]

        # 处理 chunks 信息，统一字段名
        chunks = item.get("chunks", [])
        if chunks:
            converted_chunks = []
            for chunk in chunks:
                converted_chunk = {
                    "content": chunk.get("content", "")
                    or chunk.get("relevant_content", ""),
                    "similarity": chunk.get("similarity_score", 0)
                    or chunk.get("similarity", 0),
                    "chunk_id": chunk.get("chunk_id", ""),
                    "document_id": chunk.get("document_id", ""),
                }
                # 保留其他可能有用的字段
                if chunk.get("vector_similarity"):
                    converted_chunk["vector_similarity"] = chunk["vector_similarity"]
                if chunk.get("term_similarity"):
                    converted_chunk["term_similarity"] = chunk["term_similarity"]
                converted_chunks.append(converted_chunk)
            article["chunks"] = converted_chunks

        articles.append(article)

    return {
        "articles": articles,
        "total": response.get("total", len(articles)),
        "query": query,
        "sources": response.get("sources", {}),
    }
