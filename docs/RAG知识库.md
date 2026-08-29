# 知链本地 RAG 知识库

## 当前实现

知链已经把桌面 `resource` 文件夹接入中央调度器。普通问答和 Quiz 都按以下流程执行：

1. `input_router` 把问题拆成 3～6 个检索问题；
2. `rag_node` 查询持久化知识索引；
3. 检索器在完整正文中按关键词、技术代码和中文短语覆盖度排序，默认返回前 8 个证据块；
4. RAG Agent 只能依据证据生成摘要；
5. 问答或 Quiz 生成节点使用证据，并通过 `rag_package` 返回来源、页码、chunk ID、分数和知识库版本。

需要明确：第二版后端当前是可工作的 RAG 链路，但检索器不是 Embedding 向量检索。
它会提取 PDF 全部页面以及 Word、Excel、PPT、Markdown 和文本文件的完整正文，保留 PDF 页码、Excel 工作表和 PPT 页码，再切分为 chunk 进行全文关键词匹配。`RAG_MAX_PDF_PAGES=0` 表示不限制 PDF 页数，不再截断每个文件的末尾内容。
纯图片扫描件若没有可提取文字，会在重建索引时报告 `source_text_empty`；在不启用 OCR 的前提下，这类文件不会被当作可搜索正文。
以后接入 BGE、M3E 或云端 Embedding 时，可以保持 `rag_package` 对前端的字段不变，只替换后端检索实现。

## 文件位置

- 原始资料：`C:\Users\陈子毅\Desktop\resource`
- 持久化文档索引：`backend/agent/rag/storage/local_kb/indexes/docstore.json`
- 检索实现：`backend/agent/rag/simple_retriever.py`
- 中央 RAG 节点：`backend/agent/node/knowledge_generation/rag_node.py`

资料新增、删除或修改后，可以双击项目根目录的 `重建RAG索引.cmd` 重建持久化 chunk 文档索引。

`GET /api/agent/health` 会返回 `rag_source_ready` 与 `rag_index_ready`。
正常 Agent 结果中的 `rag_package` 会包含：

```json
{
  "retrieval_mode": "lexical_character_overlap",
  "evidence": [
    {
      "source_file": "数控机床安全操作题库.xlsx",
      "chunk_id": "数控机床安全操作题库-de2682ac8781",
      "page_label": null,
      "score": 0.2983,
      "text": "……"
    }
  ]
}
```

## 前端兼容

聊天界面的 Agent 活动栏会显示知识库来源、页码和匹配度。Quiz 会把来源、chunk ID 和知识库版本保存到历史会话；能力评分证据也会保留这些字段，因此刷新后不会丢失原始 RAG 依据。
