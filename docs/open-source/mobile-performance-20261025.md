# Android 0.8.0：阅读性能与布局

长文改为逐帧分批创建原生文字控件，每批最多12行、约6毫秒处理预算，离开文章即停止后续排版。正文仍完整保留，不请求模型重新解释或删减。文本使用简单断行与预编译正则；超长连续多行段落按边界分段。表格仍一次生成，整篇最终仍保留原生视图，并非完整的列表虚拟化。

阅读进度只在百分比变化时更新，未完成排版不会覆盖旧进度；用户已经滚动时不强制跳回旧位置。原来的返回列表位置、筛选与已加载页数继续保留。目录在排版完成后可用。

公司映射按资料批次缓存，资料覆盖计数一次汇总，目录每次显示60项，支持继续加载。公司名与股票代码匹配规则保留。图片接近可视区才下载、缩放解码；远离屏幕的位图释放，返回后按需恢复。PDF 栅格化移到独立后台线程，翻页结果受导航状态保护。

顶部统计与导航收紧，正文标题、摘要、引用、表格和财务指标继续使用既有分级配色。没有增加模型调用或权限。

## 新图标

图标通过内置 imagegen 生成（builtin 模式），生产资源为 `android/app/src/main/res/drawable-nodpi/launcher_art.png`，采用自适应图标掩模。完整设计提示词：

> Use case: logo-brand. Create a single production Android launcher icon for ResearchDock (研迹), a private financial research reading library. Square 1024x1024 full-bleed icon artwork, no device mockup, no surrounding margins, no text or letters, no watermark. Deep forest green solid background matching #246B53. A bold centered ivory geometric open-book mark with an elegant small amber bookmark and three ascending research-page strokes integrated into the book, evoking knowledge and research history, not a trading arrow. Flat precision vector-like shapes, exceptional legibility at 48 pixels, calm premium editorial identity. Keep all meaningful symbol strokes inside central 60 percent safe zone for Android adaptive icon masks; background extends to every edge. Do not pre-round the outer square.

## 验证口径

使用同一小米手机、同一资料目录与同一个测试APK，对比旧版0.7.1和新版0.8.0。测试记录公司目录生成处理时间、450段合成长文的打开处理时间与排版完成时间。处理时间衡量主线程同步工作，不等于实际帧率，也不代表所有文章均无卡顿。另检查取消排版、返回位置、正文格式及实际图标。

实测（小米10 Pro，935篇资料，合成长文42,778字）：

| 指标 | 0.7.1 | 0.8.0 |
| --- | ---: | ---: |
| 公司目录生成，3次中位数 | 911.1 ms | 60.9 ms |
| 长文打开同步处理 | 432.3 ms | 21.5 ms |
| 长文排版完成 | 811.3 ms | 1225.7 ms |

新版通过分批排版缩短一次连续占用主线程的时间，完整排版耗时会增加。9项安卓回归测试通过；真实资料返回列表后，可见标题与坐标一致；12页PDF前两页切换及固定工具栏检查通过。
