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
   renderer.render(parent,"# 主标题\n## 次标题\n### 小标题\n\n核心观点：原文观点\n营业收入 **100万元**，净利润 -5万元。\n\n风险提示：需求下降\n> 保留原始引用\n- 项目一\n\n| 指标 | 数值 |\n| --- | --- |\n| 收入 | 100 |\n\n[来源](https://example.com)\n![图](asset:"+"a".repeat(64)+")");
   assertEquals(1,images[0]);assertTrue(find(parent,HorizontalScrollView.class));assertTrue(text(parent).contains("100万元"));assertTrue(text(parent).contains("-5万元"));assertTrue(text(parent).contains("需求下降"));assertFalse(text(parent).contains("**"));assertTrue(link(parent));
   CharSequence unsafe=renderer.inline("[危险](javascript:alert) [安全](https://example.com)");URLSpan[] links=((Spanned)unsafe).getSpans(0,unsafe.length(),URLSpan.class);assertEquals(1,links.length);assertEquals("https://example.com",links[0].getURL());
  });
 }
 private static boolean find(View v,Class<?> cls){if(cls.isInstance(v))return true;if(v instanceof ViewGroup)for(int i=0;i<((ViewGroup)v).getChildCount();i++)if(find(((ViewGroup)v).getChildAt(i),cls))return true;return false;}
 private static String text(View v){StringBuilder s=new StringBuilder();if(v instanceof TextView)s.append(((TextView)v).getText());if(v instanceof ViewGroup)for(int i=0;i<((ViewGroup)v).getChildCount();i++)s.append(text(((ViewGroup)v).getChildAt(i)));return s.toString();}
 private static boolean link(View v){if(v instanceof TextView){CharSequence s=((TextView)v).getText();if(s instanceof Spanned&&((Spanned)s).getSpans(0,s.length(),URLSpan.class).length>0)return true;}if(v instanceof ViewGroup)for(int i=0;i<((ViewGroup)v).getChildCount();i++)if(link(((ViewGroup)v).getChildAt(i)))return true;return false;}
}
