# 项目简介
本文件包含了该项目下所有数据与代码文件的详细说明。
- README.md: 本项目简介
- READNE.pdf: 本项目简介的pdf版本
- 爬虫相关代码与数据
    - weibo_shortdrama_spider.py: 爬取微博上关于“短剧”“付费”相关评论的代码
    - 爬虫获取的数据存放在outputs/目录下
        - weibo_shortdrama_comments_180d.ndjson: 爬虫获得的数据
        - README.md: 对爬虫获得的数据的每个字段的说明
    - make_comment_wordcloud.py: 使用outputs/weibo_shortdrama_comments_180d.ndjson制作词云图的代码

- 使用LLM预调查的相关代码与数据
    - pre-survey.ipynb: 使用GPT-OSS进行预调查的代码
    - 预调查的数据存放在data/目录下
        - resp.json: 原始的预调查数据
        - interviews_qa.csv: 存放csv格式的预调查数据

- combined_data.xlsx: MEC的数据明细
- segment.ipynb: 群体划分的代码
- ANOVA+multiple_choice_analysis.ipynb: 单因子方差分析和群体需求统计的代码
- 结构方程模型spsspro报告.docx: 结构方程模型的spsspro报告