package org.researchdock.mobile;
import android.text.Spanned;
import android.text.style.URLSpan;
import android.view.View;
import android.view.ViewGroup;
import android.widget.*;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import static org.junit.Assert.*;
public class ResearchTextTest {
 @Test public void structuredReadingPreservesTextAndRendersBlocks(){
  InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
   android.content.Context c=InstrumentationRegistry.getInstrumentation().getTargetContext();LinearLayout parent=new LinearLayout(c);parent.setOrientation(LinearLayout.VERTICAL);int[] images={0};
   ResearchText renderer=new ResearchText(c,18,(p,id,caption)->images[0]++);
   renderer.render(parent,"# 主标题\n## 次标题\n### 小标题\n\n核心观点：原文观点\n营业收入 **100万元**，净利润 -5万元。\n\n风险提示：需求下降\n> 保留原始引用\n- 项目一\n\n| 指标 | 数值 |\n| --- | --- |\n| 收入 | 100 |\n\n[来源](https://example.com)\n![图](asset:"+new String(new char[64]).replace('\0','a')+")");
   assertEquals(1,images[0]);assertTrue(find(parent,HorizontalScrollView.class));assertTrue(text(parent).contains("100万元"));assertTrue(text(parent).contains("-5万元"));assertTrue(text(parent).contains("需求下降"));assertFalse(text(parent).contains("**"));assertTrue(link(parent));
   CharSequence unsafe=renderer.inline("[危险](javascript:alert) [安全](https://example.com)");URLSpan[] links=((Spanned)unsafe).getSpans(0,unsafe.length(),URLSpan.class);assertEquals(1,links.length);assertEquals("https://example.com",links[0].getURL());
  });
 }
 @Test public void optionalVisualFixture() throws Exception {
  if(!"true".equals(InstrumentationRegistry.getArguments().getString("visual_fixture")))return;
  android.app.Instrumentation inst=InstrumentationRegistry.getInstrumentation();
  android.app.Activity activity=inst.startActivitySync(new android.content.Intent(inst.getTargetContext(),MainActivity.class).addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK));
  inst.runOnMainSync(()->{try{
   org.json.JSONObject d=new org.json.JSONObject();d.put("document_id","layout-preview");d.put("title","富文本排版样例（非真实研报）");d.put("source_name","本地排版验证");d.put("summary","仅展示原文结构与视觉样式，不包含投资建议。核心信息用独立区域呈现。");d.put("body","# 行业研究\n## 经营表现\n营业收入 **100万元**，净利润 **-5万元**。以上为排版样例数字。\n\n核心观点：原文明确标出的重点\n- 第一项研究观点\n- 第二项研究观点\n\n## 财务数据\n| 指标 | 本期 | 上期 |\n| --- | --- | --- |\n| 营业收入 | 100 | 90 |\n| 净利润 | -5 | 3 |\n\n风险提示：需求变化可能影响经营表现。\n> 这是一段保留原意的引用。\n\n[查看来源](https://example.com)");
   java.lang.reflect.Method m=MainActivity.class.getDeclaredMethod("showArticle",org.json.JSONObject.class);m.setAccessible(true);m.invoke(activity,d);
  }catch(Exception e){throw new RuntimeException(e);}});
  inst.waitForIdleSync();
  try(java.io.FileOutputStream out=new java.io.FileOutputStream(new java.io.File(inst.getTargetContext().getFilesDir(),"typography-preview.png"))){inst.getUiAutomation().takeScreenshot().compress(android.graphics.Bitmap.CompressFormat.PNG,100,out);}
  inst.runOnMainSync(()->{try{java.lang.reflect.Field f=MainActivity.class.getDeclaredField("scroll");f.setAccessible(true);((ScrollView)f.get(activity)).scrollTo(0,Math.round(430*activity.getResources().getDisplayMetrics().density));}catch(Exception e){throw new RuntimeException(e);}});
  inst.waitForIdleSync();
  try(java.io.FileOutputStream out=new java.io.FileOutputStream(new java.io.File(inst.getTargetContext().getFilesDir(),"typography-preview-details.png"))){inst.getUiAutomation().takeScreenshot().compress(android.graphics.Bitmap.CompressFormat.PNG,100,out);}
 }
 private static boolean find(View v,Class<?> cls){if(cls.isInstance(v))return true;if(v instanceof ViewGroup)for(int i=0;i<((ViewGroup)v).getChildCount();i++)if(find(((ViewGroup)v).getChildAt(i),cls))return true;return false;}
 private static String text(View v){StringBuilder s=new StringBuilder();if(v instanceof TextView)s.append(((TextView)v).getText());if(v instanceof ViewGroup)for(int i=0;i<((ViewGroup)v).getChildCount();i++)s.append(text(((ViewGroup)v).getChildAt(i)));return s.toString();}
 private static boolean link(View v){if(v instanceof TextView){CharSequence s=((TextView)v).getText();if(s instanceof Spanned&&((Spanned)s).getSpans(0,s.length(),URLSpan.class).length>0)return true;}if(v instanceof ViewGroup)for(int i=0;i<((ViewGroup)v).getChildCount();i++)if(link(((ViewGroup)v).getChildAt(i)))return true;return false;}
}
