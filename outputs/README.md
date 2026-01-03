# 短剧微博爬虫数据字段说明

`outputs/weibo_shortdrama_comments*.ndjson` 每行是一条 JSON，包含一条帖子及其一条评论，字段含义：

- `query`：搜索使用的关键词（默认“短剧”，除非命令行覆盖）。
- `fetched_at`：抓取时间（UTC，ISO8601）。
- `status_id` / `status_mid`：帖子 ID / MID（顶层冗余，便于关联）。
- `status`：帖子信息
  - `id`，`mid`：帖子 ID / MID。
  - `created_at`：微博时间字符串。
  - `reposts`，`comments`，`attitudes`：转发 / 评论 / 点赞数。
  - `text`：帖子正文（长文已展开，去掉 HTML）。
  - `platforms`：正文中提取的平台关键词（如抖音/快手/番茄短剧等）。
  - `dramas`：正文中从《…》/「…」提取的剧名。
  - `user`：发帖人
    - `id`：用户 ID。
    - `screen_name`：昵称。
    - `description`：简介。
    - `location`：位置（若有）。
    - `gender`：性别标记 m/f 或空。
    - `followers`，`follows`：粉丝 / 关注数（字符串或数字原样保存）。
    - `verified_type`：微博认证类型码。
    - `verified_reason`：认证说明。
    - `is_student_hint`：是否命中学生关键词的粗判布尔值。
    - `student_hit`：命中的学生关键词。
- `comment`：对应帖子的单条评论
  - `id`：评论 ID。
  - `root_id`：所属帖子 ID（缺失时回退 `status_id`）。
  - `created_at`：评论时间。
  - `like_count`：评论点赞数。
  - `text`：评论正文（去掉 HTML）。
  - `platforms`：评论中提取的平台关键词。
  - `dramas`：评论中提取的剧名。
  - `user`：评论用户（字段同上）。
- `combined_platforms`：帖子与评论的去重平台关键词合集。
- `combined_dramas`：帖子与评论的去重剧名合集。
