# 美股公司代码匹配（Android 0.7）

数据来自 [Nasdaq Trader 官方证券目录](https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt)，字段参见[官方定义](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs)。目录包含纳斯达克及其他美国交易所的证券。本程序排除 ETF、测试证券，以及名称标明的权证、优先股、权利、单位、债券和基金；当前不覆盖 OTC 全市场。

本地证券目录以 `us` 市场和字符串代码保存记录，例如 `usNVDA`、`usBRK.B`。安卓使用 `NVDA.US`、`BRK.B.US` 展示；US 表示市场，并不冒充具体上市交易所。A 股与港股记录不因美股更新而失效，A 股更新也不会把美股记录错误标为退市。

匹配采用官方名称、确定性的公司后缀处理，以及经过发行人名称校验的常用别名，例如英伟达/NVIDIA、微软/Microsoft、苹果/Apple。不会扫描普通正文里的英文缩写来创建新关联；只处理已经存在的文档公司名称。AI 等易混淆词不自动充当股票别名。旧别名在美股目录更新时重建，防止代码被新发行人使用后沿用旧中文名。

同一发行人的多个普通股类可保留多个代码，例如 Alphabet 的 GOOG 与 GOOGL；不同发行人之间的同名不强行匹配。中文别名为有限的本地维护清单，未匹配公司继续显示待匹配。完整大写代码或带 `.US` 后缀的查询按代码精确匹配，普通中文或英文名称仍支持关键词搜索。

刷新目录：

```sh
python -m app.us_securities
# 如本机网络无法访问，可先从同一官方 HTTPS 地址下载原始目录：
python -m app.us_securities --file /path/to/nasdaqtraded.txt
```

更新有数量异常下降保护，失败时保留现有数据。当前命令为显式刷新，不宣称已实现每日美股目录自动更新。手机只接收已关联资料的证券元数据，不携带整个证券目录，不增加 DeepSeek 请求。只提供代码匹配，不等同于已接入美股财务报表。
