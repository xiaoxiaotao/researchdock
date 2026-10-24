# 来源与接口边界

| 来源 | 获取方式 | 授权 / 限制 |
| --- | --- | --- |
| 手动资料 | JSONL / Markdown / TXT / PDF 导入 | 用户有权提供；PDF 文字层可提取，无 OCR |
| 知识星球 | 官方 zsxq-cli / API，只读采集 | 用户自己登录、自己有权限；遵守速率与内容规则 |
| 有道云笔记 | 星球原帖内的公开分享正文接口 | 不绕过密码、验证码和登录；成功结果为本地快照 |
| 原图与附件 | 来源资源接口与本地缓存 | 不转写音频、不做 OCR；星球 PDF 原件默认只下载 |
| A 股证券库 | 公开证券目录适配 | 通过界面手动同步；匹配结果需要消歧 |
| 港股证券库 | HKEX 官方公开清单 | 仅港元股票主柜台；未接入港股财务 |
| A 股财务 | 新浪公开财报接口，腾讯代码校验 | 非付费授权行情服务；可能限流或改版，保留来源 |
| 海外机构 | 部分公开索引、官方 PDF URL、用户导入 JSON / PDF | 并非完整授权研报 API，无付费墙绕过 |
| DeepSeek | 可选 Chat Completions 调用 | 用户自行提供 Key 并承担费用；相关正文离开本机 |

## 代表性应用接口

- `GET /documents/{document_id}/export.pdf?revision=1`：固定修订 PDF 下载。
- `GET /api/v1/securities`：本地证券查询。
- `POST /api/v1/securities/sync`、`.../sync-hk`：证券目录同步。
- `GET /api/v1/stocks/{stock_id}/financials`、同路径 POST：读取 / 刷新 A 股财务缓存。
- `GET /api/v1/international/providers`：机构适配状态。
- `POST /api/v1/international/{provider_id}/reports`：`{"reports":[...]}` 导入用户提供记录。

机构 records 字段包括 `title`、官方 `url`、可选 `published_at`、`external_id`、`coverage` 与 `body`。coverage 为 `public_index`、`supplied_metadata` 或 `supplied_text`；只有 `supplied_text` 允许正文，且必须非空。详细校验以 `app/international_sources.py` 为准。非全文不会伪装成已下载报告。

这些接口面向本机使用，不带多用户鉴权。新增来源应复用规范化导入流程，避免直接修改原文 / 索引，明确区分元信息、全文与推断。
