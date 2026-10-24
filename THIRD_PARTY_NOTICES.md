# 第三方代码与内容

本项目以 MIT 许可证发布自有代码。Python 依赖、可选 CLI、字体和系统工具保留各自许可证，不因本仓库的 MIT 许可证而变更。

- Python 依赖列于 requirements.txt / requirements-dev.txt，使用 pip 安装，源码包不捆绑虚拟环境。
- 知识星球 CLI 为可选外部依赖，由用户从官方项目自行安装与授权。本仓库不捆绑 CLI、Skill 或认证文件。参考：https://github.com/unnoo/zsxq-skill
- PDF 中文字体优先使用用户系统中已有的 Arial Unicode；本仓库不分发该字体。不可用时使用 ReportLab 的 STSong CID 字体引用，阅读器的中文字体支持可能影响展示。Poppler 是可选预览工具。
- `app/data/international-public-reports.json` 只含公开报告的标题、官方链接和简短中文导读，不分发报告二进制或付费正文。
- 证券名称、行情、财务数据、研报、图片、有道分享及社区内容归相应权利人所有。公开访问不等于允许再分发；用户应遵守来源许可与服务条款。

本项目未获 Bloomberg、各投行、知识星球、有道或 DeepSeek 的背书，机构名称仅用于说明来源适配与接口目标。
