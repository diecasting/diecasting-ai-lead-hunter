# Phase 3 — Customer Acquisition Engine 设计方案（预研分析）

> 本文档仅做架构分析与设计规划，未修改任何代码。
> 分析基础：当前仓库状态（Phase 1–2.5 已完成，commit `7649fe5`），共 7 张表、25 个 API 端点、229 个测试。

---

## 1. 当前架构分析

### 1.1 系统链路（已贯通）
```
关键词库 → Google SERP(Playwright) → 过滤 → 建 Lead+CrawlTask
   → Playwright 爬官网 → 抽邮箱/PDF → 规则打分+LLM摘要
   → 分级(HIGH/MEDIUM/LOW) → 生成邮件 → SMTP发送(dry-run可选) → 状态机 → Followup
```

### 1.2 架构优点（Phase 3 可复用）
- **IO 边界全注入**：搜索 provider、爬虫 fetcher、PDF fetcher/text_extractor、SMTP dry-run 均可注入 → 新渠道/数据源可完全离线测试。
- **搜索 provider 抽象已就绪**：`BaseSearchProvider` + `SearchService(provider=...)` 注入点已存在，新增 Bing/SerpAPI/CSE 零成本。
- **状态机 + append-only 历史表**（`ai_analysis`）已具备审计能力。
- **规则打分引擎**无需 API key，确定性、便宜、适合大规模筛选。
- **229 测试**提供重构安全网。

### 1.3 当前主要缺陷（Phase 3 开工前建议先修）
| # | 严重度 | 位置 | 问题 |
|---|---|---|---|
| 1 | 高 | `crawler/runner.py` | 访问 `outcome.text`，但 `CrawlResult` 字段是 `text_content` → 批量爬取必然 AttributeError 崩溃 |
| 2 | 高 | `api/search.py` | 用 `HTTPException` 但未 import → 搜索失败抛 NameError |
| 3 | 高 | `routers/leads.py` | `/leads/{lead_id}` 声明早于 `/leads/high-priority` → 后者永远 422 |
| 4 | 中 | `routers/leads.py` | `pages_crawled = getattr(result,"pages_found",0)` 把 URL 列表赋给整数字段 |
| 5 | 中 | `routers/leads.py` | `crawl_status="completed"` 与系统其他处 `"success"` 不一致 |
| 6 | 中 | `outreach/followup.py` | naive `utcnow()` 与 aware datetime 混用，PG 下比较可能报错 |
| 7 | 中 | `scheduler.py` | 从不调用 `get_due_followups()` → 跟进邮件永久滞留 draft |
| 8 | 中 | `routers/leads.py` | `PDFExtractor()` 无 fetcher 必抛异常被吞 → PDF 功能形同虚设 |

---

## 2. 数据库需要新增哪些表

Phase 3 的核心主题是**多渠道获客闭环 + 联系人精细化 + 送达追踪 + 合规**。建议新增/扩展如下：

### 2.1 新增表

**`contacts`（联系人实体化）**
- 目的：当前联系人扁平挂在 lead 上（一个 email + 一个 role 字符串），无法支撑多联系人、多角色、姓名/职位/LinkedIn。
- 字段：`id`, `lead_id`(FK), `name`, `role`(职位), `email`, `phone`, `linkedin_url`, `channel`(email/linkedin/whatsapp), `is_primary`(Bool), `verified`(Bool), `created_at`

**`lead_sources`（来源渠道记录）**
- 目的：当前 `company_leads.source` 只是字符串（如 `google_search`），无法追踪具体搜索词、国家、渠道类型、获客成本。
- 字段：`id`, `lead_id`(FK), `channel`(google/bing/serpapi/cse/linkedin/manual/import), `keyword`, `country`, `source_url`(SERP 链接), `rank`(搜索排名), `cost`(Float, 可选), `captured_at`

**`email_verifications`（邮箱验证）**
- 目的：发送前验证邮箱有效性，降低 bounce rate，保护域名信誉。
- 字段：`id`, `lead_id`(FK, 可空), `contact_id`(FK, 可空), `email`, `status`(valid/invalid/unknown/risky), `score`(0-100), `details`(JSON: mx/smtp_check/disposable/role), `verified_at`

**`email_tracking`（打开/点击追踪）**
- 目的：当前只能记 `sent` 事件，无法度量打开率/点击率。
- 字段：`id`, `message_id`(FK), `event_type`(open/click), `tracking_token`, `user_agent`, `ip`, `clicked_url`, `created_at`

**`reply_inbox`（回复内容存储）**
- 目的：`outreach_events` 只记类型不存正文，无法做回复意图分类。
- 字段：`id`, `lead_id`(FK), `message_id`(FK, 可空), `from_email`, `subject`, `body`(Text), `received_at`, `intent`(positive/negative/objection/question/unknown), `classified`(Bool)

**`unsubscribes`（合规退订）**
- 目的：CAN-SPAM / GDPR 合规硬需求。
- 字段：`id`, `email`, `lead_id`(FK, 可空), `reason`(可选), `token`, `created_at`

### 2.2 扩展现有表
- `company_leads`：加 `do_not_contact`(Bool), `bounce_count`(Int), `channel`(默认 email), `employee_count`/`contact_phone` 已有但未写入 → 在爬虫/导入时填充。
- `outreach_messages`：加 `tracking_token`(用于打开/点击像素), `open_count`(Int), `click_count`(Int), `html_body`(Text, 支持 HTML 邮件)。
- `outreach_events`：已预留 `opened/replied/bounced`，补写入逻辑。
- `crawl_tasks`：加 `channel`(source 来源), `proxy`(可选)。

### 2.3 迁移计划
新增 `0005_phase3_acquisition.py`，包含上述全部 DDL。建议同时修掉 #4/#5 的 `crawl_status` 不一致（统一为 `success`）。

---

## 3. Lead Source Integration 设计方案

### 3.1 目标
支持多渠道统一接入：Google SERP、Bing、SerpAPI、Google CSE、LinkedIn、手动导入、CSV 批量导入。

### 3.2 Provider 接口扩展
现有 `BaseSearchProvider.search(keyword, country, max_results) -> List[SearchResult]` 已可用。Phase 3 扩展：
- 新增 `channel` 属性（每个 provider 声明自己的渠道名）。
- `SearchResult` 增加 `rank` 字段（已部分存在 search_results 表有 rank）。
- 新增 `BaseImportSource` 接口处理非搜索来源（LinkedIn scraper、CSV）：

```python
class BaseLeadSource(ABC):
    channel: str
    def fetch(self, query, **kwargs) -> List[RawLead]
    # RawLead: {name, website, country, industry, source_url, raw_text}
```

### 3.3 渠道实现清单
| 渠道 | 实现方式 | 备注 |
|---|---|---|
| Google SERP | 现有 Playwright（保留兜底） | 规模化时切 SerpAPI/CSE |
| Bing | 新 provider，Playwright 或 Bing API | 复用 parse 逻辑 |
| SerpAPI | 新 provider，HTTP API | 最稳，付费，优先推荐规模化 |
| Google CSE | 新 provider，官方 API | 免费额度有限 |
| LinkedIn | 新 scraper（需登录态/代理） | 高风险，建议用 PhantomBuster 等第三方 |
| CSV 导入 | `POST /leads/import` 端点 | 解析 CSV → 批量建 lead |
| 手动 | 现有 `POST /leads` | 已支持 |

### 3.4 落库与去重
- `lead_sources` 记录每次获取的来源细节。
- 去重键仍是 `website`（domain 级归一化：strip `www.`、trailing slash）。
- 同一 lead 多来源 → 在 `lead_sources` 追加记录，不重复建 lead。

### 3.5 新增 API
- `POST /sources/search` — 指定 channel + keyword 搜索
- `POST /leads/import` — CSV/JSON 批量导入
- `GET /crm/sources` — 按渠道统计获客数

---

## 4. Google Search Crawler 设计方案

### 4.1 现状问题
- 裸爬 Google SERP：无代理、无 UA 轮换、无验证码检测、无速率限制。
- 正则解析 HTML，class 名变更即失效。
- `data/keywords.txt` 实际不存在，跑的是内置 12 条。

### 4.2 Phase 3 方案（两条路线并行）
**路线 A — 官方 API 优先（推荐规模化）**
- 新增 `SerpApiProvider` / `GoogleCSEProvider`，通过 HTTP API 取结构化 JSON。
- 好处：稳定、可解析、不被封、速率可控。
- 成本：SerpAPI ~$0.01/次，每日 1000 lead ≈ $10。

**路线 B — Playwright 增强（保留兜底）**
- 增加：随机 User-Agent 池、请求间隔随机化（2-5s）、代理支持（通过 `crawler_proxy` 配置）、验证码检测（检测 `"unusual traffic"` / `"CAPTCHA"` 文本 → 暂停并告警）。
- 解析层：引入 `beautifulsoup4` / `lxml` 替代纯正则（当前无此依赖），提升健壮性。

### 4.3 关键词管理
- 创建 `data/keywords.txt`（当前缺失），按行业分组的多语言词库：
  - 英文：`aluminum die casting`, `magnesium die casting`, `CNC machining`, `die casting mold`, `EV motor housing`...
  - 德语：`Aluminium Druckguss`, `Druckguss Hersteller`...
  - 中文：`压铸厂`, `铝合金压铸`, `镁合金压铸`...
- 支持 `country` 维度选择语言。

### 4.4 速率与配额
- `search_rate_limit` 配置：每分钟最大查询数。
- `daily_search_quota`：防止超预算。

---

## 5. Website Intelligence Crawler 设计方案

### 5.1 现状瓶颈
- **每页都 launch 新 Chromium 实例** → 单站 12+ 页面 = 启动十几次浏览器，单站数十秒。
- 完全串行，无并发。
- `PDFExtractor()` 无 fetcher 导致 PDF 抽取形同虚设（#8）。
- `crawl_status` 值不一致（#5）。

### 5.2 Phase 3 优化方案

**A. 浏览器复用**
- 单 site 内复用同一个 `BrowserContext`（launch 一次，多 page 复用）。
- 对纯静态站（无 JS 依赖）改用 `httpx` + `beautifulsoup4` 轻量 HTTP 回退（新增 `HttpFetcher` 实现 `Fetcher` 协议）。
- `Fetcher` 协议：
```python
class Fetcher(Protocol):
    def fetch(self, url, *, timeout_ms) -> str: ...
```

**B. 并发爬取**
- 引入 `asyncio` + `asyncio.gather` 或线程池，单 site 内多页并发（限 `max_concurrency=4`）。
- 尊重 `Crawl-delay`（当前 robots 解析不支持，需升级 `parse_robots` 支持 Allow/通配符/Crawl-delay）。

**C. 智能页面发现增强**
- 从 sitemap.xml **真正解析** URL 列表（当前只是把 `/sitemap.xml` 当候选页抓一次，不解析内容）。
- 增加 `detect_sitemap()` → 解析 `<loc>` → 合并到候选队列。
- 行业特定深链：products 列表页 → 进入单个 product 页抽具体零件/材料。

**D. 联系人抽取增强**
- 从 Contact/About 页抽**姓名 + 职位**（不仅是 email），写入 `contacts` 表。
- LinkedIn URL 发现（`<a href="*linkedin*">`）。

**E. PDF 抽取修复**
- 给 `PDFExtractor` 注入 fetcher（复用 site 的 Fetcher），修复 #8。
- 公司文档（catalog/brochure）结构化提取能力参数（吨位、公差、认证）→ 已部分实现，补 fetcher 即可生效。

**F. 数据写入**
- 爬完后填 `employee_count`（从 About/Impressum 抽取）、`contact_phone`、`region`。
- 抽到的多联系人写入 `contacts` 表，主联系人映射回 `lead.contact_email`。

### 5.3 新增 API
- `POST /crawl/{lead_id}` 已存在，增强为支持 `fetcher_type=playwright|http`。
- `GET /crawl/{lead_id}/contacts` — 查看抽取到的联系人。

---

## 6. Email Verification 模块设计

### 6.1 目标
发送前验证邮箱，降低 bounce，保护域名信誉。

### 6.2 验证层级（从轻到重）
1. **格式校验**：正则（已有 email_extractor 基础）。
2. **域名校验**：MX 记录存在性（`socket.getaddrinfo` 或 `dns.resolver`）。
3. **角色/ disposable 检测**：`info@/admin@/noreply@` 标记 role；`mailinator/tempmail` 标记 disposable。
4. **SMTP 握手**（可选，谨慎）：对目标 MX 发 `RCPT TO` 探测，不实际发信。易被拦截，建议用第三方 API（ZeroBounce / NeverBounce / Hunter）。
5. **第三方 API**（推荐）：`EmailVerifier` provider 接口，注入 ZeroBounce/Hunter key。

### 6.3 模块设计
```python
class BaseEmailVerifier(ABC):
    def verify(self, email) -> VerificationResult
    # VerificationResult: {status, score, details}

class RuleBasedVerifier(BaseEmailVerifier):  # 免费，格式+MX+role/disposable
    ...

class ApiEmailVerifier(BaseEmailVerifier):  # ZeroBounce/Hunter
    ...
```

### 6.4 落库与流程集成
- 写 `email_verifications` 表。
- 发送前门禁：`status == 'invalid'` 或 `do_not_contact` → 跳过发送，标记 lead。
- `company_leads.bounce_count` 递增（收到 bounce 事件时）。

### 6.5 新增 API
- `POST /leads/{id}/verify-email` — 触发验证
- `GET /crm/email-quality` — 邮箱健康度统计

### 6.6 依赖
新增 `dnspython`（MX 查询）或 `httpx`（第三方 API）。

---

## 7. Phase 3 开发拆分计划

### 阶段 0：缺陷修复（必须，约 1 天）
- [ ] 修 #1 `crawler/runner.py` text_content 字段名
- [ ] 修 #2 `api/search.py` 补全 HTTPException import
- [ ] 修 #3 `routers/leads.py` 路由顺序（high-priority 前置）
- [ ] 修 #4/#5 crawl_status 一致性 + pages_crawled 类型
- [ ] 修 #6 followup naive/aware 时区统一
- [ ] 修 #8 PDFExtractor 注入 fetcher
- [ ] 补 `data/keywords.txt`

### 阶段 1：数据库与模型层（2 天）
- [ ] 新增 `contacts`, `lead_sources`, `email_verifications`, `email_tracking`, `reply_inbox`, `unsubscribes` 模型
- [ ] `company_leads` 扩展 do_not_contact/bounce_count/channel
- [ ] `outreach_messages` 扩展 tracking_token/open_count/click_count/html_body
- [ ] Alembic `0005_phase3_acquisition.py`
- [ ] CRUD + Schema

### 阶段 2：Lead Source Integration（3 天）
- [ ] `BaseLeadSource` 抽象 + `channel` 属性
- [ ] SerpApiProvider / GoogleCSEProvider（官方 API）
- [ ] BingProvider（Playwright 增强版，UA 池 + 代理 + 验证码检测）
- [ ] CSV/JSON 批量导入端点 `POST /leads/import`
- [ ] `lead_sources` 落库 + 去重
- [ ] API：`POST /sources/search`, `GET /crm/sources`

### 阶段 3：Website Intelligence Crawler 升级（3 天）
- [ ] `Fetcher` 协议 + `HttpFetcher`(httpx+bs4) + `PlaywrightFetcher`(context 复用)
- [ ] 并发爬取（asyncio，限流）
- [ ] sitemap 真正解析
- [ ] 联系人抽取（姓名+职位+LinkedIn）→ `contacts` 表
- [ ] 修 PDFExtractor fetcher 注入
- [ ] 填 employee_count/contact_phone/region
- [ ] 升级 `parse_robots` 支持 Allow/通配符/Crawl-delay

### 阶段 4：Email Verification（2 天）
- [ ] `BaseEmailVerifier` + `RuleBasedVerifier`(格式+MX+role/disposable)
- [ ] `ApiEmailVerifier`(ZeroBounce/Hunter，可配置)
- [ ] `email_verifications` 落库
- [ ] 发送前门禁集成
- [ ] API：`POST /leads/{id}/verify-email`, `GET /crm/email-quality`

### 阶段 5：闭环追踪与 Followup 执行（3 天）
- [ ] HTML 邮件模板（追踪像素 + 链接包装）
- [ ] `email_tracking` 写入（open/click 端点 `GET /t/{token}`）
- [ ] IMAP/webhook 回复检测 → `reply_inbox` + 意图分类
- [ ] 把 `get_due_followups()` 接入 scheduler，实现递进 + 收到回复即停止
- [ ] 退订端点 `GET /unsubscribe?token=` + `unsubscribes` 表
- [ ] 发送节流（每封间隔 + 日配额）
- [ ] 补 outreach approve/send API 端点

### 阶段 6：测试与文档（2 天）
- [ ] 新增测试：test_contacts, test_lead_sources, test_email_verification, test_email_tracking, test_reply_inbox, test_import
- [ ] 修复现有 #7 scheduler 测试盲区
- [ ] README Phase 3 文档 + deployment 更新
- [ ] 全量 pytest 通过 + git commit/push

### 预估总工期：约 16 个工作日

---

## 8. 关键架构决策建议

1. **优先官方搜索 API**：裸爬 Google 不可规模化，provider 接口已就绪，切换成本极低。
2. **爬虫浏览器复用 + HTTP 回退**：当前每页启浏览器的架构是吞吐硬瓶颈，Phase 3 必须解。
3. **合规先行**：退订 + do_not_contact + 发送节流必须在规模化发送前落地，否则域名信誉与法律风险。
4. **联系人实体化**：从扁平字段升级为 `contacts` 表，支撑多触点个性化。
5. **闭环度量**：打开/点击/回复追踪让"获客引擎"真正可度量 ROI，而非只发不测。
6. **路由重构**：统一 `app/api/` 与 `app/routers/`，拆分臃肿的 `routers/leads.py`（338 行）。
