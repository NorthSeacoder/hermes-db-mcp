# Data Model: Hermes DB-First

**Workspace**: `hermes-db-first` | **Date**: 2026-05-23

---

## Schema Setup

```sql
-- 创建独立 schema 和用户
CREATE USER hermes_user WITH PASSWORD 'hermes_Str0ng2026';
CREATE SCHEMA hermes AUTHORIZATION hermes_user;

-- 启用 pgvector 扩展（需 superuser）
CREATE EXTENSION IF NOT EXISTS vector;

-- 授权
GRANT USAGE ON SCHEMA hermes TO hermes_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA hermes TO hermes_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA hermes GRANT ALL ON TABLES TO hermes_user;
```

---

## Entities

### Topic（选题）— 表名: `hermes.topics`

**描述**: 公众号选题，含账号归属、状态流转、语义向量

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK, DEFAULT gen_random_uuid() | 主键 |
| title | VARCHAR(200) | NOT NULL | 选题标题 |
| angle | TEXT | | 核心角度（一句话） |
| account | VARCHAR(50) | NOT NULL | 目标账号缩写 |
| status | VARCHAR(20) | NOT NULL, DEFAULT 'draft' | 状态 |
| priority | CHAR(1) | DEFAULT 'B' | 优先级 A/B/C |
| column_name | VARCHAR(50) | | 适用栏目 |
| resonance | VARCHAR(10) | | 共鸣度：高/中/低 |
| content | TEXT | | 选题详细描述/备注 |
| source | VARCHAR(50) | DEFAULT 'topic-inbox' | 来源 skill |
| embedding | vector(1024) | | 语义向量 |
| published_url | TEXT | | 发布后的文章链接 |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | 更新时间 |

**索引**:
- `idx_topics_account_status` on (account, status)
- `idx_topics_created_at` on (created_at DESC)
- `idx_topics_embedding_hnsw` on embedding using hnsw (embedding vector_cosine_ops)

**状态转换**:

```text
draft → writing → published
  ↘               ↗
   → archived ←──┘
```

- `draft`: 新入库，待写
- `writing`: 正在撰写
- `published`: 已发布（附 published_url）
- `archived`: 归档/放弃

---

### NovelInspiration（小说灵感）— 表名: `hermes.novel_inspirations`

**描述**: 小说灵感碎片，含书目归属、类型分类、语义向量

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK, DEFAULT gen_random_uuid() | 主键 |
| content | TEXT | NOT NULL | 灵感内容 |
| book_id | VARCHAR(50) | NOT NULL | 书目标识（缩写） |
| category | VARCHAR(20) | NOT NULL | 类型标签 |
| status | VARCHAR(20) | NOT NULL, DEFAULT 'candidate' | 状态 |
| title | VARCHAR(200) | | 简洁标题 |
| chapter_hint | VARCHAR(100) | | 关联章节/卷提示 |
| embedding | vector(1024) | | 语义向量 |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | 更新时间 |

**索引**:
- `idx_novel_book_category` on (book_id, category)
- `idx_novel_created_at` on (created_at DESC)
- `idx_novel_embedding_hnsw` on embedding using hnsw (embedding vector_cosine_ops)

**category 枚举值**:
- `hook`: 钩子
- `scene`: 场景
- `setting`: 设定
- `character`: 角色
- `conflict`: 冲突
- `world`: 世界观
- `plot`: 情节

**状态转换**:

```text
candidate → adopted → used
    ↘
     → archived
```

- `candidate`: 候选灵感
- `adopted`: 已采纳进大纲
- `used`: 已在正文中使用
- `archived`: 归档/弃用

---

## Relationships

```text
Topic N:1 Account (通过 account 字段逻辑关联，无外键)
NovelInspiration N:1 Book (通过 book_id 字段逻辑关联，无外键)
```

不建立物理外键——账号和书目信息由 Hermes skill 层管理，DB 层只做存储和检索。

---

## DDL Scripts

```sql
-- init.sql: 完整初始化脚本

SET search_path TO hermes;

-- Topics
CREATE TABLE IF NOT EXISTS topics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(200) NOT NULL,
    angle TEXT,
    account VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    priority CHAR(1) DEFAULT 'B',
    column_name VARCHAR(50),
    resonance VARCHAR(10),
    content TEXT,
    source VARCHAR(50) DEFAULT 'topic-inbox',
    embedding vector(1024),
    published_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_topics_account_status ON topics (account, status);
CREATE INDEX idx_topics_created_at ON topics (created_at DESC);

-- Novel Inspirations
CREATE TABLE IF NOT EXISTS novel_inspirations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    book_id VARCHAR(50) NOT NULL,
    category VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'candidate',
    title VARCHAR(200),
    chapter_hint VARCHAR(100),
    embedding vector(1024),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_novel_book_category ON novel_inspirations (book_id, category);
CREATE INDEX idx_novel_created_at ON novel_inspirations (created_at DESC);

-- HNSW 向量索引（数据量 > 1000 后再创建效果更好，初期可跳过）
-- CREATE INDEX idx_topics_embedding_hnsw ON topics
--     USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
-- CREATE INDEX idx_novel_embedding_hnsw ON novel_inspirations
--     USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- updated_at 自动更新触发器
CREATE OR REPLACE FUNCTION hermes.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_topics_updated_at
    BEFORE UPDATE ON topics
    FOR EACH ROW EXECUTE FUNCTION hermes.update_updated_at();

CREATE TRIGGER trg_novel_updated_at
    BEFORE UPDATE ON novel_inspirations
    FOR EACH ROW EXECUTE FUNCTION hermes.update_updated_at();
```

---

## Redis Cache Schema

```text
Key pattern                          | Type   | TTL  | 用途
hermes:topics:recent:{account}       | ZSET   | 7d   | 最近7天选题，score=timestamp
hermes:novel:recent:{book_id}        | ZSET   | 7d   | 最近7天灵感，score=timestamp
hermes:topic:{id}                    | HASH   | 7d   | 单条选题详情缓存
hermes:novel:{id}                    | HASH   | 7d   | 单条灵感详情缓存
```

写入时同步更新 Redis；读取时先查 Redis，miss 则查 PG 并回填。

---

## Migration Notes

- 无 Flyway/Alembic — Hermes 是 Python 脚本集，用手动 SQL 文件管理
- 初始化脚本放在 `.hermes/scripts/db/init.sql`
- 历史数据迁移脚本 `.hermes/scripts/db/migrate.py`：解析现有 `选题收集箱.md` 和 `灵感池.md`，批量写入 + 生成 embedding
- HNSW 索引在数据量达到 ~1000 条后手动创建（小数据量下全表扫描更快）
